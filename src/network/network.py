"""
network.py - Server en Client netwerkklassen voor multiplayer
Server is een universele aggregator; alle clients (incl. host-client)
zijn gelijk.
"""

import socket
import pickle
import struct
import threading
import queue
import time
import json
import os
import io

import pygame


def _save_surface_as_png(img):
    import tempfile
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
    """Headless server: TCP handshake + UDP game data I/O + state relay"""
    def __init__(self, port, max_players=4):
        super().__init__(daemon=True)
        self.port = port
        self.max_players = max_players
        self.running = True

        # TCP for initial handshake
        self.tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_server.setblocking(False)
        self.tcp_server.bind(('0.0.0.0', port))
        self.tcp_server.listen(max_players)

        # UDP for game data
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.setblocking(False)
        self.udp_socket.bind(('0.0.0.0', port))

        # Connected clients: [(addr, player_id, name)]
        self.clients = []
        self.clients_lock = threading.Lock()

        # Latest inputs per client (player_id → data dict)
        self.inputs = {}

        # Server game state
        from .server_game import ServerGame
        self.server_game = ServerGame()

        # Lobby updates for lobby phase
        self.lobby_updates = queue.Queue()

        # Host name for lobby
        self.host_name = "Host"

        # Stale client tracking
        self.last_seen = {}

        # Pending TCP registrations awaiting UDP registration
        self._pending = {}
        self._pending_lock = threading.Lock()
        self.next_id = 0  # First client (host) gets 0

        # Server-side skin management
        self.skin_manifest = []
        self._next_skin_id = 100
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
            json.dump({"next_id": self._next_skin_id, "skins": self.skin_manifest}, f)

    def _handle_skin_upload(self, sock, packet):
        name = packet.get("name", "Unnamed")
        uploader = packet.get("uploader", "Unknown")
        raw = packet.get("data")
        if not isinstance(raw, (bytes, bytearray)):
            resp = {"type": "skin_upload_ack", "skin_id": -1, "success": False, "error": "Geen data"}
            resp_data = pickle.dumps(resp)
            sock.sendall(struct.pack('!I', len(resp_data)) + resp_data)
            return
        if len(raw) > 5 * 1024 * 1024:
            resp = {"type": "skin_upload_ack", "skin_id": -1, "success": False, "error": "Bestand te groot"}
            resp_data = pickle.dumps(resp)
            sock.sendall(struct.pack('!I', len(resp_data)) + resp_data)
            return
        try:
            img = pygame.image.load(io.BytesIO(raw))
        except pygame.error:
            resp = {"type": "skin_upload_ack", "skin_id": -1, "success": False, "error": "Niet-ondersteund beeldformaat"}
            resp_data = pickle.dumps(resp)
            sock.sendall(struct.pack('!I', len(resp_data)) + resp_data)
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
        resp_data = pickle.dumps(resp)
        sock.sendall(struct.pack('!I', len(resp_data)) + resp_data)
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
        data = pickle.dumps(packet)
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
            self._accept_tcp()
            self._receive_udp()
            self.server_game.process_inputs(self.inputs)
            self.server_game.tick()
            if self.server_game.initialized:
                self._send_server_state()
            self._cleanup_stale()
            elapsed = time.perf_counter() - t0
            if elapsed < TICK_RATE:
                time.sleep(TICK_RATE - elapsed)

    # ── TCP handshake ──────────────────────────────────────────

    def _accept_tcp(self):
        try:
            sock, addr = self.tcp_server.accept()
            sock.settimeout(10.0)
            size_data = self._recv_all(sock, 4)
            if size_data:
                size = struct.unpack('!I', size_data)[0]
                if 0 < size < 5 * 1024 * 1024:
                    data = self._recv_all(sock, size)
                    if data:
                        try:
                            packet = pickle.loads(data)
                        except Exception:
                            sock.close()
                            return
                        if packet.get("type") == "connect":
                            name = packet.get("name", f"Player {self.next_id}")
                            skin_id = packet.get("skin_id", 0)
                            with self._pending_lock:
                                pid = self.next_id
                                self.next_id += 1
                                self._pending[pid] = {"name": name, "skin_id": skin_id}
                            resp = {"type": "accept", "player_id": pid,
                                    "skin_manifest": self.skin_manifest}
                            resp_data = pickle.dumps(resp)
                            sock.sendall(struct.pack('!I', len(resp_data)) + resp_data)

                        elif packet.get("type") == "skin_request":
                            req_skin_id = packet.get("skin_id", -1)
                            print(f"[SERVER] skin_request: id={req_skin_id} from {addr}")
                            raw = self._get_skin_data(req_skin_id)
                            if raw is not None:
                                print(f"[SERVER] skin_request: id={req_skin_id} found, {len(raw)} bytes")
                                resp = {"type": "skin_data", "skin_id": req_skin_id, "data": raw}
                            else:
                                print(f"[SERVER] skin_request: id={req_skin_id} NOT FOUND on disk")
                                resp = {"type": "skin_data", "skin_id": req_skin_id, "data": None}
                            resp_data = pickle.dumps(resp)
                            sock.sendall(struct.pack('!I', len(resp_data)) + resp_data)

                        elif packet.get("type") == "skin_upload":
                            self._handle_skin_upload(sock, packet)
            sock.close()
        except BlockingIOError:
            pass
        except OSError:
            pass

    @staticmethod
    def _recv_all(sock, n):
        data = b''
        while len(data) < n:
            try:
                chunk = sock.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                return None
        return data

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
                packet = pickle.loads(data)
            except Exception:
                continue

            ptype = packet.get("type")
            pid = packet.get("player_id", -1)

            if ptype == "register":
                with self._pending_lock:
                    pending = self._pending.pop(pid, {"name": f"Player {pid}", "skin_id": 0})
                name = pending["name"]
                skin_id = pending["skin_id"]
                should_broadcast = False
                with self.clients_lock:
                    for c_addr, c_pid, _ in self.clients:
                        if c_pid == pid:
                            break
                    else:
                        if len(self.clients) < self.max_players:
                            self.clients.append((addr, pid, name))
                            self.lobby_updates.put(("player_joined", pid, name))
                            should_broadcast = True
                            self.server_game.register_player(pid, name, skin_id)
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
                self.server_game.init_world()
                game_start_packet = pickle.dumps({"type": "game_start"})
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
                    should_reset = len(self.clients) == 0
                self.last_seen.pop(pid, None)
                self.inputs.pop(pid, None)
                self.server_game.remove_player(pid)
                self.lobby_updates.put(("player_left", pid, ""))
                if should_reset:
                    self.server_game.reset_to_lobby()
                    self.next_id = 0
                    self.inputs.clear()
                    self.last_seen.clear()
                if should_broadcast:
                    self._broadcast_lobby()

            elif ptype == "select_skin":
                skin_id = packet.get("skin_id", 0)
                self.server_game.set_skin(pid, skin_id)
                self._broadcast_lobby()
                self.last_seen[pid] = time.time()

            elif ptype == "request_lobby":
                self._broadcast_lobby()
                self.last_seen[pid] = time.time()

            elif ptype == "ping":
                self.last_seen[pid] = time.time()

    # ── State relay ────────────────────────────────────────────

    def _send_server_state(self):
        state = self.server_game.get_state()
        if not state:
            return
        data = pickle.dumps(state)
        with self.clients_lock:
            for c_addr, _, _ in self.clients:
                try:
                    self.udp_socket.sendto(data, c_addr)
                except OSError:
                    pass

    def _broadcast_lobby(self):
        players = self.get_lobby_players()
        packet = {"type": "lobby_info", "players": players}
        data = pickle.dumps(packet)
        with self.clients_lock:
            for c_addr, _, _ in self.clients:
                try:
                    self.udp_socket.sendto(data, c_addr)
                except OSError:
                    pass

    def set_host_name(self, name):
        self.host_name = name

    def _cleanup_stale(self):
        now = time.time()
        stale = []
        should_reset = False
        with self.clients_lock:
            for addr, pid, name in self.clients:
                last = self.last_seen.get(pid, now)
                if now - last > 10:
                    stale.append((addr, pid, name))
            for _, pid, name in stale:
                self.clients = [(a, p, n) for a, p, n in self.clients if p != pid]
                self.last_seen.pop(pid, None)
                self.inputs.pop(pid, None)
                self.server_game.remove_player(pid)
                self.lobby_updates.put(("player_left", pid, name))
            should_reset = len(self.clients) == 0 and stale
        if should_reset:
            self.server_game.reset_to_lobby()
            self.next_id = 0
            self.inputs.clear()
            self.last_seen.clear()
        if stale:
            self._broadcast_lobby()

    def get_lobby_players(self):
        result = []
        with self.clients_lock:
            for _, pid, name in self.clients:
                skin_id = self.server_game.players.get(pid, {}).get("skin_id", 0)
                result.append({"name": name, "pid": pid, "skin_id": skin_id})
        return result

    def stop(self):
        self.running = False
        try:
            self.udp_socket.close()
            self.tcp_server.close()
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

    def connect(self, host, port, name, skin_id=0):
        self.skin_id = skin_id
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))
            packet = {"type": "connect", "name": name, "skin_id": skin_id}
            data = pickle.dumps(packet)
            sock.sendall(struct.pack('!I', len(data)) + data)
            size_data = self._recv_all(sock, 4)
            if size_data:
                size = struct.unpack('!I', size_data)[0]
                if 0 < size < 8192:
                    resp_data = self._recv_all(sock, size)
                    if not resp_data:
                        sock.close()
                        return False
                    try:
                        resp = pickle.loads(resp_data)
                    except Exception:
                        sock.close()
                        return False
                    if resp.get("type") == "accept":
                        self.player_id = resp["player_id"]
                        self.server_addr = (host, port)
                        self.connected = True
                        sock.close()
                        from ..assets.skin_manager import SkinManager
                        SkinManager.set_server_addr(self.server_addr)
                        manifest = resp.get("skin_manifest", [])
                        SkinManager.set_manifest(manifest)
                        SkinManager.download_all_skins()
                        reg = {"type": "register", "player_id": self.player_id}
                        self.udp_socket.sendto(pickle.dumps(reg), self.server_addr)
                        self._save_config(name, host, port, skin_id)
                        return True
            sock.close()
        except (socket.timeout, ConnectionRefusedError, OSError):
            pass
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

    @staticmethod
    def _recv_all(sock, n):
        data = b''
        while len(data) < n:
            try:
                chunk = sock.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                return None
        return data

    def send_input(self, input_data):
        if not self.server_addr:
            return
        packet = {"type": "pos_update", "data": input_data, "player_id": self.player_id}
        try:
            self.udp_socket.sendto(pickle.dumps(packet), self.server_addr)
        except OSError:
            pass

    def send(self, packet):
        if not self.server_addr:
            return
        packet["player_id"] = self.player_id
        try:
            self.udp_socket.sendto(pickle.dumps(packet), self.server_addr)
        except OSError:
            pass

    def try_recv(self):
        """Receive any UDP packet. Returns parsed dict or None."""
        try:
            data, addr = self.udp_socket.recvfrom(65536)
            return pickle.loads(data)
        except BlockingIOError:
            return None
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
        MAX_SIZE = 1024 * 1024
        if len(raw) > MAX_SIZE:
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
            if len(raw) > 5 * 1024 * 1024:
                return (False, "Bestand te groot (max 5MB)")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect((host, port))
            req = {"type": "skin_upload", "name": name, "uploader": uploader, "data": raw}
            data = pickle.dumps(req)
            sock.sendall(struct.pack('!I', len(data)) + data)
            size_data = self._recv_all(sock, 4)
            if not size_data:
                sock.close()
                return (False, "Geen response van server")
            size = struct.unpack('!I', size_data)[0]
            if not (0 < size < 8192):
                sock.close()
                return (False, "Ongeldige response")
            resp_data = self._recv_all(sock, size)
            sock.close()
            if not resp_data:
                return (False, "Lege response")
            resp = pickle.loads(resp_data)
            if resp.get("type") == "skin_upload_ack":
                if resp.get("success"):
                    sid = resp.get("skin_id", -1)
                    return (True, f"Skin #{sid} geupload!", sid)
                else:
                    return (False, resp.get("error", "Upload mislukt"))
            return (False, "Ongeldige response type")
        except (socket.timeout, ConnectionRefusedError, OSError, pickle.UnpicklingError) as e:
            return (False, f"Netwerkfout: {str(e)[:50]}")

    def disconnect(self):
        self.connected = False
        self.server_addr = None
        try:
            self.udp_socket.close()
        except OSError:
            pass
