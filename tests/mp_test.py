"""
tests/mp_test.py - Multiplayer-integratietests (headless, geen pytest nodig)

Twee soorten tests:

  1. "pure"  - draait ServerGame direct, zonder netwerk. Snel en uitputtend:
               bv. elke mogelijke speler die de lift kan triggeren.
  2. "net"   - start een echte ServerIO op 127.0.0.1 met nep-clients die zich
               gedragen als de echte client (game.py): elke tick een pos_update
               met elevator_waiting, en die vlag weer terug syncen uit de
               server-state.

De lifttests bestaan omdat de lift af hing van de volgorde waarin de server de
spelers verwerkte: alleen de laatste speler kon elevator_waiting op True zetten
(1 op de N kans dat het werkte).

Gebruik:
    py -3.10 tests/mp_test.py               # alles
    py -3.10 tests/mp_test.py elevator     # alleen tests met 'elevator' erbij
    py -3.10 tests/mp_test.py -v           # naam + resultaat per test
"""

import os
import sys
import time
import socket
import random
import struct
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
os.environ.setdefault("GUNK_HEADLESS", "1")
sys.path.insert(0, ROOT)

import pygame  # noqa: E402
import numpy  # noqa: E402  (komt met pygame mee, gebruikt om ruis te maken)

from src.network.protocol import encode_packet, decode_packet  # noqa: E402
from src.network.server_game import ServerGame                # noqa: E402
from src.network.network import NetworkClient                  # noqa: E402
from src.core.config import (MAX_PLAYERS, ELEVATOR_WAIT_DIST,   # noqa: E402
                             ELEVATOR_WAIT_FRAMES, ELEVATOR_STUCK_FRAMES)
from math import hypot  # noqa: E402

TEMP_DIR = tempfile.gettempdir()

# Een echte client én een echte server schrijven naar bestanden van de speler:
# mp_config.json (laatste IP/poort) en server_skins/ (manifest + afbeeldingen).
# Tests die die klasse gebruiken zetten alles terug, anders staat er na het
# testen een skin van "tester" in je skinlijst.
MP_CONFIG_PATH = os.path.join(ROOT, "mp_config.json")
SKIN_DIR = os.path.join(ROOT, "server_skins")
MANIFEST_PATH = os.path.join(SKIN_DIR, "manifest.json")


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _write(path, data):
    if data is None:
        try:
            os.unlink(path)
        except OSError:
            pass
    else:
        with open(path, "wb") as f:
            f.write(data)


class keep_player_files:
    """Context manager die mp_config.json en server_skins/ terugzet."""

    def __enter__(self):
        self._config = _read(MP_CONFIG_PATH)
        self._manifest = _read(MANIFEST_PATH)
        self._skins = None
        if os.path.isdir(SKIN_DIR):
            self._skins = set(os.listdir(SKIN_DIR))
        return self

    def __exit__(self, *exc):
        _write(MP_CONFIG_PATH, self._config)
        _write(MANIFEST_PATH, self._manifest)
        if self._skins is not None:
            for name in set(os.listdir(SKIN_DIR)) - self._skins:
                try:
                    os.unlink(os.path.join(SKIN_DIR, name))
                except OSError:
                    pass

# Afstanden in pixels tov. de exit. ON_TILE = op de uitgangstegel,
# NEAR = binnen ELEVATOR_WAIT_DIST (mag mee de lift in), FAR = te ver weg.
ON_TILE = 0
NEAR = ELEVATOR_WAIT_DIST - 50
FAR = 900


# ── mini-testrunner ────────────────────────────────────────────

TESTS = []
VERBOSE = "-v" in sys.argv


def test(fn):
    TESTS.append(fn)
    return fn


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── helpers voor de "pure" lift-tests ───────────────────────────

def make_lift_game(n_players):
    """Een ServerGame met n spelers, level 0 geladen, zonder enemies."""
    sg = ServerGame()
    for pid in range(n_players):
        sg.register_player(pid, f"P{pid}", 0)
    sg.init_world()
    sg.enemies = []  # de liftlogica hangt niet van de enemy-AI af
    return sg


def drive_lift(sg, n_players, waiting, offsets, ticks, seqs=None):
    """Stuurt elke tick van elke speler een pos_update.

    De volgorde waarin de spelers verwerkt worden wisselt per tick, want die
    volgorde was precies de oorzaak van de lift-bug: self.inputs is een dict
    in aankomstvolgorde en de laatste speler overschreef de vlag van de rest.

    seqs moet je doorgeven als je meerdere levels achter elkaar speelt: de server
    weigert invoer met een seq die niet hoger is dan de vorige.
    """
    if seqs is None:
        seqs = {}
    ex = sg.exit_pos
    for t in range(ticks):
        pids = list(range(n_players))
        if t % 4 < 2:
            pids.reverse()
        for pid in pids:
            seqs[pid] = seqs.get(pid, 0) + 1
            dx, dy = offsets[pid]
            sg.process_input(pid, {
                "seq": seqs[pid],
                "pos": (ex.x + dx, ex.y + dy),
                "state": "game",
                "elevator_waiting": waiting[pid],
            })
        sg.tick()
    return seqs


# ── nep-client ─────────────────────────────────────────────────

class MiniClient:
    """Doet wat NetworkClient.connect + game.py._send_client_state doen."""

    def __init__(self, idx, port, host="127.0.0.1"):
        self.idx = idx
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        self.sock.setblocking(False)
        self.pid = -1
        self.token = f"mp_test_{idx}_{time.time()}"
        self.elevator_waiting = False
        self.seq = 0
        self.last_state = None
        self.seen = []  # alle packet-types die deze client ontving
        self.udp_sizes = []  # ruwe bytegroottes van de ontvangen datagrams

    def record_sizes(self):
        """Meet de werkelijk over de lijn gaande framgroottes."""
        from src.network.network import STATE_CHUNK_SIZE
        from src.network.protocol import ID_TO_PACKET_TYPE
        while True:
            try:
                data, _ = self.sock.recvfrom(65536)
            except (BlockingIOError, socket.timeout, OSError):
                break
            self.udp_sizes.append(len(data))
            self.seen.append(ID_TO_PACKET_TYPE.get(data[0], "unknown"))
            if len(data) > STATE_CHUNK_SIZE:
                raise AssertionError(
                    f"server stuurde een datagram van {len(data)} bytes, "
                    f"groter dan de chunkgrootte {STATE_CHUNK_SIZE}")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def send(self, packet):
        packet["player_id"] = self.pid
        try:
            self.sock.sendto(encode_packet(packet), self.addr)
        except OSError:
            pass

    def drain(self):
        """Lees alles dat klaarstaat; het laatste state-packet wint."""
        out = []
        while True:
            try:
                data, _ = self.sock.recvfrom(65536)
            except (BlockingIOError, socket.timeout, OSError):
                break
            pkt = decode_packet(data)
            if pkt:
                out.append(pkt)
                self.seen.append(pkt.get("type"))
                if pkt.get("type") == "state":
                    self.last_state = pkt
                    self.elevator_waiting = pkt.get("elevator_waiting", self.elevator_waiting)
        return out

    def wait_for(self, ptype, timeout=1.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for p in self.drain():
                if p.get("type") == ptype:
                    return p
            time.sleep(0.01)
        return None

    def handshake(self, timeout=2.0):
        """connect -> accept -> register, zoals NetworkClient.connect."""
        self.send({"type": "connect", "name": f"T{self.idx}",
                   "skin_id": 0, "token": self.token})
        deadline = time.time() + timeout
        while time.time() < deadline:
            for p in self.drain():
                if p.get("type") == "accept":
                    self.pid = p["player_id"]
                    self.send({"type": "register", "token": self.token})
                    return True
            time.sleep(0.01)
        return False

    def tick(self, pos, waiting=None):
        self.seq += 1
        if waiting is not None:
            self.elevator_waiting = waiting
        self.send({"type": "pos_update", "data": {
            "seq": self.seq,
            "pos": pos,
            "state": "game",
            "elevator_waiting": self.elevator_waiting,
        }})

    def death(self):
        self.seq += 1
        self.send({"type": "pos_update", "data": {
            "seq": self.seq, "pos": (0, 0), "state": "dead",
        }})


class LocalServer:
    def __init__(self, max_players=MAX_PLAYERS):
        self.port = free_port()
        self.max_players = max_players
        self.srv = None

    def __enter__(self):
        from src.network.network import ServerIO
        self.srv = ServerIO(self.port, max_players=self.max_players)
        self.srv.start()
        time.sleep(0.2)
        return self.srv

    def __exit__(self, *exc):
        if self.srv:
            self.srv.stop()
            self.srv = None
        time.sleep(0.1)


def join(srv, n):
    """n clients verbinden en registreren."""
    clients = [MiniClient(i, srv.port) for i in range(n)]
    for c in clients:
        check(c.handshake(), f"client {c.idx} kon niet registreren")
    return clients


def ready_all(srv, clients, timeout=12.0):
    """Alle clients ready -> wacht tot de countdown de wereld gestart heeft."""
    for c in clients:
        c.send({"type": "ready"})
    deadline = time.time() + 3.0
    while time.time() < deadline and srv.countdown <= 0:
        time.sleep(0.02)
    check(srv.countdown > 0, "countdown startte niet terwijl iedereen ready was")
    deadline = time.time() + timeout
    while time.time() < deadline and not srv.server_game.initialized:
        time.sleep(0.05)
    check(srv.server_game.initialized, "countdown liep af maar de wereld startte niet")
    return srv.server_game


# ── pure lift-tests ────────────────────────────────────────────

@test
def elevator_elke_speler_kunt_de_lift_triggeren():
    """Zodra 1 van de N spelers op de exit-tile staat moet de lift starten.

    Voor de fix werkte dit alleen als die speler als laatste werd verwerkt.
    """
    ticks = ELEVATOR_WAIT_FRAMES + 260
    for n in (2, 4, 6):
        for trigger in range(n):
            sg = make_lift_game(n)
            offsets = [(NEAR, 0)] * n
            waiting = [False] * n
            offsets[trigger] = (ON_TILE, 0)
            waiting[trigger] = True
            drive_lift(sg, n, waiting, offsets, ticks)
            check(sg.level >= 1,
                  f"{n} spelers, speler {trigger} op de tile: level bleef {sg.level} "
                  f"(elevator_waiting={sg.elevator_waiting})")


@test
def elevator_alle_spelers_op_de_tile():
    sg = make_lift_game(6)
    drive_lift(sg, 6, [True] * 6, [(ON_TILE, 0)] * 6, ELEVATOR_WAIT_FRAMES + 260)
    check(sg.level >= 1, f"level bleef {sg.level}")


@test
def elevator_gaat_niet_van_zichzelf():
    """Zonder iemand op de tile mag de lift niet starten."""
    sg = make_lift_game(4)
    drive_lift(sg, 4, [False] * 4, [(NEAR, 0)] * 4, 400)
    check(sg.elevator_waiting is False, "elevator_waiting ging vanzelf aan")
    check(sg.level == 0, f"level liep zonder trigger op naar {sg.level}")


@test
def elevator_veiligheidsnet_bij_afwezige_speler():
    """Een speler die ver weg blijft staan mag het level niet eeuwig blokkeren."""
    sg = make_lift_game(2)
    offsets = [(ON_TILE, 0), (FAR, 0)]
    waiting = [True, False]
    drive_lift(sg, 2, waiting, offsets, ELEVATOR_STUCK_FRAMES + 300)
    check(sg.level >= 1,
          f"level bleef {sg.level} terwijl 1 van 2 spelers {FAR}px weg stond")


@test
def elevator_rapporteeert_hoeveel_spelers_er_nog_moeten_komen():
    """De state moet zeggen wie er nog moet komen, anders weet niets waarom
    de lift stil staat."""
    sg = make_lift_game(4)
    ex = sg.exit_pos
    offsets = [(ON_TILE, 0), (NEAR, 0), (NEAR, 0), (FAR, 0)]
    waiting = [True, False, False, False]
    for _ in range(30):
        drive_lift(sg, 4, waiting, offsets, 1)
    state = sg.get_state()
    pending = state.get("elevator_pending")
    check(pending is not None, "elevator_pending ontbreekt in de state")
    check(list(pending) == [3, 4], f"verwachtte [3, 4] bij de lift, kreeg {list(pending)}")


@test
def elevator_overgang_kan_geen_softlock_maken():
    """Na een level-up moet de volgende level weer te triggeren zijn."""
    sg = make_lift_game(2)
    offsets = [(ON_TILE, 0), (NEAR, 0)]
    waiting = [True, False]
    ticks = ELEVATOR_WAIT_FRAMES + 260
    seqs = drive_lift(sg, 2, waiting, offsets, ticks)
    check(sg.level == 1, f"level 1 niet gehaald (staande op {sg.level})")
    sg.enemies = []  # level 2 laadt zijn eigen enemies er weer bij
    seqs = drive_lift(sg, 2, waiting, offsets, ticks, seqs)
    check(sg.level == 2, f"level 2 niet gehaald (staande op {sg.level})")
    sg.enemies = []
    drive_lift(sg, 2, waiting, offsets, ticks, seqs)
    check(sg.level == 3, f"level 3 niet gehaald (staande op {sg.level})")


# ── netwerk-tests ──────────────────────────────────────────────

@test
def lobby_zes_spelers_pas_en_nummer_zeven_krijgt_server_full():
    with LocalServer() as srv:
        clients = join(srv, MAX_PLAYERS)
        time.sleep(0.3)
        check(len(srv.clients) == MAX_PLAYERS,
              f"server registreerde {len(srv.clients)} i.p.v. {MAX_PLAYERS}")

        extra = MiniClient(999, srv.port)
        check(extra.handshake(), "extra client kreeg geen accept")
        pkt = extra.wait_for("server_full", timeout=3.0)
        check(pkt is not None, "speler 7 kreeg geen server_full en blijft hangen")
        check(pkt.get("max_players") == MAX_PLAYERS,
              f"server_full meldt max_players={pkt.get('max_players')}, "
              f"verwacht {MAX_PLAYERS}")
        time.sleep(0.3)
        check(len(srv.clients) == MAX_PLAYERS,
              f"server liet {len(srv.clients)} spelers toe")
        extra.close()
        for c in clients:
            c.close()


@test
def lobby_iedereen_ready_start_het_spel():
    with LocalServer() as srv:
        clients = join(srv, MAX_PLAYERS)
        sg = ready_all(srv, clients)
        check(len(sg.players) == MAX_PLAYERS,
              f"wereld kent {len(sg.players)} spelers i.p.v. {MAX_PLAYERS}")
        check(len(sg.enemies) > 0, "level 1 heeft geen enemies")
        for c in clients:
            c.close()


@test
def lobby_host_kunt_de_groep_starten_als_iemand_niet_ready_is():
    """Zonder force-start zit iedereen vast zodra één speler op READY UP
    blijft hangen."""
    with LocalServer() as srv:
        clients = join(srv, MAX_PLAYERS)
        ready_all(srv, clients)
        for c in clients:
            c.close()

    with LocalServer() as srv:
        clients = join(srv, MAX_PLAYERS)
        # Precies één speler (niet de host) houdt zich niet-ready.
        host_pid = srv.host_pid
        for c in clients:
            if c.pid != host_pid:
                c.send({"type": "ready"})
        time.sleep(0.5)
        check(srv.countdown == 0,
              f"countdown liep toch af met een niet-ready speler ({srv.countdown})")
        check(not srv.server_game.initialized, "spel startte toch zonder iedereen ready")

        # Een niet-host probeert te starten: mag niet lukken.
        not_host = next(c for c in clients if c.pid != host_pid)
        not_host.send({"type": "start_game"})
        time.sleep(0.5)
        check(not srv.server_game.initialized,
              "een niet-host kon het spel starten")

        host = next(c for c in clients if c.pid == host_pid)
        host.send({"type": "start_game"})
        deadline = time.time() + 3.0
        while time.time() < deadline and not srv.server_game.initialized:
            time.sleep(0.02)
        check(srv.server_game.initialized,
              "de host kon het spel niet starten terwijl er spelers niet-ready waren")
        # initialized staat al gezet vóórdat de game_start-pakketten de deur
        # uitgaan, dus even inkloppen voor je het controleert.
        deadline = time.time() + 3.0
        while time.time() < deadline and not any("game_start" in c.seen for c in clients):
            for c in clients:
                c.drain()
            time.sleep(0.02)
        check(all("game_start" in c.seen for c in clients),
              f"niet iedereen kreeg game_start: "
              f"{[sorted(set(c.seen)) for c in clients]}")
        for c in clients:
            c.close()


@test
def lobby_speler_kan_tijdens_het_spel_nog_injoinen():
    """Een speler die pas na de start joint moet gewoon meespelen."""
    with LocalServer() as srv:
        clients = join(srv, MAX_PLAYERS - 1)
        ready_all(srv, clients)
        late = MiniClient(500, srv.port)
        check(late.handshake(), "late speler kreeg geen accept")
        deadline = time.time() + 2.0
        while time.time() < deadline and "lobby_info" not in late.seen:
            late.drain()
            time.sleep(0.02)
        check("lobby_info" in late.seen,
              f"late speler kreeg geen lobby_info, wel: {sorted(set(late.seen))}")
        check("server_full" not in late.seen, "er was nog plek, maar server_full gestuurd")
        check(late.pid in srv.server_game.players,
              f"late speler {late.pid} staat niet in de wereld")
        check(late.pid in [p for _, p, _ in srv.clients],
              f"late speler {late.pid} staat niet tussen de clients")
        late.close()
        for c in clients:
            c.close()


@test
def dood_van_een_speler_maakt_hele_groep_dood():
    with LocalServer() as srv:
        clients = join(srv, MAX_PLAYERS)
        sg = ready_all(srv, clients)
        check(sg.global_health > 0, "groep start met 0 HP")
        clients[0].death()
        deadline = time.time() + 3.0
        while time.time() < deadline and sg.global_health != 0:
            time.sleep(0.02)
        check(sg.global_health == 0,
              f"na een dode speelde speler is global_health {sg.global_health} i.p.v. 0")
        for c in clients:
            c.close()


@test
def dood_zonder_gedeeld_leven_raakt_de_groep_niet():
    """Zonder gedeeld leven is één dode alleen voor die speler een ramp.

    De server zette de globale pool ook op nul, ook als de optie uit stond.
    Dat merkte niemand omdat elke client dan zijn eigen health leest, maar
    het is een landmine: zet je die voorwaarde ooit weg, dan is de hele
    groep door één sterfbericht dood. De test hiernaast bewaakt de andere
    kant, dus samen dekken ze beide richtingen af.
    """
    with LocalServer() as srv:
        srv.lobby_options["shared_health"] = False
        clients = join(srv, 2)
        # Alleen de host mag dit, en clients[0] is hier de host.
        clients[0].send({"type": "set_lobby_option",
                         "option_key": "shared_health", "option_value": False})
        sg = ready_all(srv, clients)
        sg.set_shared_options({"shared_health": False, "shared_ammo": True})
        check(sg.shared_health is False, "de optie shared_health bleef aan")
        check(sg.global_health > 0, "groep start met 0 HP")

        clients[0].death()
        deadline = time.time() + 3.0
        while time.time() < deadline and sg.players.get(
                clients[0].pid, {}).get("state") != "dead":
            time.sleep(0.02)
        check(sg.players[clients[0].pid]["state"] == "dead",
              "de dode speler staat niet als dood geregistreerd")

        time.sleep(0.3)
        check(sg.global_health > 0,
              f"de pool werd toch op nul gezet ({sg.global_health}) terwijl "
              f"het leven niet gedeeld is")
        check(sg.players[clients[1].pid]["health"] > 0,
              f"de levende teammate heeft {sg.players[clients[1].pid]['health']} HP")
        check(sg.players[clients[1].pid]["state"] != "dead",
              "de levende teammate is als dood geregistreerd")
        for c in clients:
            c.close()


@test
def dood_met_gedeeld_leven_maakt_het_wel_kapot():
    """Omgekeerd: met gedeeld leven blijft één dode de run beëindigen."""
    with LocalServer() as srv:
        clients = join(srv, 2)
        sg = ready_all(srv, clients)
        check(sg.shared_health is True, "shared_health staat niet aan")
        clients[0].death()
        deadline = time.time() + 3.0
        while time.time() < deadline and sg.global_health != 0:
            time.sleep(0.02)
        check(sg.global_health == 0,
              f"de pool bleef {sg.global_health} ondanks een dode speler")
        for c in clients:
            c.close()


@test
def dode_speler_struikt_zijn_ammo_voor_je_teammates():
    """Iets dat je achterlaat is de enige straf die een dode nog kan geven.

    Zonder gedeeld leven gaat de run door, dus de overdracht is zinvol.
    Met gedeeld leven stopt de hele run bij de eerste dode en zou een
    hoopje ammo neergezet worden dat niemand meer kan pakken.
    """
    with LocalServer() as srv:
        srv.lobby_options["shared_health"] = False
        srv.lobby_options["shared_ammo"] = False
        clients = join(srv, 2)
        clients[0].send({"type": "set_lobby_option",
                         "option_key": "shared_health", "option_value": False})
        clients[0].send({"type": "set_lobby_option",
                         "option_key": "shared_ammo", "option_value": False})
        sg = ready_all(srv, clients)
        sg.set_shared_options({"shared_health": False, "shared_ammo": False})
        check(sg.shared_ammo is False, "de optie shared_ammo bleef aan")

        # Naar een plek met geen pickups in de buurt, anders vullen we
        # een bestaand hoopje en tellen we het verkeerd. Via tick(), want
        # een handmatig packet met een eigen seq nummer zou de dooddaan
        # daarna als "verouderd" worden weggegooid.
        marker = (1, 2)
        clients[0].tick(marker, waiting=False)
        time.sleep(0.2)
        for obj in sg.objects.get("ammo", []):
            afstand = hypot(obj["pos"][0] - marker[0], obj["pos"][1] - marker[1])
            check(afstand >= 50,
                  f"de testplek ligt {afstand:.0f} van een bestaande ammo-pickup")

        basis = len(sg.objects["ammo"])
        dode = clients[0]
        # 100 ammo op start = 100 // 50 = 2 drops.
        sg.players[dode.pid]["ammo"] = 100
        dode.death()
        deadline = time.time() + 3.0
        while time.time() < deadline and len(sg.objects["ammo"]) == basis:
            time.sleep(0.02)

        check(len(sg.objects["ammo"]) == basis + 2,
              f"er verschenen {len(sg.objects['ammo']) - basis} drops, verwacht 2 "
              f"(100 ammo // 50)")
        nieuw = [o for o in sg.objects["ammo"] if o not in sg.objects["ammo"][:basis]]
        check(len(nieuw) == 2, f"kon de drops niet apart houden: {nieuw}")
        for drop in nieuw:
            afstand = hypot(drop["pos"][0] - marker[0], drop["pos"][1] - marker[1])
            check(afstand < 40,
                  f"een drop ligt {afstand:.0f} van de plek van de dode")
        check(sg.players[dode.pid]["ammo"] == 0,
              f"de dode heeft nog {sg.players[dode.pid]['ammo']} ammo")
        for c in clients:
            c.close()


@test
def lege_handen_dropt_geen_ammo():
    """Minder dan één oppakking waard is niets waard: dan komt er niks."""
    with LocalServer() as srv:
        srv.lobby_options["shared_health"] = False
        clients = join(srv, 2)
        clients[0].send({"type": "set_lobby_option",
                         "option_key": "shared_health", "option_value": False})
        sg = ready_all(srv, clients)
        sg.set_shared_options({"shared_health": False, "shared_ammo": True})
        basis = len(sg.objects["ammo"])
        dode = clients[0]
        sg.players[dode.pid]["ammo"] = 49
        dode.death()
        time.sleep(0.5)
        check(len(sg.objects["ammo"]) == basis,
              f"er kwamen {len(sg.objects['ammo']) - basis} drops uit 49 ammo")
        for c in clients:
            c.close()


@test
def gedeeld_leven_dropt_geen_ammo_op_je_sterfplek():
    """Eén dode stopt de hele run, dus een hoopje ammo is zinloos."""
    with LocalServer() as srv:
        clients = join(srv, 2)
        sg = ready_all(srv, clients)
        check(sg.shared_health is True, "shared_health staat niet aan")
        basis = len(sg.objects["ammo"])
        clients[0].death()
        time.sleep(0.5)
        check(len(sg.objects["ammo"]) == basis,
              f"er kwamen {len(sg.objects['ammo']) - basis} drops terwijl de "
              f"run toch al voorbij is")
        for c in clients:
            c.close()


@test
def teammate_pakt_de_achtergelaten_ammo_echt_op():
    """Het hele pad: dode laat het liggen, ander pakt het op, krijgt het terug.

    Zonder deze test zou er alleen bewezen zijn dat er iets op de kaart
    verschijnt. Dat een dode zijn ammo echt inlevert is het hele nut.
    """
    with LocalServer() as srv:
        srv.lobby_options["shared_health"] = False
        srv.lobby_options["shared_ammo"] = False
        dode, levend = join(srv, 2)
        for key, value in (("shared_health", False), ("shared_ammo", False)):
            dode.send({"type": "set_lobby_option",
                       "option_key": key, "option_value": value})
        sg = ready_all(srv, [dode, levend])
        sg.set_shared_options({"shared_health": False, "shared_ammo": False})

        dode.tick((1, 2), waiting=False)
        time.sleep(0.2)
        voor = len(sg.objects["ammo"])

        dode.death()
        deadline = time.time() + 3.0
        while time.time() < deadline and len(sg.objects["ammo"]) == voor:
            time.sleep(0.02)
        check(len(sg.objects["ammo"]) == voor + 2,
              f"er lagen {len(sg.objects['ammo']) - voor} drops, verwacht 2")

        # De overgebleven speler heeft zelf nog zijn startammo van 100.
        check(sg.players[levend.pid]["ammo"] == 100,
              f"de levende speler begon met {sg.players[levend.pid]['ammo']} ammo")

        # Alleen de 2 drops oppakken. Alles doorlopen zou ook de ammo van
        # het level meepakken, want de server matcht op positie.
        drops = sg.objects["ammo"][voor:]
        check(len(drops) == 2, f"er lagen {len(drops)} drops om op te pakken")
        for drop in drops:
            levend.seq += 1
            levend.send({"type": "pos_update", "data": {
                "seq": levend.seq, "pos": (1, 2), "state": "game",
                "remove_pickup": [{"type": "ammo", "pos": drop["pos"]}]}})
            time.sleep(0.15)

        check(len(sg.objects["ammo"]) == voor,
              f"er bleef {len(sg.objects['ammo']) - voor} ammo op de kaart liggen")
        check(sg.players[levend.pid]["ammo"] == 200,
              f"de levende speler eindigde met {sg.players[levend.pid]['ammo']} "
              f"ammo i.p.v. 100 + 2x50 = 200")
        dode.close()
        levend.close()


@test
def net_elevator_werkt_als_de_triggerende_speler_niet_de_laatste_is():
    """Eind-tot-eind over het netwerk, met de speler op de tile als EERSTE
    geregistreerde speler - dat was de volgorde die het zekerst vastliep."""
    with LocalServer() as srv:
        clients = join(srv, MAX_PLAYERS)
        sg = ready_all(srv, clients)
        ex = sg.exit_pos
        start_level = sg.level
        ticks = ELEVATOR_WAIT_FRAMES + 260
        deadline = time.time() + 12.0
        sent = 0
        while sent < ticks and sg.level == start_level:
            for i, c in enumerate(clients):
                c.drain()
                dx = ON_TILE if i == 0 else NEAR
                c.tick((ex.x + dx, ex.y), waiting=(i == 0))
            sg._post_transition_grace = 0
            time.sleep(1 / 60)
            sent += 1
        check(sg.level > start_level,
              f"lift liep vast: level bleef {sg.level}, elevator_waiting="
              f"{sg.elevator_waiting} na {sent} ticks")
        for c in clients:
            c.close()


@test
def net_state_pakket_blijft_onder_mtu():
    """Een state-pakket groter dan 1500 bytes fragmenteert over het internet,
    en één verloren fragment betekent een weggevallen frame."""
    from src.network.network import STATE_CHUNK_SIZE
    with LocalServer() as srv:
        clients = join(srv, MAX_PLAYERS)
        sg = ready_all(srv, clients)
        worst = 0
        for level in range(5):
            if level:
                sg.level = level
                sg._setup_level()
            size = len(encode_packet(sg.get_state()))
            worst = max(worst, size)
            if VERBOSE:
                print(f"      level {level}: {size} bytes")
        check(worst > STATE_CHUNK_SIZE,
              f"de test vindt geen enkel groot pakket ({worst} bytes) en bewijst niets")

        # Echte server + echte client: meet wat er werkelijk over de lijn gaat.
        deadline = time.time() + 4.0
        while time.time() < deadline:
            for level in range(5):
                sg.level = level
                sg._setup_level()
            time.sleep(0.3)
            for c in clients:
                c.record_sizes()
        biggest = max((max(c.udp_sizes) for c in clients if c.udp_sizes), default=0)
        check(biggest <= STATE_CHUNK_SIZE,
              f"grootste frame over de lijn is {biggest} bytes "
              f"(> {STATE_CHUNK_SIZE})")
        if VERBOSE:
            print(f"      grootste frame over de lijn: {biggest} bytes")
        for c in clients:
            c.close()


@test
def net_skin_upload_van_een_echte_png():
    """Een skin van een paar honderd kB past niet in één UDP-datagram, dus de
    upload moet in stukken kunnen."""
    from src.network.network import STATE_CHUNK_SIZE
    with keep_player_files():
        with LocalServer() as srv:
            client = NetworkClient()
            try:
                check(client.connect("127.0.0.1", srv.port, "uploader"),
                      "connect lukte niet")
                path = os.path.join(TEMP_DIR, "gunk_test_skin.png")
                # Echt ruis: een gladde kleur geeft een piepklein PNG en dan
                # bewijst de test niets.
                rng = random.Random(20260929)
                noise = bytes(rng.randrange(256)
                              for _ in range(512 * 512 * 3))
                surface = pygame.Surface((512, 512))
                pygame.surfarray.blit_array(
                    surface,
                    numpy.frombuffer(noise, dtype=numpy.uint8).reshape(512, 512, 3))
                pygame.image.save(surface, path)
                size = os.path.getsize(path)
                check(size > STATE_CHUNK_SIZE,
                      f"de testskin is maar {size} bytes en bewijst niets")

                before = len(srv.skin_manifest)
                ok, msg, *rest = client.upload_skin("ruis", "tester", path)
                check(ok, f"upload van een {size}-bytes skin mislukte: {msg}")
                sid = rest[0] if rest else -1
                check(len(srv.skin_manifest) == before + 1,
                      f"manifest groeide niet: {len(srv.skin_manifest)} vs {before}")
                entry = next((s for s in srv.skin_manifest
                              if s.get("id") == sid), None)
                check(entry is not None,
                      f"skin {sid} staat niet in de manifest "
                      f"({[s.get('id') for s in srv.skin_manifest]})")
                # Het opgeslagen bestand moet bytegelijk zijn aan wat we stuurden.
                stored = os.path.join(ROOT, "server_skins", f"skin_{sid}.png")
                with open(path, "rb") as f:
                    original = f.read()
                with open(stored, "rb") as f:
                    got = f.read()
                check(got == original,
                      f"opgeslagen skin is {len(got)} bytes, origineel {len(original)}")
                os.unlink(stored)
            finally:
                try:
                    client.disconnect()
                except Exception:
                    pass


# ── adres/autopoort-mapping ────────────────────────────────────

def _natpmp_packet(opcode, result, body=b"", version=0):
    # Bit 7 markeert het als antwoord; bits 0-6 zijn de opcode. De lengte van
    # het antwoord volgt uit de opcode, zit niet in de byte verwerkt.
    return (struct.pack("!BBB", version, 0x80 | opcode, result)
            + struct.pack("!I", 0) + body)


@test
def adres_natpmp_antwoord_wordt_gelezen():
    from src.network.port_map import parse_natpmp_response
    body = socket.inet_aton("192.168.1.42") + socket.inet_aton("82.196.7.3")
    parsed = parse_natpmp_response(_natpmp_packet(0, 0, body))
    check(parsed["result"] == 0, f"result {parsed['result']} != 0")
    check(parsed["external_ip"] == "82.196.7.3", parsed["external_ip"])
    check(parsed["internal_ip"] == "192.168.1.42", parsed["internal_ip"])

    body = struct.pack("!HHI", 5555, 5555, 3600)
    parsed = parse_natpmp_response(_natpmp_packet(1, 0, body))
    check(parsed["external_port"] == 5555, parsed["external_port"])
    check(parsed["lifetime"] == 3600, parsed["lifetime"])

    check(parse_natpmp_response(b"\x00") is None, "kort antwoord werd geaccepteerd")
    check(parse_natpmp_response(_natpmp_packet(0, 2, body))["result"] == 2,
          "foutcode 2 niet doorggegeven")


@test
def adres_stun_antwoord_wordt_ontward():
    from src.network.port_map import parse_stun_response, MAGIC_COOKIE
    txn = bytes(range(12))
    xor_addr = bytes(b ^ c for b, c in
                     zip(socket.inet_aton("82.196.7.3"),
                         struct.pack("!I", MAGIC_COOKIE)))
    # XOR-MAPPED-ADDRESS: reserved(1) + family(1) + x-port(2) + x-addr(4)
    value = (b"\x00\x01" + struct.pack("!H", 5555 ^ 0x2112) + xor_addr)
    attr = struct.pack("!HH", 0x0020, len(value)) + value
    resp = struct.pack("!HHI", 0x0101, len(attr), MAGIC_COOKIE) + txn + attr
    parsed = parse_stun_response(resp, txn)
    check(parsed is not None, "geldig STUN-antwoord werd genegeerd")
    check(parsed["ip"] == "82.196.7.3", parsed["ip"])
    check(parsed["port"] == 5555, parsed["port"])

    # Verkeerd transactie-id: een antwoord op iemand anders' vraag.
    check(parse_stun_response(resp, bytes(12)) is None,
          "een vreemd transactie-id werd geaccepteerd")
    # Error response (geen Binding Success).
    check(parse_stun_response(struct.pack("!HHI", 0x0111, 0, MAGIC_COOKIE) + txn,
                              txn) is None,
          "een error response werd als succes gelezen")


@test
def adres_bannerscherm_tonen_lan_en_internet():
    from src.network.port_map import format_banner
    lines = format_banner(5555, {
        "lan_ip": "192.168.1.42", "public_ip": "82.196.7.3",
        "mapped": True, "external_port": 5555, "method": "NAT-PMP",
        "notes": ["poort opengezet"],
    })
    text = "\n".join(lines)
    check("192.168.1.42:5555" in text, "LAN-adres ontbreekt in de banner")
    check("82.196.7.3" in text, "internet-adres ontbreekt in de banner")
    check("NAT-PMP" in text, "de herkomst van het adres staat er niet bij")

    # Zonder mapping moet de banner duidelijk zeggen dat de poort nog dicht zit.
    text = "\n".join(format_banner(5555, {
        "lan_ip": "192.168.1.42", "public_ip": "82.196.7.3", "mapped": False,
        "external_port": 5555, "notes": [],
    }))
    check("NIET" in text, "banner waarschuwt niet voor een dichte poort:\n" + text)

    # Zonder enig adres mag het geen crash geven.
    text = "\n".join(format_banner(5555, {"lan_ip": None, "notes": []}))
    check("onbekend" in text, "ontbrekend adres wordt niet gemeld:\n" + text)


@test
def adres_stun_vindt_echt_onze_publieke_ip():
    """Echte STUN-vraag. Slaat de test over als er geen internet is."""
    from src.network.port_map import stun_external_address
    found = stun_external_address(tries=1, timeout=2.0)
    if not found:
        print("      (geen STUN bereikbaar, overslaan)")
        return
    check(found["ip"].count(".") == 3, f"ongeldig IP uit STUN: {found['ip']}")
    check(not found["ip"].startswith("127."), f"STUN gaf een loopback-IP terug")


# ── LAN-ontdekking ─────────────────────────────────────────────

@test
def lan_aankondiging_overleeft_de_ronde():
    from src.network.discovery import (encode_announcement,
                                      decode_announcement, MAGIC)
    data = encode_announcement(5555, players=2, max_players=6, motd="Huis")
    check(len(data) <= 75, f"de aankondiging is {len(data)} bytes, te groot voor comfort")
    parsed = decode_announcement(data)
    check(parsed["port"] == 5555, parsed["port"])
    check(parsed["players"] == 2, parsed["players"])
    check(parsed["max_players"] == 6, parsed["max_players"])
    check(parsed["motd"] == "Huis", parsed["motd"])

    # Iets anders op poort 4445 moet genegeerd worden, niet gecrasht.
    check(decode_announcement(b"") is None, "lege packet werd geaccepteerd")
    check(decode_announcement(b"MIJN" + data[4:]) is None,
          "vreemd magisch getal werd geaccepteerd")
    check(decode_announcement(data[:6]) is None, "afgekapt packet werd geaccepteerd")
    check(decode_announcement(b"\x00" * 40) is None, "onzin werd geaccepteerd")


@test
def lan_broadcast_adressen_cloppen():
    from src.network.discovery import broadcast_targets
    check("255.255.255.255" in broadcast_targets("192.168.1.42"),
          "de beperkte broadcast ontbreekt: die werkt op elk netwerk")
    # /24 van 192.168.1.42 is 192.168.1.255
    check("192.168.1.255" in broadcast_targets("192.168.1.42"),
          broadcast_targets("192.168.1.42"))
    # En op een /18, zoals dit campusnetwerk.
    check("10.240.63.255" in broadcast_targets("10.240.2.75", prefix=18),
          broadcast_targets("10.240.2.75", prefix=18))
    # Bepaalt een IP dat geen vier delen heeft, dan blijft de beperkte
    # broadcast over; de code mag daar niet op klappen.
    check(broadcast_targets("geen-ip") == ["255.255.255.255"],
          broadcast_targets("geen-ip"))


@test
def lan_ontdekking_vindt_een_lopende_server():
    """De luisteraar moet aankondigingen in een bruikbare lijst zetten.

    Bewust zonder socket: het ontvangen staat in _on_packet, en dat is
    precies het stuk dat kapot kan. Een test die een echte poort opent
    zou alleen de topologie van deze machine meten.
    """
    from src.network.discovery import DiscoveryListener, encode_announcement

    listener = DiscoveryListener(timeout=3.0)
    listener._on_packet(encode_announcement(5555, players=3, max_players=6),
                        ("192.168.1.42", 4445))
    listener._on_packet(encode_announcement(5556, players=1, max_players=6),
                        ("192.168.1.77", 4445))
    # Onszelf en rommel horen eruit, anders zou de speler zichzelf zien.
    listener._on_packet(encode_announcement(5555), ("127.0.0.1", 4445))
    listener._on_packet(b"MIJN\x01\x15\xb3niet voor ons", ("192.168.1.9", 4445))

    servers = listener.list_servers()
    check(len(servers) == 2,
          f"verwachtte 2 servers na het filteren, kreeg {len(servers)}: {servers}")
    gevonden = {s["port"]: s for s in servers}
    check(5555 in gevonden, f"poort 5555 ontbreekt: {sorted(gevonden)}")
    check(5556 in gevonden, f"poort 5556 ontbreekt: {sorted(gevonden)}")
    check(gevonden[5555]["ip"] == "192.168.1.42", gevonden[5555]["ip"])
    check(gevonden[5555]["players"] == 3, gevonden[5555]["players"])
    check(gevonden[5555]["max_players"] == 6, gevonden[5555]["max_players"])

    # Dezelfde server die zich opnieuw meldt moet niet verdubbeld worden.
    listener._on_packet(encode_announcement(5555, players=5, max_players=6),
                        ("192.168.1.42", 4445))
    check(len(listener.list_servers()) == 2,
          f"een tweede melding verdubbelde de lijst: {listener.list_servers()}")
    check(listener.list_servers()[0]["players"] == 5,
          "de nieuwste spelersaantallen tellen niet mee")

    # Een server die stil valt moet vanzelf uit de lijst verdwijnen, anders
    # zie je dode servers staan tot je het spel sluit. De klok terugzetten
    # werkt betrouwbaarder dan wachten: monotonic() is te grof om op te
    # rekenen binnen dezelfde aanroep.
    oud = time.monotonic() - 60
    for server in listener.servers.values():
        server["seen"] = oud
    check(listener.list_servers() == [],
          f"een stilgevallen server bleef staan: {listener.list_servers()}")


@test
def lan_horende_speler_blijft_zichzelf_buiten_de_lijst():
    """Een server die zichzelf hoort moet zichzelf niet aanbieden."""
    from src.network.discovery import is_own_address
    for ip in ("127.0.0.1", "0.0.0.0", "geen-adres", ""):
        check(is_own_address(ip), f"{ip!r} zou als eigen adres moeten tellen")
    check(not is_own_address("192.168.1.42"), "een LAN-adres is geen eigen adres")


@test
def lan_ontdekking_start_en_stopt_wel():
    """De draadjes moeten echt opstarten en weer netjes stoppen."""
    from src.network.discovery import (DiscoveryListener, DiscoveryResponder,
                                      DISCOVERY_PORT, encode_announcement)

    listener = DiscoveryListener()
    listener.start()
    listener.stop()
    listener.join(timeout=3)
    check(not listener.is_alive(), "de luisteraar bleef hangen na stop()")

    # De zender hoeft geen verbinding te maken om te mogen bestaan: hij
    # verstuurt alleen bcast-datagrammen. Als broadcast op dit netwerk
    # verboden is, mag dat stilletjes falen, maar niet klappen.
    responder = DiscoveryResponder(5555, get_info=lambda: {"players": 1})
    responder.start()
    responder.stop()
    responder.join(timeout=3)
    check(not responder.is_alive(), "de zender bleef hangen na stop()")


# ── gateway zoeken ─────────────────────────────────────────────

@test
def adres_gateway_komt_uit_de_routetabel():
    """De campusgateway staat niet op x.x.x.1, dus we lezen de routetabel."""
    from src.network.port_map import _pick_gateway, _looks_like_gateway
    routes = [
        {"NextHop": "100.101.102.103", "RouteMetric": "0"},    # Tailscale
        {"NextHop": "0.0.0.0", "RouteMetric": "0"},             # onbekend
        {"NextHop": "169.254.83.107", "RouteMetric": "0"},       # Tailscale
        {"NextHop": "10.240.63.254", "RouteMetric": "25"},       # echt
    ]
    check(_pick_gateway(routes) == "10.240.63.254",
          f"gateway verkeerd gekozen: {_pick_gateway(routes)}")
    check(_pick_gateway([]) is None, "een lege tabel gaf een gateway")
    check(_pick_gateway([{"NextHop": "169.254.1.1", "RouteMetric": "1"}]) is None,
          "een link-local adres werd als gateway geaccepteerd")
    check(_looks_like_gateway("192.168.1.1"), "een normale router werd geweigerd")
    check(not _looks_like_gateway("999.1.1.1"), "ongeldig IP werd geaccepteerd")


@test
def adres_prefixlengte_komt_uit_de_adaptertabel():
    """De prefixlengte moet echt worden opgevraagd, niet op /24 geschat.

    Dit was een echte bug: de aankondiging ging naar 10.240.2.255 terwijl
    het campusnetwerk op een /18 zit en het juiste adres 10.240.63.255 is.
    """
    from src.network import port_map as PM
    from src.network.port_map import _parse_ip_prefix_table, _parse_ip_addr_output

    # Windows-uitvoer van Get-NetIPAddress.
    windows_csv = ('"IPAddress","PrefixLength"\r\n'
                   '"10.240.2.75","18"\r\n'
                   '"100.115.3.78","32"\r\n'
                   '"127.0.0.1","8"\r\n')
    table = _parse_ip_prefix_table(windows_csv)
    check(table.get("10.240.2.75") == 18, f"prefix verkeerd gelezen: {table}")
    check(table.get("100.115.3.78") == 32, f"/32 verkeerd gelezen: {table}")

    # Linux-uitvoer van `ip -o -4 addr show`. Met de -o staat er een
    # regelnummer voor, dus 'inet' staat niet op een vaste kolom.
    linux_out = ("3: eth0    inet 10.240.2.75/18 brd 10.240.63.255 scope global\n"
                 "5: lo      inet 127.0.0.1/8 scope host\n"
                 "6: eth0    inet6 fe80::1/64 scope link\n"
                 "7: tun0    inet 100.115.3.78 netmask 0xffffffff\n")
    table = _parse_ip_addr_output(linux_out)
    check(table.get("10.240.2.75") == 18, f"prefix verkeerd gelezen: {table}")
    check(table.get("127.0.0.1") == 8, f"loopback verkeerd gelezen: {table}")
    check("100.115.3.78" not in table, "het Tailscale-adres zonder / werd meegenomen")
    check(not any(":" in ip for ip in table),
          f"een IPv6-adres kwam in de tabel: {table}")

    # Zonder de -o staat 'inet' wel vooraan; dat moet ook lukken.
    check(_parse_ip_addr_output("    inet 192.168.1.42/24 brd 192.168.1.255\n")
          == {"192.168.1.42": 24},
          "de vorm zonder regelnummers werd niet gelezen")
    check(_parse_ip_addr_output("    inet 10.0.0.5\n") == {},
          "een adres zonder prefix werd meegenomen")

    # Lege of kapotte uitvoer mag niet klappen.
    check(_parse_ip_prefix_table("") == {}, "lege tabel gaf adressen terug")
    check(_parse_ip_prefix_table('"IPAddress","PrefixLength"\r\n"x","y"\r\n') == {},
          "onzin werd als prefix geaccepteerd")
    check(_parse_ip_addr_output("") == {}, "lege uitvoer gaf adressen terug")

    # Vinden we het adres niet, dan blijft het bij de /24-gok.
    original = PM.prefix_length_table
    PM.prefix_length_table = lambda: {"10.240.2.75": 18}
    try:
        check(PM.local_prefix_length("10.240.2.75") == 18,
              "een bekend adres werd niet gevonden")
        check(PM.local_prefix_length("10.9.9.9") == 24,
              "een onbekend adres viel niet terug op /24")
        # En daarom is de aankondiging op dit netwerk 10.240.63.255.
        from src.network.discovery import broadcast_targets
        check("10.240.63.255" in broadcast_targets("10.240.2.75",
                                                   PM.local_prefix_length("10.240.2.75")),
              broadcast_targets("10.240.2.75", 18))
    finally:
        PM.prefix_length_table = original


@test
def adres_mapping_kan_zichzelf_herhalen():
    """De mapping moet verlengd kunnen worden, anders valt hij na een uur weg."""
    from src.network import port_map as PM

    calls = []

    def fake_map(gateway, internal_port, lifetime=3600, tries=3, timeout=0.35):
        calls.append(lifetime)
        return {"external_port": internal_port, "lifetime": lifetime,
                "external_ip": None}

    original = PM.natpmp_map_udp
    PM.natpmp_map_udp = fake_map
    try:
        keeper = PM.PortMappingKeeper(("10.0.0.1", 5351), 5555, lifetime=7200)
        check(keeper.renew() == 5555, "het verlengen gaf geen poort terug")
        check(keeper.mapped, "de mapping meldt zich niet als geldig")
        check(calls == [7200], f"er werd een verkeerde levensduur gevraagd: {calls}")
        keeper.release()
        check(calls[-1] == 0,
              f"een lifetime van 0 moet de mapping intrekken, kreeg {calls[-1]}")
    finally:
        PM.natpmp_map_udp = original


# ── UI tekenen ─────────────────────────────────────────────────
#
# De rest van de suite draait met GUNK_HEADLESS=1, waardoor config.SCREEN
# leeg is en geen enkele tekenfunctie aan de beurt komt. Voor de schermen
# draaien we daarom een apart proces met SDL's dummy videodriver: daarmee
# bestaat er echt een Surface, zonder dat er een venster opent.

UI_DRIVER = r'''
import os, sys, traceback
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ.pop("GUNK_HEADLESS", None)
ROOT = sys.argv[1]
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.argv = ["game.py"]

import importlib.util
from src.ui.Menu import Menu_inst
from src.network.protocol import encode_packet, decode_packet


class FakeGame:
    state = "multiplayer_menu"
    player_id = 0
    skin_id = 100
    discovery_listener = None
    hosted_server = None
    hosted_address = None
    hosted_port = None

    def _do_connect(self, ip, port, name):
        raise AssertionError("niemand mag verbinden tijdens het tekenen")

    def _do_host(self, port, name):
        raise AssertionError("niemand mag hosten tijdens het tekenen")


class FakeListener:
    """Levert een vaste lijst servers, zodat we geen echt netwerk nodig hebben."""

    def __init__(self, servers):
        self._servers = servers

    def list_servers(self):
        return list(self._servers)


# "Ik host niet" en "ik host, maar we weten mijn adres nog niet" zijn twee
# verschillende dingen en moeten dus ook twee verschillende tekeningen zijn.
NOT_HOSTING = object()


def draw_lobby(menu, ready_list, player_id, skin_id=100, host_info=NOT_HOSTING):
    """Tekent de lobby met de opgegeven spelers, ready-vlaggen en kijker."""
    packet = decode_packet(encode_packet({
        "type": "lobby_info",
        "players": [{"pid": i, "name": "P%d" % i, "skin_id": skin_id,
                     "ready": r} for i, r in enumerate(ready_list)],
        "host_pid": 0}))
    menu.client_list = packet["players"]
    menu.host_pid = packet["host_pid"]
    g = FakeGame()
    g.state = "waiting_lobby"
    g.player_id = player_id
    if host_info is not NOT_HOSTING:
        g.hosted_server = object()
        g.hosted_port = 5555
        g.hosted_address = host_info
    menu.draw_waiting_lobby([], g)


try:
    menu = Menu_inst

    # Het multiplayer-menu met de HOST SERVER-knop, eerst zonder gevonden
    # servers en daarna met drie, want de rij kan het scherm opvullen.
    # De luisteraar is een stub, zodat de tekentest geen echte poort opent.
    empty = FakeGame()
    empty.discovery_listener = FakeListener([])
    menu.draw_multiplayer_menu([], empty)
    g = FakeGame()
    g.discovery_listener = FakeListener([
        {"ip": "192.168.1.42", "port": 5555, "players": 2, "max_players": 6,
         "is_host": True, "motd": ""},
        {"ip": "192.168.1.77", "port": 5556, "players": 5, "max_players": 6,
         "is_host": False, "motd": ""},
        # Een server zonder limiet: het tekenen mag niet op %d klappen.
        {"ip": "10.0.0.5", "port": 5555, "players": 0, "max_players": 0,
         "is_host": True, "motd": ""},
    ])
    menu.draw_multiplayer_menu([], g)

    # De host ziet zes spelers, waarvan een nog niet ready is: de START-knop
    # en de wachtmelding moeten daarbij tekenen.
    draw_lobby(menu, [False] * 6, player_id=0)
    draw_lobby(menu, [True] * 6, player_id=0)
    draw_lobby(menu, [False, True, True, True, True, True], player_id=3)
    draw_lobby(menu, [], player_id=0)

    # De drie stadia van het gasten-adres: nog zoeken, wel open, niet open.
    draw_lobby(menu, [True] * 3, player_id=0, host_info=None)
    draw_lobby(menu, [True] * 3, player_id=0, host_info={
        "lan_ip": "192.168.1.42", "public_ip": "82.196.7.3",
        "mapped": True, "external_port": 5555})
    draw_lobby(menu, [True] * 3, player_id=0, host_info={
        "lan_ip": "10.240.2.75", "public_ip": "82.196.7.3",
        "mapped": False, "external_port": 5555})

    # De hele game, inclusief het HUD met de liftwachtmelding.
    spec = importlib.util.spec_from_file_location("gunk_game", os.path.join(ROOT, "game.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    game = mod.Game()
    game.multiplayer = True
    game.network_client = None
    for pending in ([3, 6], [0, 0], [6, 6]):
        game.elevator_pending = pending
        game.render()

    # Game-overscherm zonder en met de MEEKIJKEN-knop, plus de HUD-banner
    # van het meekijken zelf.
    game.multiplayer = False
    game.state = "dead"
    menu.draw_dead_screen([], game)
    game.multiplayer = True
    game._spectate_info = {
        0: {"name": "ShelfHead", "state": "dead", "angle": 1.0},
        1: {"name": "Ruben", "state": "game", "angle": 2.0},
        2: {"name": "Andreas", "state": "game", "angle": 0.5},
    }
    menu.draw_dead_screen([], game)
    game.spectating = True
    game._spectate_name = "Ruben"
    game._spectate_pid = 1
    menu.draw_UI([])
    game.spectating = False
except Exception:
    traceback.print_exc()
    sys.exit(1)

print("UI OK")
'''


@test
def ui_lobby_joinscherm_en_hud_tekenen_zonder_fout():
    """Alle schermen die ik aanraakte moeten daadwerkelijk tekenen."""
    path = os.path.join(TEMP_DIR, "gunk_ui_driver.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(UI_DRIVER)
    try:
        proc = subprocess.run([sys.executable, path, ROOT],
                              capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        check(False, "het tekenen van de schermen liep vast (time-out)")
        return
    if proc.returncode != 0:
        tail = [ln for ln in proc.stderr.splitlines()
                if ln.strip() and "pygame community" not in ln
                and "Hello from" not in ln and "warnings.warn" not in ln
                and "UserWarning" not in ln and "Transparency" not in ln
                and "PIL" not in ln]
        check(False, "tekenen gaf een fout:\n" + "\n".join(tail[-25:]))
        return
    check("UI OK" in proc.stdout, f"geen 'UI OK' in de uitvoer:\n{proc.stdout[-500:]}")


# ── hosten: blijft je eigen server draaiende? ───────────────────
#
# _do_host draait de server in ditzelfde proces en verbindt er zelf mee.
# Om dat te kunnen beoordelen moet de returnwaarde van _do_connect kloppen:
# `if not self._do_connect(...)` is bij een functie zonder return altijd
# waar, en dan sloot de host zijn zojuist gestarte server weer af. Het
# gevolg was een lege lobby zonder host, dus zonder server settings.
#
# Vroeger stond _do_connect bovendien twee keer in game.py. Die dubbele
# definitie is weg, maar de test hieronder hoeft zich daar niet van af te
# laten hangen: hij kijkt naar het gedrag, niet naar de bron.

HOSTEN_DRIVER = r'''
import os, sys, time, socket
ROOT = sys.argv[1]
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("GUNK_HEADLESS", "1")

import game


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

fouten = []


def check(cond, msg):
    if not cond:
        fouten.append(msg)


class Harness:
    """Alleen het stuk van Game dat _do_host aanraakt.

    De echte Game heeft een scherm nodig, maar de hele lobby-logica niet.
    De methodes zijn wel de echte: _do_host van Game zelf, dus een fix die
    hier werkt werkt ook in het spel.
    """
    _do_host = game.Game._do_host
    _do_connect = game.Game._do_connect
    _stop_host = game.Game._stop_host
    _discovery_info = game.Game._discovery_info
    # Het adres opzoeken gaat het internet op en duurt seconden; dat is
    # voor deze test niet het punt waar we naar kijken.
    _discover_host_address = lambda self, port: None

    def __init__(self):
        self.network_client = None
        self.hosted_server = None
        self.discovery_responder = None
        self.mapping_keeper = None
        self.hosted_address = None
        self.hosted_port = None
        self.player_id = -1
        self.player_name = ""
        self.skin_id = 0
        self.multiplayer = False
        self.state = "multiplayer_menu"
        self.host_pid = -1
        self.is_host = False
        self._last_server_packet = 0

        class Menu:
            mp_skin_id = 106
            mp_status = ""
        self.Menu = Menu()


h = Harness()
port = free_port()

# 1. De returnwaarde is niet decoratief.
r = h._do_connect.__func__(h, "127.0.0.1", port, "NiemandLuistert")
check(r is False, f"verbinden met een dode poort gaf {r!r} in plaats van False")
h._stop_host()

# 2. Hosten: de server moet blijven draaien.
h2 = Harness()
h2._do_host(port, "HostSpeler")

check(h2.state == "waiting_lobby",
      f"state is {h2.state!r} i.p.v. 'waiting_lobby'")
check(h2.hosted_server is not None,
      "de server werd afgesloten direct na het verbinden")
check(h2.network_client is not None, "er is geen client verbonden")

if h2.hosted_server is None:
    fouten.append("geen server om te controleren")
else:
    srv = h2.hosted_server
    time.sleep(1.0)   # de server moet de 'register' nog verwerken
    spelers = srv.get_lobby_players()
    check(len(spelers) == 1,
          f"de lobby telt {len(spelers)} spelers i.p.v. 1 (de host zelf)")
    check(srv.host_pid == h2.player_id,
          f"host_pid is {srv.host_pid} maar jij bent {h2.player_id}")
    check(any(p["pid"] == h2.player_id and p["name"] == "HostSpeler"
              for p in spelers),
          f"jouw eigen naam staat niet in de lobby: {spelers}")

    # 3. En dat kom je ook via het protocol te weten, want daar tekent de
    #    lobby zich.
    lobby = None
    for p in h2.network_client.drain():
        if p.get("type") == "lobby_info":
            lobby = p
    check(lobby is not None, "geen lobby_info ontvangen")
    if lobby is not None:
        check(lobby.get("host_pid") == h2.player_id,
              f"lobby_info noemt host_pid {lobby.get('host_pid')}, "
              f"jij bent {h2.player_id}")
        check(len(lobby.get("players", [])) == 1,
              f"lobby_info toont {len(lobby.get('players', []))} spelers")
        # Precies dit is waar game.py zijn is_host uit haalt, en dus waar
        # de server settings-knop aan of uit gaat.
        check(lobby["host_pid"] == h2.player_id,
              "is_host zou onjuist uitvallen")
        check("lobby_options" in lobby,
              "lobby_info mist lobby_options, dus de settings-knop heeft niets")

h2._stop_host()
check(h2.hosted_server is None, "_stop_host liet de server achter")

if fouten:
    for f in fouten:
        print("FOUT:", f)
    sys.exit(1)
print("HOSTEN OK")
'''


@test
def hosten_eigen_server_blijft_draaien_en_je_zit_er_in():
    """Na HOST SERVER moet je zelf in de lobby staan, als host."""
    path = os.path.join(TEMP_DIR, "gunk_hosten_driver.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(HOSTEN_DRIVER)
    # Hosten is verbinden, en verbinden schrijft mp_config.json met de
    # laatste naam/ip/poort. Zonder deze kleed je het bestand van de speler
    # aan met "HostSpeler" op een willekeurige poort.
    with keep_player_files():
        try:
            proc = subprocess.run([sys.executable, path, ROOT],
                                  capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            check(False, "hosten liep vast (time-out)")
            return
    stdout = proc.stdout or ""
    if "HOSTEN OK" in stdout:
        return
    check(False, f"hosten gaf fouten:\n{stdout[-900:]}"
          + "\n" + (proc.stderr or "")[-900:])


# ── muziek: één soundtrack tegelijk ──────────────────────────────
#
# De main loop mocht vroeger starten zodra er _intro_duration
# milliseconden voorbij waren. Dat is een klok, geen geluid: pauze je
# in die tijd, dan loopt de klok door terwijl de intro stilstaat, en
# begint de loop ernaast. Na het hervatten speelden ze over elkaar.
#
# Hier draaien we de echte Game en de echte _maybe_start_main_loop,
# want dat gedrag is alleen in het echte spel te bewijzen.

MUZIEK_DRIVER = r'''
import os, sys, traceback
os.environ["SDL_VIDIODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ.pop("GUNK_HEADLESS", None)
ROOT = sys.argv[1]
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.argv = ["game.py"]

import pygame

import game as gamemodule

g = gamemodule.Game()

fouten = []


def check(voorwaarde, bericht):
    if not voorwaarde:
        fouten.append(bericht)


class Tel:
    """Telt hoe vaak de main loop gestart wordt."""

    def __init__(self, snd, naam):
        self.snd = snd
        self.naam = naam
        self.starts = 0

    def play(self, *a, **kw):
        if self.naam == "main loop":
            self.starts += 1
        return self.snd.play(*a, **kw)

    def stop(self, *a, **kw):
        return self.snd.stop(*a, **kw)

    def set_volume(self, v):
        return self.snd.set_volume(v)

    def get_length(self):
        return self.snd.get_length()


g.main_music_loop = Tel(g.main_music_loop, "main loop")
g.main_music_intro = Tel(g.main_music_intro, "intro")

try:
    # ── A: zolang de intro speelt mag de main loop niet losgaan ──
    g.reset_game()
    check(g._intro_channel is not None,
          "er werd geen kanaal vastgehouden om de intro op te volgen")
    check(g._intro_channel.get_busy(),
          "de intro speelde niet, dus de test meet hier niets")

    for _ in range(120):
        g._maybe_start_main_loop()
    check(g.main_music_loop.starts == 0,
          f"de main loop startte {g.main_music_loop.starts} keer terwijl de "
          f"intro nog bezig was")

    # ── B: pauzeren mag het niet door de klok heen helpen ──
    # Precies het scenario uit de klacht: de klok loopt door, de
    # audio staat stil, en de loop begint alsnog ernaast.
    pygame.mixer.pause()
    for _ in range(120):
        g._maybe_start_main_loop()
    check(g.main_music_loop.starts == 0,
          f"tijdens een pauze startte de main loop {g.main_music_loop.starts} "
          f"keer alsof de intro uit was")
    pygame.mixer.unpause()

    # ── C: zodra het introkanaal echt vrij is, mag hij door ──
    g.main_music_intro.stop()
    g._maybe_start_main_loop()
    check(g.main_music_loop.starts == 1,
          f"de main loop startte {g.main_music_loop.starts} keer in plaats "
          f"van 1 toen de intro klaar was")

    # ── D: en niet nog een keer daarna ──
    for _ in range(50):
        g._maybe_start_main_loop()
    check(g.main_music_loop.starts == 1,
          f"de main loop startte {g.main_music_loop.starts} keer in totaal")

    bezet = [i for i in range(pygame.mixer.get_num_channels())
             if pygame.mixer.Channel(i).get_busy()]
    check(len(bezet) == 1,
          f"er speelden {len(bezet)} geluiden tegelijk: kanalen {bezet}")

    # ── E: de baas pakt de muziek over, dan wacht de loop op ──
    g.main_music_loop.starts = 0
    g._main_loop_started = False
    g._intro_start = pygame.time.get_ticks()
    g._intro_channel = None
    if g.boss_music:
        g.main_music_loop.stop()
        g.main_music_intro.stop()
        g.boss_music.play(loops=-1)
        g._main_loop_started = True      # zoals de code het doet
        g._intro_channel = None
        for _ in range(50):
            g._maybe_start_main_loop()
        check(g.main_music_loop.starts == 0,
              f"de main loop startte {g.main_music_loop.starts} keer bovenop "
              f"de baasmuziek")
        g.boss_music.stop()

except Exception:
    traceback.print_exc()
    sys.exit(1)

if fouten:
    for f in fouten:
        print("FOUT:", f)
    sys.exit(1)

print("MUZIEK OK")
'''


@test
def muziek_main_loop_start_niet_op_de_klok():
    """Eén soundtrack tegelijk, ook als je in de intro pauzeert."""
    path = os.path.join(TEMP_DIR, "gunk_muziek_driver.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(MUZIEK_DRIVER)
    try:
        proc = subprocess.run([sys.executable, path, ROOT],
                              capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        check(False, "de muziektest liep vast (time-out)")
        return
    stdout = proc.stdout or ""
    if "MUZIEK OK" in stdout:
        return
    check(False, "de muziektest gaf fouten:\n" + stdout[-800:]
          + "\n" + (proc.stderr or "")[-800:])


# ── runner ─────────────────────────────────────────────────────

def main():
    pattern = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    selected = [t for t in TESTS if not pattern or pattern in t.__name__]
    say = lambda s: print(s, flush=True)
    say(f"multiplayer-tests: {len(selected)} van {len(TESTS)}")
    failed = []
    for t in selected:
        t0 = time.time()
        # Eerst zeggen welke test begint. Een test die blijft hangen is
        # anders onzichtbaar, en dat kostte ons al een keer tien minuten.
        if VERBOSE:
            say(f"  ...  {t.__name__}")
        try:
            t()
        except Exception as e:
            failed.append(t.__name__)
            say(f"  FAIL  {t.__name__}")
            say(f"        {type(e).__name__}: {e}")
        else:
            say(f"  ok    {t.__name__}  ({time.time() - t0:.1f}s)")
    say("")
    if failed:
        say(f"{len(failed)} MISLUKT: {', '.join(failed)}")
        return 1
    say("alles groen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
