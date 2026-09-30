"""
network.py - Server en Client netwerkklassen voor multiplayer
Server is een universele aggregator; alle clients (incl. host-client)
zijn gelijk.
"""

import socket
import threading
import time
import json
import os
import io
import tempfile

import pygame

from .protocol import encode_packet, decode_packet
from ..core.logger import log as _log

# Maximale grootte van één UDP-datagram naar de client. Ruim onder de
# 1500-byte MTU blijven zodat de router niets hoeft te fragmenteren: één
# verloren fragment zou anders het hele state-frame kosten.
STATE_CHUNK_SIZE = 1200

# Wat er om de payload heen zit als het frame in stukken gaat: het type-byte,
# drie keys, de tags en de lengtes. Afgerond, zodat de envelop nooit het
# limiet doorduwt.
_STATE_CHUNK_OVERHEAD = 32
_STATE_CHUNK_PAYLOAD = STATE_CHUNK_SIZE - _STATE_CHUNK_OVERHEAD

# Hoe lang de client stukken van een gebroken state-pakket bewaart voordat
# hij ze weggooit. Bij een nieuw frame begint de telling sowieso opnieuw.
STATE_CHUNK_TIMEOUT = 2.0

# Skin-uploads: max grootte en hoe lang onvolledige uploads worden bewaard.
SKIN_MAX_SIZE = 5 * 1024 * 1024
SKIN_UPLOAD_TIMEOUT = 10.0

# Stukken per burst en de pauze ertussen. Zonder pauze stuurt de klapper alle
# stukken in een keer en loopt de ontvangstbuffer van de server over.
SKIN_UPLOAD_BURST = 16
SKIN_UPLOAD_PAUSE = 0.002

# Zelfde idee voor het downloaden, maar de klapper is hier de server en de
# ontvangstbuffer die volloopt die van de client. Een skin van een paar
# honderd kB is ruim zevenhonderd stukken; zonder pauze gaan die er in één
# keer uit en blijft een groot deel in de kast van het netwerk hangen.
#
# Hoeveel stukken per burst is nu vooral een kwestie van snelheid, want de
# client vraagt zelf een ruime ontvangstbuffer aan en vult de gaten die
# overblijven ook zelf aan. De pauze duurt op Windows 15 ms ongeacht wat je
# vraagt, dus elke burst kost tijd: 64 stukken is 78 KB per burst en een
# flinke skin in een paar tientallen milliseconden.
SKIN_DOWNLOAD_BURST = 64
SKIN_DOWNLOAD_PAUSE = 0.001


def _save_surface_as_png(img):
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmpf:
        tmp_path = tmpf.name
    try:
        pygame.image.save(img, tmp_path)
        with open(tmp_path, "rb") as tmpf:
            data = tmpf.read()
    except pygame.error:
        os.unlink(tmp_path)
        raise
    os.unlink(tmp_path)
    return data


class ServerIO(threading.Thread):
    """Headless server: all-UDP game data I/O + state relay"""
    def __init__(self, port, max_players=None):
        super().__init__(daemon=True)
        from ..core.config import MAX_PLAYERS
        self.port = port
        self.max_players = MAX_PLAYERS if max_players is None else max_players
        self.running = True

        # UDP for all communication (handshake + game data)
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)
        # Een skin-upload komt binnen als honderden datagrams in een korte
        # burst. Zonder ruime ontvangstbuffer gooit de kernel er daarvan weg
        # voordat de server ze bij een tick allemaal heeft gelezen.
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
        self.udp_socket.setblocking(False)
        self.udp_socket.bind(('0.0.0.0', port))
        self._state_tick = 0

        # Connected clients: [(addr, player_id, name)]
        self.clients = []
        self.clients_lock = threading.Lock()

        # Latest inputs per client (player_id → data dict)
        self.inputs = {}

        # Server game state
        from .server_game import ServerGame
        self.server_game = ServerGame()



        # Stale client tracking
        self.last_seen = {}

        # Pending registrations (token → {name, skin_id, addr, time})
        self._pending_connect = {}
        self.next_id = 0  # First client (host) gets 0

        # Lobby countdown (frames until game start)
        self.countdown = 0

        # Pseudo-host tracking (first joiner is host)
        self.host_pid = -1

        # Lobby options (host can toggle these)
        self.lobby_options = {"shared_health": True, "shared_ammo": True}

        # Server-side skin management
        self.skin_manifest = []
        self._next_skin_id = 100
        self._upload_chunks = {}
        self._load_skin_manifest()

    # ── Server-side skin management ─────────────────────────────

    def _load_skin_manifest(self):
        path = "server_skins/manifest.json"
        try:
            with open(path) as f:
                data = json.load(f)
                self.skin_manifest = data.get("skins", [])
                self._next_skin_id = data.get("next_id", 100)
        except (OSError, json.JSONDecodeError):
            self.skin_manifest = []
            self._next_skin_id = 100

    def _save_skin_manifest(self):
        os.makedirs("server_skins", exist_ok=True)
        with open("server_skins/manifest.json", "w") as f:
            json.dump({"next_id": self._next_skin_id, "skins": self.skin_manifest}, f, indent=2)

    def _handle_skin_upload_udp(self, packet, addr):
        name = packet.get("name", "Unnamed")
        uploader = packet.get("uploader", "Unknown")
        raw = packet.get("data")
        total = packet.get("total")

        if total:
            # Een heel PNG past niet in één UDP-datagram, dus uploads komen in
            # stukken binnen. Onderdelen worden per afzender bewaard tot elke
            # index 0..total-1 binnen is. Bewust niet-destructief: de client
            # stuurt de hele rij nog eens zodra er iets ontbreekt, dus een
            # half uitgelezen buffer weggooien zou elke poging ruïneren.
            if not isinstance(raw, (bytes, bytearray)):
                return
            index = packet.get("chunk", 0)
            entry = self._upload_chunks.get(addr)
            stale = (entry is None or entry["total"] != total
                     or time.time() - entry["time"] > SKIN_UPLOAD_TIMEOUT)
            if stale:
                entry = {"chunks": {}, "total": total, "name": name,
                         "uploader": uploader, "time": time.time()}
                self._upload_chunks[addr] = entry
            entry["time"] = time.time()
            entry["name"] = name
            entry["uploader"] = uploader
            # Een herhaald stuk met dezelfde index overschrijft zichzelf, dus
            # een tweede poging bouwt gewoon verder.
            entry["chunks"][index] = bytes(raw)
            if len(entry["chunks"]) != total:
                return  # wacht nog op stukken
            try:
                raw = b"".join(entry["chunks"][i] for i in range(total))
            except KeyError:
                return  # gat in de rij: wacht tot de client de rij herhaalt
            self._upload_chunks.pop(addr, None)

        if not isinstance(raw, (bytes, bytearray)) or not raw:
            resp = {"type": "skin_upload_ack", "skin_id": -1, "success": False, "error": "Geen data"}
            self.udp_socket.sendto(encode_packet(resp), addr)
            return
        if len(raw) > SKIN_MAX_SIZE:
            resp = {"type": "skin_upload_ack", "skin_id": -1, "success": False, "error": "Bestand te groot"}
            self.udp_socket.sendto(encode_packet(resp), addr)
            return
        try:
            img = pygame.image.load(io.BytesIO(raw))
        except pygame.error:
            resp = {"type": "skin_upload_ack", "skin_id": -1, "success": False, "error": "Niet-ondersteund beeldformaat"}
            self.udp_socket.sendto(encode_packet(resp), addr)
            return
        raw = _save_surface_as_png(img)
        MAX_SIZE = 1024 * 1024
        if len(raw) > MAX_SIZE:
            w, h = img.get_size()
            scale = 512 / max(w, h)
            new_w, new_h = int(w * scale), int(h * scale)
            try:
                img = pygame.transform.smoothscale(img, (new_w, new_h))
            except pygame.error:
                img = pygame.transform.scale(img, (new_w, new_h))
            raw = _save_surface_as_png(img)
        sid = self._next_skin_id
        self._next_skin_id += 1
        os.makedirs("server_skins", exist_ok=True)
        with open(f"server_skins/skin_{sid}.png", "wb") as f:
            f.write(raw)
        entry = {"id": sid, "name": name, "uploader": uploader}
        self.skin_manifest.append(entry)
        self._save_skin_manifest()
        resp = {"type": "skin_upload_ack", "skin_id": sid, "success": True}
        self.udp_socket.sendto(encode_packet(resp), addr)
        self._broadcast_skin_manifest()

    def _get_skin_data(self, skin_id):
        path = f"server_skins/skin_{skin_id}.png"
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None

    def _broadcast_skin_manifest(self):
        packet = {"type": "skin_manifest_update", "skin_manifest": self.skin_manifest}
        data = encode_packet(packet)
        with self.clients_lock:
            for c_addr, _, _ in self.clients:
                try:
                    self.udp_socket.sendto(data, c_addr)
                except OSError:
                    pass

    def run(self):
        TICK_RATE = 1 / 60  # ~60 Hz server tick
        while self.running:
            t0 = time.perf_counter()
            self._receive_udp()
            self.server_game.process_inputs(self.inputs)
            self.server_game.tick()
            self._state_tick = (self._state_tick + 1) % 2
            if self.server_game.initialized and self._state_tick == 0:
                self._send_server_state()
            self._handle_countdown()
            self._cleanup_stale()
            elapsed = time.perf_counter() - t0
            if elapsed < TICK_RATE:
                time.sleep(TICK_RATE - elapsed)

    # ── UDP receive ────────────────────────────────────────────

    def _receive_udp(self):
        while True:
            try:
                data, addr = self.udp_socket.recvfrom(65536)
            except BlockingIOError:
                return
            except OSError:
                return

            try:
                packet = decode_packet(data)
            except Exception as e:
                _log(f"decode error: {e}")
                continue

            ptype = packet.get("type")
            pid = packet.get("player_id", -1)

            if ptype == "connect":
                token = packet.get("token", "")
                name = packet.get("name", f"Player {self.next_id}")
                skin_id = packet.get("skin_id", 0)
                if token in self._pending_connect:
                    pid = self._pending_connect[token]["pid"]
                else:
                    pid = self.next_id
                    self.next_id += 1
                    self._pending_connect[token] = {"pid": pid, "name": name, "skin_id": skin_id, "addr": addr, "time": time.time()}
                resp = {"type": "accept", "player_id": pid, "skin_manifest": self.skin_manifest}
                self.udp_socket.sendto(encode_packet(resp), addr)

            elif ptype == "skin_request":
                req_skin_id = packet.get("skin_id", -1)
                raw = self._get_skin_data(req_skin_id)
                if raw is not None:
                    CHUNK = 1200
                    total = (len(raw) + CHUNK - 1) // CHUNK
                    # De client mag zeggen welke stukken hij nog mist. UDP
                    # gooit er willekeurig weg, dus na de eerste ronde blijft
                    # er altijd een gat over. Alleen dat gat opnieuw sturen is
                    # het verschil tussen één keer de skin en elke keer de
                    # hele skin opnieuw. Ontbreekt de lijst, dan sturen we
                    # gewoon alles, zodat een oudere client nog werkt.
                    gevraagd = packet.get("chunks")
                    if isinstance(gevraagd, (list, tuple)):
                        rij = [i for i in gevraagd
                               if isinstance(i, int) and 0 <= i < total]
                    else:
                        rij = range(total)
                    for n, i in enumerate(rij):
                        chunk = raw[i*CHUNK:(i+1)*CHUNK]
                        try:
                            self.udp_socket.sendto(encode_packet(
                                {"type": "skin_chunk", "skin_id": req_skin_id, "chunk": i, "total": total, "data": chunk}
                            ), addr)
                        except OSError:
                            pass
                        # Met een pauze ertussen, anders stuurt de klapper
                        # alle stukken in een keer en loopt de ontvangstbuffer
                        # van de client over. Precies dezelfde reden als bij
                        # het uploaden, zie SKIN_UPLOAD_PAUSE hierboven.
                        if n % SKIN_DOWNLOAD_BURST == SKIN_DOWNLOAD_BURST - 1:
                            time.sleep(SKIN_DOWNLOAD_PAUSE)
                else:
                    resp = {"type": "skin_data", "skin_id": req_skin_id, "data": None}
                    self.udp_socket.sendto(encode_packet(resp), addr)

            elif ptype == "skin_upload":
                self._handle_skin_upload_udp(packet, addr)

            elif ptype == "register":
                pid = packet.get("player_id", -1)
                pending = self._pending_connect.get(packet.get("token", ""), {})
                name = pending.get("name", f"Player {pid}")
                skin_id = pending.get("skin_id", 0)
                should_broadcast = False
                is_full = False
                game_already_started = self.server_game.initialized
                with self.clients_lock:
                    for c_addr, c_pid, _ in self.clients:
                        if c_pid == pid:
                            break
                    else:
                        if len(self.clients) < self.max_players:
                            self.clients.append((addr, pid, name))
                            if self.host_pid == -1:
                                self.host_pid = pid
                            should_broadcast = True
                            self.server_game.register_player(pid, name, skin_id)
                            if game_already_started:
                                spawn = self.server_game.get_spawn_position()
                                if spawn:
                                    self.server_game.players[pid]["pos"] = spawn
                                    self.server_game.players[pid]["state"] = "game"
                                    self.server_game.players[pid]["ready"] = True
                        else:
                            # Niet stilzwijgend negeren: anders wacht de
                            # speler 30 seconden tot "verbinding verloren".
                            is_full = True
                if is_full:
                    try:
                        self.udp_socket.sendto(encode_packet(
                            {"type": "server_full", "max_players": self.max_players}
                        ), addr)
                    except OSError:
                        pass
                    self._pending_connect.pop(packet.get("token", ""), None)
                    self.last_seen.pop(pid, None)
                    continue
                if should_broadcast:
                    self._broadcast_lobby()
                self.last_seen[pid] = time.time()

            elif ptype == "pos_update":
                with self.clients_lock:
                    if not any(c_pid == pid for _, c_pid, _ in self.clients):
                        continue
                self.last_seen[pid] = time.time()
                data = packet.get("data", {})
                self.inputs[pid] = data

            elif ptype == "start_game":
                # Alleen de host mag de groep in beweging zetten. Zonder deze
                # knop wacht iedereen tot ALLE spelers READY zijn.
                with self.clients_lock:
                    is_client = any(c_pid == pid for _, c_pid, _ in self.clients)
                if not is_client or pid != self.host_pid:
                    _log(f"start_game genegeerd voor pid {pid} (host is {self.host_pid})")
                    continue
                if self.server_game.initialized:
                    game_start_packet = encode_packet({
                        "type": "game_start",
                        "level": self.server_game.level
                    })
                    for _ in range(3):
                        try:
                            self.udp_socket.sendto(game_start_packet, addr)
                        except OSError:
                            pass
                else:
                    self.countdown = 0
                    self.server_game.set_shared_options(self.lobby_options)
                    self.server_game.init_world()
                    game_start_packet = encode_packet({"type": "game_start", "level": 0})
                    with self.clients_lock:
                        for c_addr, _, _ in self.clients:
                            for _ in range(3):
                                try:
                                    self.udp_socket.sendto(game_start_packet, c_addr)
                                except OSError:
                                    pass

            elif ptype == "disconnect":
                should_broadcast = False
                should_reset = False
                with self.clients_lock:
                    for i, (c_addr, c_pid, c_name) in enumerate(self.clients):
                        if c_pid == pid:
                            self.clients.pop(i)
                            should_broadcast = True
                            break
                    if pid == self.host_pid:
                        remaining = [c_pid for _, c_pid, _ in self.clients]
                        self.host_pid = min(remaining) if remaining else -1
                    should_reset = len(self.clients) == 0
                self.last_seen.pop(pid, None)
                self.inputs.pop(pid, None)
                self.server_game.remove_player(pid)
                if self.countdown > 0:
                    self.countdown = 0
                if should_reset:
                    self.server_game.reset_to_lobby()
                    self.next_id = 0
                    self.host_pid = -1
                    self.inputs.clear()
                    self.last_seen.clear()
                    self._pending_connect.clear()
                if should_broadcast:
                    self._broadcast_lobby()

            elif ptype == "select_skin":
                skin_id = packet.get("skin_id", 0)
                self.server_game.set_skin(pid, skin_id)
                self._broadcast_lobby()
                self.last_seen[pid] = time.time()

            elif ptype == "ready":
                with self.clients_lock:
                    if not any(c_pid == pid for _, c_pid, _ in self.clients):
                        _log(f"ready: pid {pid} not in clients, ignoring")
                        continue
                self.server_game.toggle_ready(pid)
                if not self.server_game.initialized:
                    if self._all_players_ready():
                        if self.countdown <= 0:
                            self.countdown = 180
                    else:
                        if self.countdown > 0:
                            self.countdown = 0
                players = self.get_lobby_players()
                # Direct unicast response to sender FIRST, then broadcast
                direct_resp = {"type": "lobby_info", "players": players}
                if self.server_game.initialized:
                    direct_resp["game_active"] = True
                try:
                    self.udp_socket.sendto(encode_packet(direct_resp), addr)
                except OSError:
                    pass
                self._broadcast_lobby()
                self.last_seen[pid] = time.time()

            elif ptype == "request_lobby":
                self._broadcast_lobby()
                self.last_seen[pid] = time.time()

            elif ptype == "join_game":
                with self.clients_lock:
                    if not any(c_pid == pid for _, c_pid, _ in self.clients):
                        continue
                if self.server_game.initialized:
                    spawn = self.server_game.get_spawn_position()
                    if spawn and pid in self.server_game.players:
                        self.server_game.players[pid]["pos"] = spawn
                        self.server_game.players[pid]["state"] = "game"
                    game_start_packet = encode_packet({
                        "type": "game_start",
                        "level": self.server_game.level
                    })
                    for _ in range(5):
                        try:
                            self.udp_socket.sendto(game_start_packet, addr)
                        except OSError:
                            pass
                self.last_seen[pid] = time.time()

            elif ptype == "set_lobby_option":
                with self.clients_lock:
                    if not any(c_pid == pid for _, c_pid, _ in self.clients):
                        continue
                if pid == self.host_pid:
                    key = packet.get("option_key", "")
                    value = packet.get("option_value")
                    if key in ("shared_health", "shared_ammo") and isinstance(value, bool):
                        self.lobby_options[key] = value
                        self.server_game.set_shared_options(self.lobby_options)
                        self._broadcast_lobby()
                self.last_seen[pid] = time.time()

            elif ptype == "ping":
                with self.clients_lock:
                    if not any(c_pid == pid for _, c_pid, _ in self.clients):
                        continue
                self.last_seen[pid] = time.time()
                try:
                    self.udp_socket.sendto(encode_packet({"type": "pong"}), addr)
                except OSError:
                    pass

    # ── State relay ────────────────────────────────────────────

    def _send_server_state(self):
        state = self.server_game.get_state()
        if not state:
            return
        state["lobby_options"] = self.lobby_options
        data = encode_packet(state)
        with self.clients_lock:
            targets = [c_addr for c_addr, _, _ in self.clients]
        if not targets:
            return
        if len(data) <= STATE_CHUNK_SIZE:
            for addr in targets:
                try:
                    self.udp_socket.sendto(data, addr)
                except OSError:
                    pass
            return
        # Groter dan het limiet: opsplitsen, anders fragmenteert UDP en kost
        # één verloren fragment meteen het hele frame. Gebeurt vanaf ~5 spelers
        # op de grotere levels.
        total = (len(data) + _STATE_CHUNK_PAYLOAD - 1) // _STATE_CHUNK_PAYLOAD
        for i in range(total):
            part = data[i * _STATE_CHUNK_PAYLOAD:(i + 1) * _STATE_CHUNK_PAYLOAD]
            pkt = encode_packet({"type": "state_chunk", "chunk": i,
                                 "total": total, "data": part})
            for addr in targets:
                try:
                    self.udp_socket.sendto(pkt, addr)
                except OSError:
                    pass

    def _broadcast_lobby(self):
        players = self.get_lobby_players()
        packet = {"type": "lobby_info", "players": players}
        if self.server_game.initialized:
            packet["game_active"] = True
        if self.countdown > 0:
            packet["countdown"] = self.countdown
        packet["host_pid"] = self.host_pid
        packet["lobby_options"] = self.lobby_options
        data = encode_packet(packet)
        with self.clients_lock:
            for c_addr, _, _ in self.clients:
                try:
                    self.udp_socket.sendto(data, c_addr)
                except OSError:
                    pass

    def _cleanup_stale(self):
        now = time.time()
        # Half afgeleverde skin-uploads laten we niet eeuwig staan.
        for addr, entry in list(self._upload_chunks.items()):
            if now - entry["time"] > SKIN_UPLOAD_TIMEOUT:
                del self._upload_chunks[addr]
        for token, info in list(self._pending_connect.items()):
            if now - info["time"] > 15:
                del self._pending_connect[token]
        stale = []
        should_reset = False
        with self.clients_lock:
            for addr, pid, name in self.clients:
                last = self.last_seen.get(pid, now)
                if now - last > 8:
                    stale.append((addr, pid, name))
            for _, pid, name in stale:
                self.clients = [(a, p, n) for a, p, n in self.clients if p != pid]
                self.last_seen.pop(pid, None)
                self.inputs.pop(pid, None)
                self.server_game.remove_player(pid)
                if pid == self.host_pid:
                    remaining = [c_pid for _, c_pid, _ in self.clients]
                    self.host_pid = min(remaining) if remaining else -1
            should_reset = len(self.clients) == 0 and stale
        if should_reset:
            self.server_game.reset_to_lobby()
            self.next_id = 0
            self.host_pid = -1
            self.inputs.clear()
            self.last_seen.clear()
            self._pending_connect.clear()
        if stale:
            if self.countdown > 0:
                self.countdown = 0
            self._broadcast_lobby()

    def _handle_countdown(self):
        if self.countdown > 0 and not self.server_game.initialized:
            self.countdown -= 1
            if self.countdown <= 0:
                try:
                    self.server_game.set_shared_options(self.lobby_options)
                    self.server_game.init_world()
                    self._broadcast_game_start()
                except Exception as e:
                    _log(f"[SERVER] ERROR in countdown init: {e}")

    def _broadcast_game_start(self):
        game_start_packet = encode_packet({"type": "game_start", "level": self.server_game.level})
        with self.clients_lock:
            for c_addr, _, _ in self.clients:
                for _ in range(3):
                    try:
                        self.udp_socket.sendto(game_start_packet, c_addr)
                    except OSError:
                        pass

    def _all_players_ready(self):
        with self.clients_lock:
            pids = [pid for _, pid, _ in self.clients]
        if not pids:
            return False
        for pid in pids:
            pd = self.server_game.players.get(pid)
            if not pd or not pd.get("ready"):
                return False
        return True

    def get_lobby_players(self):
        result = []
        with self.clients_lock:
            for _, pid, name in self.clients:
                pd = self.server_game.players.get(pid, {})
                result.append({"name": name, "pid": pid, "skin_id": pd.get("skin_id", 0), "ready": pd.get("ready", False)})
        return result

    def stop(self):
        self.running = False
        self._broadcast_server_stopped()
        try:
            self.udp_socket.close()
        except OSError:
            pass

    def _broadcast_server_stopped(self):
        packet = {"type": "server_stopped"}
        data = encode_packet(packet)
        with self.clients_lock:
            for c_addr, _, _ in self.clients:
                try:
                    self.udp_socket.sendto(data, c_addr)
                except OSError:
                    pass


class NetworkClient:
    """Client-side networking (runs on ALL clients, including host-client)"""
    def __init__(self):
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setblocking(False)
        self.server_addr = None
        self.player_id = -1
        self.connected = False
        self.skin_id = 0
        self._state_chunks = {}
        self._state_chunks_at = 0.0

    def connect(self, host, port, name, skin_id=0):
        self.skin_id = skin_id
        addr = (host, port)
        token = f"{name}:{time.time()}:{id(self)}"
        for attempt in range(3):
            try:
                packet = {"type": "connect", "name": name, "skin_id": skin_id, "token": token}
                self.udp_socket.sendto(encode_packet(packet), addr)
                self.udp_socket.settimeout(0.5)
                try:
                    data, _ = self.udp_socket.recvfrom(65536)
                    resp = decode_packet(data)
                    if resp.get("type") == "accept":
                        self.server_addr = addr
                        self.player_id = resp["player_id"]
                        self.connected = True
                        from ..assets.skin_manager import SkinManager
                        SkinManager.set_server_addr(self.server_addr)
                        manifest = resp.get("skin_manifest", [])
                        SkinManager.set_manifest(manifest)
                        SkinManager.start_background_download()
                        reg = {"type": "register", "player_id": self.player_id, "token": token}
                        self.udp_socket.sendto(encode_packet(reg), self.server_addr)
                        self._save_config(name, host, port, skin_id)
                        self.udp_socket.setblocking(False)
                        return True
                except socket.timeout:
                    pass
            except OSError:
                pass
        self.udp_socket.setblocking(False)
        self.server_addr = None
        return False

    @staticmethod
    def _save_config(name, ip, port, skin_id=0):
        try:
            with open("mp_config.json", "w") as f:
                json.dump({"last_name": name, "last_ip": ip,
                           "last_port": str(port), "last_skin_id": skin_id}, f)
        except OSError:
            pass

    @staticmethod
    def load_config():
        try:
            with open("mp_config.json") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def send_input(self, input_data):
        if not self.server_addr:
            return
        packet = {"type": "pos_update", "data": input_data, "player_id": self.player_id}
        try:
            self.udp_socket.sendto(encode_packet(packet), self.server_addr)
        except OSError:
            pass

    def send(self, packet):
        if not self.server_addr:
            return
        packet["player_id"] = self.player_id
        try:
            self.udp_socket.sendto(encode_packet(packet), self.server_addr)
        except OSError:
            pass

    def try_recv(self):
        """Receive any UDP packet. Returns parsed dict or None."""
        try:
            data, addr = self.udp_socket.recvfrom(65536)
            return decode_packet(data)
        except BlockingIOError:
            return None
        except Exception:
            return None

    def drain(self, max_packets=64):
        """Lees ALLE packets die klaarstaan, in aankomstvolgorde.

        Eén packet per frame lezen laat de queue groeien zodra de framerate
        even zakt; de client loopt dan steeds verder achter en ziet steeds
        oudere posities. Onvolledige state-chunks worden apart bewaard en pas
        teruggegeven als het hele frame compleet is.
        """
        out = []
        for _ in range(max_packets):
            try:
                data, _ = self.udp_socket.recvfrom(65536)
            except (BlockingIOError, socket.timeout):
                break
            except Exception:
                break
            try:
                packet = decode_packet(data)
            except Exception:
                continue
            if not packet:
                continue
            if packet.get("type") == "state_chunk":
                merged = self._merge_state_chunk(packet)
                if merged is None:
                    continue
                packet = merged
            out.append(packet)
        return out

    def _merge_state_chunk(self, packet):
        """Zet de stukken van een frame weer samen. None als er meer komt."""
        now = time.time()
        if now - self._state_chunks_at > STATE_CHUNK_TIMEOUT:
            self._state_chunks.clear()
        self._state_chunks_at = now
        index = packet.get("chunk", 0)
        total = packet.get("total", 1)
        if index == 0:
            # Beginning van een nieuw frame: een restje van het vorige weggooien.
            self._state_chunks.clear()
        self._state_chunks[index] = packet.get("data") or b""
        if len(self._state_chunks) < total:
            return None
        buf = bytearray()
        for i in range(total):
            part = self._state_chunks.pop(i, None)
            if part is None:
                return None
            buf.extend(part)
        self._state_chunks.clear()
        try:
            return decode_packet(bytes(buf))
        except Exception:
            return None

    def _save_as_png(self, img):
        return _save_surface_as_png(img)

    def upload_skin(self, name, uploader, filepath):
        if not self.server_addr:
            return (False, "Niet verbonden")
        host, port = self.server_addr
        try:
            img = pygame.image.load(filepath)
        except (FileNotFoundError, pygame.error):
            return (False, "Kon afbeelding niet laden")
        try:
            raw = self._save_as_png(img)
        except pygame.error:
            return (False, "Kon afbeelding niet comprimeren")
        MAX_SIZE = SKIN_MAX_SIZE
        if len(raw) > 1024 * 1024:
            w, h = img.get_size()
            scale = 512 / max(w, h)
            new_w, new_h = int(w * scale), int(h * scale)
            try:
                img = pygame.transform.smoothscale(img, (new_w, new_h))
            except pygame.error:
                img = pygame.transform.scale(img, (new_w, new_h))
            try:
                raw = self._save_as_png(img)
            except pygame.error:
                return (False, "Kon afbeelding niet comprimeren")
        if len(raw) > MAX_SIZE:
            return (False, "Bestand te groot (max 5MB)")

        # Een heel PNG past niet in één UDP-datagram, dus in stukken versturen.
        chunk_size = _STATE_CHUNK_PAYLOAD
        total = (len(raw) + chunk_size - 1) // chunk_size

        def _chunks():
            for i in range(total):
                yield encode_packet({
                    "type": "skin_upload", "name": name, "uploader": uploader,
                    "chunk": i, "total": total,
                    "data": raw[i * chunk_size:(i + 1) * chunk_size],
                })

        try:
            self.udp_socket.settimeout(0.5)
            for _ in range(20):
                # Met een pauze ertussen, anders stuurt de klapper alle
                # stukken in een keer en loopt de ontvangstbuffer van de
                # server over voordat hij ze heeft gelezen.
                for i, pkt in enumerate(_chunks()):
                    self.udp_socket.sendto(pkt, self.server_addr)
                    if i % SKIN_UPLOAD_BURST == SKIN_UPLOAD_BURST - 1:
                        time.sleep(SKIN_UPLOAD_PAUSE)
                # Elke round sturen we de hele rij opnieuw: UDP gooit
                # willekeurige stukken weg en we weten niet welke.
                deadline = time.time() + 0.5
                while time.time() < deadline:
                    try:
                        data, _ = self.udp_socket.recvfrom(65536)
                    except socket.timeout:
                        break
                    resp = decode_packet(data)
                    if resp and resp.get("type") == "skin_upload_ack":
                        self.udp_socket.setblocking(False)
                        if resp.get("success"):
                            sid = resp.get("skin_id", -1)
                            return (True, f"Skin #{sid} geupload!", sid)
                        return (False, resp.get("error", "Upload mislukt"))
        except OSError as e:
            return (False, f"Netwerkfout: {str(e)[:50]}")
        finally:
            self.udp_socket.setblocking(False)
        return (False, "Geen response van server")

    def disconnect(self):
        self.connected = False
        self.server_addr = None
        try:
            self.udp_socket.close()
        except OSError:
            pass
