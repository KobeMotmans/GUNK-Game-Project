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

from src.network.protocol import (encode_packet, decode_packet,      # noqa: E402
                                  PACKET_TYPE_TO_ID)
from src.network.server_game import ServerGame                # noqa: E402
from src.network.network import NetworkClient                  # noqa: E402
from src.core.config import (MAX_PLAYERS, ELEVATOR_WAIT_DIST,   # noqa: E402
                             ELEVATOR_WAIT_FRAMES, ELEVATOR_STUCK_FRAMES,
                             TILE_SIZE, MAX_LEVEL, MAP_PATH)  # noqa: E402
from src.core.map_loader import M                         # noqa: E402
from math import hypot, pi  # noqa: E402

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


def _staat_in_muur(pos):
    """Staat dit punt op de nu geladen kaart tegen een muur?

    Let op: M is de kaart die de server nu heeft geladen, dus dit slaat op
    het level waar de speler NA de overgang zou zitten.
    """
    tx, ty = int(pos[0] // TILE_SIZE), int(pos[1] // TILE_SIZE)
    breed, hoog = len(M.MAP[0]), len(M.MAP)
    if tx < 0 or ty < 0 or tx >= breed or ty >= hoog:
        return "buiten de kaart"
    return "muur" if M.MAP[ty][tx] == 1 else "open"


def _rijdt_lift_tot_overgang(sg, seqs=None, ticks=None):
    """Zet alle spelers op de uitgang en rijd totdat het level verandert.

    Vergelijkt met het level waarmee je begon, anders stopt hij meteen:
    de helper wordt ook gebruikt als het level al 1 is.
    """
    if ticks is None:
        ticks = ELEVATOR_WAIT_FRAMES + 300
    if seqs is None:
        seqs = {}
    begin_level = sg.level
    for _ in range(ticks):
        seqs = drive_lift(sg, len(sg.players), [True] * len(sg.players),
                          [(ON_TILE, 0)] * len(sg.players), 1, seqs)
        if sg.level != begin_level or sg.escaped:
            break
    return seqs


@test
def lift_spawnt_niet_in_een_muur():
    """Een vertraagd clientpakket mag de nieuwe spawn niet wegschrijven.

    De speler is client-authoritative, dus de server neemt elke positie over.
    Tijdens de overgang gaat er een pakket onderweg dat nog de positie van de
    OUDE level draagt. Op de nieuwe kaart kan dat punt midden in een muur
    staan, en de client teleporteert er dan naartoe zodra hij de nieuwe level
    ziet. Dat was een echte bug: je startte de volgende level in een muur.
    """
    sg = make_lift_game(1)
    oude_pos = (sg.exit_pos.x, sg.exit_pos.y)
    seqs = _rijdt_lift_tot_overgang(sg)
    check(sg.level == 1, f"level 1 niet gehaald (staande op {sg.level})")

    spawn = M.SPAWNS["player"]
    check(_staat_in_muur(spawn) == "open",
          "de spawn van de nieuwe level staat zelf in een muur, "
          "deze test kan dan niets bewijzen")

    # Het pakket dat al onderweg was: de client stond nog op level 0.
    seqs[0] = seqs.get(0, 0) + 1
    sg.process_input(0, {"seq": seqs[0], "pos": oude_pos, "state": "game",
                         "level": 0})

    p = sg.players[0]
    check(_staat_in_muur((p["pos"].x, p["pos"].y)) == "open",
          f"speler staat in een muur op level {sg.level}: "
          f"({p['pos'].x:.0f}, {p['pos'].y:.0f})")

    state = sg.get_state()
    verstuurd = state["players"][0]["pos"]
    check(_staat_in_muur(verstuurd) == "open",
          f"de server verstuurt een muurpositie door: {verstuurd}")
    check(list(verstuurd) == [spawn[0], spawn[1]],
          f"verstuurde positie {verstuurd} is niet de spawn {spawn}")


@test
def lift_posities_komen_weer_goed_na_de_overgang():
    """De weigering mag niet permanent zijn: na de overgang telt de client
    weer mee, anders zou de speler bevroren zijn op zijn nieuwe level."""
    sg = make_lift_game(1)
    seqs = _rijdt_lift_tot_overgang(sg)
    seqs[0] = seqs.get(0, 0) + 1
    sg.process_input(0, {"seq": seqs[0], "pos": (10.0, 20.0), "state": "game",
                         "level": 1})
    p = sg.players[0]
    check(abs(p["pos"].x - 10.0) < 0.01 and abs(p["pos"].y - 20.0) < 0.01,
          f"een pakket van de nieuwe level werd niet doorgelaten: "
          f"({p['pos'].x:.0f}, {p['pos'].y:.0f})")


@test
def lift_escape_stuurt_geen_onbestaande_level():
    """Na de laatste level mag het levelnummer niet verder dan MAP_PATH.

    Vroeger telde de server door tot 5 terwijl er maar vijf kaarten zijn. De
    client probeerde dan MAP_PATH[5] te laden, en bleef op 4 hangen terwijl de
    server op 5 stond.
    """
    sg = make_lift_game(1)
    seqs = {}
    for verwacht in range(1, MAX_LEVEL + 1):
        sg.enemies = []  # elke level laadt zijn eigen enemies er weer bij
        seqs = _rijdt_lift_tot_overgang(sg, seqs)
        check(sg.level == verwacht,
              f"level {verwacht} niet gehaald (staande op {sg.level})")

    # Eén keer nog: nu pas is de laatste level bereikt en moet escape komen.
    sg.enemies = []
    _rijdt_lift_tot_overgang(sg, seqs)

    check(sg.escaped is True, "escape werd niet gemeld na de laatste level")
    check(sg.elevator_transition is False,
          "elevator_transition bleef staan na escape")
    check(sg.level < len(MAP_PATH),
          f"level {sg.level} bestaat niet in MAP_PATH ({len(MAP_PATH)} kaarten)")
    state = sg.get_state()
    check(0 <= state["level"] < len(MAP_PATH),
          f"de state stuurt level {state['level']}, geen geldige kaart")


@test
def lift_host_teleporteert_naar_de_spawn():
    """Een host die zelf server is, moet ook echt verplaatst worden.

    Dit is de variant die `lift_spawnt_niet_in_een_muur` niet ving. Bij
    zelfhosten draait de server in een draadje in hetzelfde proces en deelt
    hij de module-singleton M. De server zet M.map_level alvast op de nieuwe
    level in _setup_level. Hing de teleport van de client aan
    `new_level != M.map_level`, dan sloeg hij die bij de host over en bleef
    die op zijn oude positie staan, terwijl een externe client (eigen proces,
    eigen M) wél verplaatst werd. Die oude positie kan midden in een muur op
    de nieuwe kaart staan.

    We draaien de server hier dus in-proces, precies zoals bij zelfhosten.
    """
    from src.core.map_loader import M as SHARED_M

    sg = make_lift_game(1)
    oude_pos = (sg.exit_pos.x, sg.exit_pos.y)
    begin_level = sg.level
    _rijdt_lift_tot_overgang(sg)
    check(sg.level != begin_level, "de lift ging niet over")

    # Dit is de hele truc: de server heeft M.map_level al bijgewerkt, precies
    # zoals in het echte spel omdat ze hetzelfde proces delen. Daardoor is de
    # conditie waar het oude code-blok op hing NIET meer waar, en dat is
    # precies de bug.
    check(SHARED_M.map_level == sg.level,
          "de server werkte M.map_level niet bij, dan testen we hier niets")

    state = sg.get_state()
    new_level = state["level"]

    # De oude teleport deed dit, en is nu onwaar, dus hij sloeg over:
    check(not (new_level != SHARED_M.map_level),
          "M.map_level loopt niet vooruit; de oude code zou hier wél werken "
          "en de test zou niets bewijzen")

    # De nieuwe teleport vergelijkt met wat de client zelf geladen heeft, en
    # die klopt hier nog niet, dus hij gaat wél door.
    check(new_level != begin_level,
          "de client denkt dat hij dit level al geladen heeft")

    pdata = next(p for p in state["players"] if p.get("id") == 0)
    bestelde_pos = tuple(pdata["pos"])
    check(_staat_in_muur(bestelde_pos) == "open",
          f"de server stuurt een muurpositie: {bestelde_pos}")

    # En de positie die de host daadwerkelijk zou krijgen is de spawn van de
    # nieuwe level, niet de oude positie uit de vorige level.
    spawn = SHARED_M.SPAWNS["player"]
    check(list(bestelde_pos) == [spawn[0], spawn[1]],
          f"host komt op {bestelde_pos} in plaats van de spawn {spawn}")
    check(_staat_in_muur(oude_pos) != "open",
          "de oude uitgangspositie is open op de nieuwe kaart, "
          "dan zou de bug niet zichtbaar zijn")


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


class ChunkDropper:
    """Staat tussen de server en het netwerk en maakt een gat in de rij.

    UDP gooit willekeurig pakketten weg, dus een overdracht van honderden
    stukken komt nooit in een keer volledig aan. Dit maart dat
    reproduceerbaar: een paar vaste stukken vallen weg, één keer, en daarna
    is de verbinding weer in orde. Alleen de stukken van de skin die we
    toetsen worden aangeraakt, zodat al het andere verkeer gewoon doorgaat.
    """

    def __init__(self, real, skin_id, drop_indices=()):
        self._real = real
        self._skin_id = skin_id
        # Eenmalig: na het weggooien is de overdracht weer heel.
        self._drop = set(drop_indices)
        self.dropped = 0
        self.sent = []          # de stuknummers die zijn doorgelaten

    def sendto(self, data, addr=None):
        try:
            pkt = decode_packet(data)
        except Exception:
            pkt = {}
        index = pkt.get("chunk")
        if (pkt.get("type") == "skin_chunk"
                and pkt.get("skin_id") == self._skin_id):
            if index in self._drop:
                self._drop.discard(index)
                self.dropped += 1
                return len(data)
            self.sent.append(index)
        return self._real.sendto(data, addr)

    def __getattr__(self, name):
        return getattr(self._real, name)


class tel_skin_verzoeken:
    """Legt de skin_request-pakketten vast die de client op de lijn zet.

    De vraag is niet alleen "komt de skin aan", maar ook "stuurt de client
    bij een gat alleen dát gat opnieuw op, of toch de hele rij". Dat is het
    verschil tussen één keer de skin over de lijn en elke poging de hele
    skin opnieuw.

    Alleen de verzoeken voor `skin_id` worden geteld: een achtergrond
    downloader uit een andere test stuurt anders zijn eigen verzoeken
    tussendoor.
    """

    def __init__(self, skin_id):
        self.skin_id = skin_id

    def __enter__(self):
        self.verzoeken = []          # None = "geef me de hele rij"
        self._orig = socket.socket.sendto

        def sendto(sock, data, *args):
            try:
                pkt = decode_packet(data)
            except Exception:
                pkt = {}
            if (pkt.get("type") == "skin_request"
                    and pkt.get("skin_id") == self.skin_id):
                self.verzoeken.append(pkt.get("chunks"))
            return self._orig(sock, data, *args)

        socket.socket.sendto = sendto
        return self

    def __exit__(self, *exc):
        socket.socket.sendto = self._orig


class temp_skin_cache:
    """Zet de skin-cache van SkinManager op een tijdelijke map.

    Zonder dit zou de test de echte skins van de speler overschrijven.
    """

    def __enter__(self):
        import src.assets.skin_manager as sm
        self._sm = sm
        self._orig = sm._get_cache_dir
        self.dir = os.path.join(TEMP_DIR, "gunk_test_skins")
        os.makedirs(self.dir, exist_ok=True)
        for name in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, name))
        sm._get_cache_dir = lambda: self.dir
        sm.SkinManager._cache.clear()
        return self

    def __exit__(self, *exc):
        self._sm._get_cache_dir = self._orig
        self._sm.SkinManager._cache.clear()
        for name in os.listdir(self.dir):
            try:
                os.unlink(os.path.join(self.dir, name))
            except OSError:
                pass


@test
def skin_download_vraagt_alleen_de_gaten_op():
    """Een skin van een paar honderd kB komt in honderden UDP-stukken.

    Omdat UDP pakketten willekeurig weggooit, ontstaat er altijd een gat in
    de rij. Wie de hele rij opnieuw opvraagt, stuurt bij elke poging de
    volledige skin opnieuw over de lijn, en bij honderden stukken komt
    daar nooit een moment waarop alles toevallig binnenkomt. De ontvanger
    moet dus alleen de stukken opnieuw vragen die hij echt mist.
    """
    import src.assets.skin_manager as sm

    with keep_player_files():
        with LocalServer() as srv:
            # Echt ruis: een gladde kleur geeft een piepklein PNG en dan
            # bewijst de test niets.
            rng = random.Random(20260930)
            noise = bytes(rng.randrange(256) for _ in range(512 * 512 * 3))
            surface = pygame.Surface((512, 512))
            pygame.surfarray.blit_array(
                surface,
                numpy.frombuffer(noise, dtype=numpy.uint8).reshape(512, 512, 3))
            stored = os.path.join(SKIN_DIR, "skin_999.png")
            pygame.image.save(surface, stored)
            with open(stored, "rb") as f:
                original = f.read()
            srv.skin_manifest = [{"id": 999, "name": "gat",
                                  "uploader": "test"}]
            n_chunks = -(-len(original) // 1200)
            check(n_chunks > 100,
                  f"de testskin is maar {n_chunks} stukken en bewijst niets")

            # Vijf stukken uit het midden vallen weg, één keer.
            gaten = [n_chunks // 3 + k for k in range(5)]
            proxy = ChunkDropper(srv.udp_socket, 999, gaten)
            srv.udp_socket = proxy

            with temp_skin_cache() as cache:
                sm.SkinManager.set_server_addr(("127.0.0.1", srv.port))
                with tel_skin_verzoeken(999) as gezien:
                    ok = sm.SkinManager.download_skin(999)

                check(ok, f"download mislukte terwijl de verbinding "
                          f"{proxy.dropped} stukken liet vallen")
                check(proxy.dropped == len(gaten),
                      f"er vielen {proxy.dropped} van de {len(gaten)} "
                      f"gekozen stukken weg")

                got_path = os.path.join(cache.dir, "skin_999.png")
                check(os.path.exists(got_path),
                      "de download slaagde maar schreef de skin niet weg")
                with open(got_path, "rb") as f:
                    got = f.read()
                check(len(got) == len(original),
                      f"ontvangen {len(got)} bytes, origineel {len(original)}")
                check(got == original, "de ontvangen skin is niet bytegelijk")

                # De kern van de fix. Zonder gatenlijst stuurt de server de
                # hele rij, en dat is bij deze hoeveelheid data een manier om
                # nooit klaar te komen: bij elke poging komen er nieuwe
                # gaten bij.
                check(len(gezien.verzoeken) >= 2,
                      f"er kwamen maar {len(gezien.verzoeken)} verzoeken; "
                      f"dan viel er niets weg en de test bewijst niets")
                check(gezien.verzoeken[0] is None,
                      "het eerste verzoek moet om de hele rij vragen")
                hele_rijen = [v for v in gezien.verzoeken[1:] if v is None]
                check(not hele_rijen,
                      f"de client vroeg na een gat {len(hele_rijen)} keer de "
                      f"hele rij opnieuw op in plaats van alleen de gaten")
                gaten = [v for v in gezien.verzoeken[1:] if v]
                check(gaten, "na een gat werd er niets opnieuw opgevraagd")
                check(max(len(v) for v in gaten) * 5 < n_chunks,
                      f"de client vroeg {max(len(v) for v in gaten)} stukken "
                      f"opnieuw op voor een rij van {n_chunks}")


@test
def skins_komen_via_de_achtergronddownload_binnen():
    """De klacht van een echte speler: er staan skins in de lijst, maar je
    ziet ze niet. De hele lijst moet dus op de achtergrond binnenkomen,
    over een verbinding die af en toe een pakketje laat vallen.

    Deze test waakt over het hele pad: manifest -> achtergronddraadje ->
    bestand op schijf -> bruikbare afbeelding. De verspilling die ontstaat
    wanneer de client de hele rij opnieuw opvraagt vangt hij níet, want op
    localhost komt de tweede ronde gewoon aan. Daarvoor zijn er twee
    gerichte tests die het gedrag meeten in plaats van het gevolg.
    """
    import src.assets.skin_manager as sm

    with keep_player_files():
        with LocalServer() as srv:
            # Echte skins uit de repo, dus geen opgepotte testdata.
            srv.skin_manifest = [{"id": 106, "name": "A", "uploader": "t"},
                                 {"id": 107, "name": "B", "uploader": "t"}]
            for sid in (106, 107):
                check(os.path.exists(os.path.join(SKIN_DIR, f"skin_{sid}.png")),
                      f"skin {sid} ontbreekt in de repo, test kan niet draaien")
            proxy = ChunkDropper(srv.udp_socket, 106, [3, 11])
            srv.udp_socket = proxy

            with temp_skin_cache() as cache:
                # Een achtergronddraadje van een eerdere test kan nog
                # bezig zijn; die pakken de skins ook mee, en daar is niets
                # mis mee. We wachten daarom niet op 'klaar' maar op de
                # bestanden zelf.
                client = NetworkClient()
                try:
                    check(client.connect("127.0.0.1", srv.port, "skiper"),
                          "connect lukte niet")
                    wanted = [os.path.join(cache.dir, f"skin_{s}.png")
                              for s in (106, 107)]
                    deadline = time.time() + 30.0
                    while time.time() < deadline:
                        if all(os.path.exists(p) for p in wanted):
                            break
                        time.sleep(0.05)
                finally:
                    try:
                        client.disconnect()
                    except Exception:
                        pass

                check(proxy.dropped == 2,
                      f"de verbinding liet {proxy.dropped} van de 2 "
                      f"gekozen stukken vallen")
                for sid, pad in zip((106, 107), wanted):
                    check(os.path.exists(pad),
                          f"skin {sid} staat in de lijst maar is niet opgehaald")
                    try:
                        breed, hoog = pygame.image.load(pad).get_size()
                    except pygame.error as e:
                        check(False, f"skin {sid} is geen bruikbare afbeelding: {e}")
                    check(breed > 0 and hoog > 0,
                          f"skin {sid} heeft maat {breed}x{hoog}")


@test
def skin_server_stuurt_alleen_de_gevraagde_stukken():
    """Vraagt de client om drie stukken, dan stuurt de server drie stukken.

    Dit is de andere helft van het gatenvullen: de client vraagt alleen wat
    hij mist, dus als de server daar gehoorloos de hele rij voor terugstuurt
    ligt bij elke kleine packetverlies de volledige skin over de lijn.
    """
    with keep_player_files():
        with LocalServer() as srv:
            rng = random.Random(20260930)
            noise = bytes(rng.randrange(256) for _ in range(512 * 512 * 3))
            surface = pygame.Surface((512, 512))
            pygame.surfarray.blit_array(
                surface,
                numpy.frombuffer(noise, dtype=numpy.uint8).reshape(512, 512, 3))
            stored = os.path.join(SKIN_DIR, "skin_999.png")
            pygame.image.save(surface, stored)
            srv.skin_manifest = [{"id": 999, "name": "drie stukken",
                                  "uploader": "test"}]
            n_chunks = -(-os.path.getsize(stored) // 1200)
            check(n_chunks > 100,
                  f"de testskin is maar {n_chunks} stukken en bewijst niets")

            proxy = ChunkDropper(srv.udp_socket, 999, ())
            srv.udp_socket = proxy

            gevraagd = [3, 17, n_chunks - 1]
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            ontvangen = []
            try:
                sock.sendto(encode_packet({"type": "skin_request",
                                           "skin_id": 999,
                                           "chunks": gevraagd}),
                            ("127.0.0.1", srv.port))
                deadline = time.time() + 2.0
                while time.time() < deadline and len(ontvangen) < len(gevraagd):
                    data, _ = sock.recvfrom(65536)
                    pkt = decode_packet(data)
                    if (pkt.get("type") == "skin_chunk"
                            and pkt.get("skin_id") == 999):
                        ontvangen.append(pkt["chunk"])
            finally:
                sock.close()

            check(sorted(ontvangen) == sorted(gevraagd),
                  f"gevraagd {gevraagd}, gekregen {sorted(ontvangen)}")
            # Zonder de fix stuurt de server de hele rij. De klant stopt met
            # lezen zodra hij zijn drie stukken heeft, dus het exacte aantal
            # wanneer de server zijn socket dichtgooit is onvoorspelbaar. Wat
            # wel vastligt: het zijn er veel meer dan drie.
            check(len(proxy.sent) <= 4 * len(gevraagd),
                  f"de server stuurde {len(proxy.sent)} stukken voor een "
                  f"verzoek om {len(gevraagd)}; hij stuurt de hele rij mee")


@test
def protocol_kent_elke_sleutel_die_de_code_gebruikt():
    """Elke sleutel die een pakket in gaat moet in KEY_TO_ID staan.

    Een onbekende sleutel wordt door encode_packet als 255 geschreven, en
    dat is precies de TERMINATOR. De decoder stopt daar dan stilzwijgend
    midden in het pakket: het veld valt weg, net als alles wat erop volgt,
    zonder ook maar een foutmelding. Dat is stilzwijgend dataverlies op
    iedere plek waar iemand een veld toevoegt en vergeet het aan te melden.
    """
    import ast

    from src.network.protocol import KEY_TO_ID
    onbekend = {}
    doorzocht = 0
    overslaan = (".git", ".venv", "venv", "build", "dist", "__pycache__",
                 ".vscode", "node_modules")
    for dirpad, dirnamen, namen in os.walk(ROOT):
        dirnamen[:] = [d for d in dirnamen if d not in overslaan]
        for naam in namen:
            if not naam.endswith(".py"):
                continue
            pad = os.path.join(dirpad, naam)
            rel = os.path.relpath(pad, ROOT)
            try:
                with open(pad, "rb") as f:
                    boom = ast.parse(f.read(), filename=pad)
            except (OSError, SyntaxError, ValueError):
                continue
            doorzocht += 1
            for knoop in ast.walk(boom):
                if not isinstance(knoop, ast.Dict):
                    continue
                sleutels = [k.value for k in knoop.keys
                            if isinstance(k, ast.Constant)
                            and isinstance(k.value, str)]
                # Alleen echte pakketten: een dict met een "type" dat in
                # PACKET_TYPE_TO_ID staat. Anders pakken we ook gewone
                # woordenlijstjes zoals {"type": "ammo", ...} mee.
                if "type" not in sleutels:
                    continue
                type_waarde = knoop.values[sleutels.index("type")]
                if not (isinstance(type_waarde, ast.Constant)
                        and type_waarde.value in PACKET_TYPE_TO_ID):
                    continue
                for s in sleutels:
                    if s != "type" and s not in KEY_TO_ID:
                        onbekend.setdefault(s, set()).add(rel)

    check(doorzocht > 10,
          f"er werden maar {doorzocht} bestanden doorzocht, "
          f"dan bewijst deze test niets")
    check(not onbekend,
          "deze sleutels worden verstuurd maar staan niet in KEY_TO_ID, "
          f"waardoor het hele pakket bij de decoder wordt afgekapt: "
          + "; ".join(f"{s!r} in {', '.join(sorted(w))}"
                      for s, w in sorted(onbekend.items())))

    # Een geregistreerde sleutel helpt niets als haar nummer 255 is: dat is
    # de TERMINATOR, dus de decoder stopt er alsnog midden in het pakket.
    botsers = sorted(s for s, nummer in KEY_TO_ID.items() if nummer >= 255)
    check(not botsers,
          f"deze sleutels hebben nummer 255 of hoger en werken daardoor "
          f"niet: {botsers}")


@test
def skin_cache_valt_terug_op_een_bruikbare_plek():
    """Een cachemap waar niet in geschreven kan worden mag het verbinden
    niet blokkeren.

    De klap komt via has_skin_locally in start_background_download terecht,
    en vandaar in NetworkClient.connect. Een speler die het spel bij
    voorbeeld uit een map zonder schrijfrechten start zou dan niet eens meer
    inloggen, alleen omdat er geen plek is om skins te bewaren.
    """
    import src.assets.skin_manager as sm

    # ── De voorkeursplek is onbruikbaar ──────────────────────────
    # Een gewoon bestand als bovenliggende map: elke map erbovenop maken
    # klapt met NotADirectoryError, precies zoals een schrijfverboden plek.
    blokkade = os.path.join(TEMP_DIR, "gunk_test_geen_map")
    with open(blokkade, "wb") as f:
        f.write(b"x")

    origineel = sm.appdata_path
    sm.appdata_path = lambda rel: os.path.join(blokkade, rel)
    try:
        pad = sm._get_cache_dir()
        check(os.path.isdir(pad), f"geen bruikbare cachemap gevonden: {pad}")
        check(not pad.startswith(blokkade),
              f"de cachemap ligt nog steeds op de onbruikbare plek: {pad}")
        check(os.access(pad, os.W_OK),
              f"de gevonden cachemap is niet beschrijfbaar: {pad}")
    finally:
        sm.appdata_path = origineel
        try:
            os.unlink(blokkade)
        except OSError:
            pass

    # ── En als er helemaal geen schrijfplek is ────────────────────
    # has_skin_locally draait midden in NetworkClient.connect. Een
    # schrijfplek die niets oplevert mag daar niet het verbinden
    # blokkeren, dus de vraag moet gewoon "nee" zijn.
    originele_keuze = sm._get_cache_dir

    def klapt_Altijd():
        raise OSError("geen schrijfplek")

    sm._get_cache_dir = klapt_Altijd
    try:
        sm.SkinManager._manifest = [{"id": 106, "name": "A", "uploader": "t"}]
        check(sm.SkinManager.has_skin_locally(106) is False,
              "zonder schrijfplek moet een skin als niet-bestaand tellen")
    finally:
        sm._get_cache_dir = originele_keuze
        sm.SkinManager._manifest = []


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


# ── minimap ────────────────────────────────────────────────────
#
# De minimap hoort te ontdekken in plaats van alles te tonen. Dat is drie
# regels waarvan de kracht zit in wat níet zichtbaar is, dus de kaartjes hieronder
# zijn klein en met opzet leesbaar: alles wat de speler ziet staat als `+` of `o`
# (onthouden) en alles wat hij niet ziet laat de test stuklopen.
#
# Er zit geen pygame in dit stuk: de zichtberekening staat los van de tekening
# in src/core/minimap.py, zodat hier geen scherm voor nodig is.

from src.core.minimap import (Minimap, UIT as MM_UIT, GEZIEN as MM_GEZIEN,  # noqa: E402
                              VOLLEDIG as MM_VOLLEDIG)


def mm_kaart(rijen):
    """'#' is een muur, '.' is vloer."""
    return [[1 if c == "#" else 0 for c in rij] for rij in rijen]


def mm_pos(tx, ty):
    """Het midden van tegel (tx, ty), in wereldpixels."""
    return (tx + 0.5) * TILE_SIZE, (ty + 0.5) * TILE_SIZE


# Dicht bij elkaar: (1,1) is de speler, (2,1) de muur recht voor zijn neus en
# (3,1) de vloer daarachter. De muur moet zichtbaar zijn en de vloer erachter
# niet, anders staat de hele kaart in één klap open.
MM_MUUR = mm_kaart([
    "#####",
    "#.#.#",
    "#####",
])

# Een gang die om de hoek loopt. Rij 1 is de gang recht vooruit, rij 3 ligt
# achter de speler, en (3,3) ligt wél in de kijkhoek maar achter een muur.
MM_GANG = mm_kaart([
    "#####",
    "#...#",
    "##.##",
    "#...#",
    "#####",
])


@test
def minimap_ziet_niet_door_muren():
    fog = Minimap()
    fog.update(MM_MUUR, 5, 3, *mm_pos(1, 1), 0.0, MM_GEZIEN)
    check(fog.is_zichtbaar(*mm_pos(2, 1)),
          "de muur recht voor de speler is niet zichtbaar; dan is er geen muur getekend")
    check(not fog.is_zichtbaar(*mm_pos(3, 1)),
          "de vloer achter die muur is wél zichtbaar: de kaart lekt door de muur")
    check(not fog.is_gezien(*mm_pos(3, 1)),
          "en die tegel wordt ook onthouden, dus hij blijft alsnog op de kaart staan")


# Een open tegel die aan alle kanten door muren omringd is. Daar zit de
# speler in het echte spel nooit, maar het is de enige vorm waarin het
# verschil tussen "de eigen tegel is gezaaid" en "de eigen tegel is onderweg
# teruggevonden" echt zichtbaar wordt: met maar één open buur komt de speler
# als buur van die buur gewoon terug.
MM_PLAATSJE = mm_kaart([
    "#####",
    "#.#.#",
    "#.#.#",
    "#####",
])


@test
def minimap_ziet_altijd_de_tegel_waar_je_op_staat():
    fog = Minimap()
    fog.update(MM_PLAATSJE, 5, 5, *mm_pos(2, 2), 0.0, MM_GEZIEN)
    check(fog.is_zichtbaar(*mm_pos(2, 2)),
          "de tegel waar de speler op staat is niet zichtbaar, dus de kaart "
          "tekent een gat onder zijn eigen voeten")


@test
def minimap_ziet_om_de_hoek_mar_niet_achter_je_rug():
    fog = Minimap()
    fog.update(MM_GANG, 5, 5, *mm_pos(1, 1), 0.0, MM_GEZIEN)
    check(fog.is_zichtbaar(*mm_pos(2, 1)) and fog.is_zichtbaar(*mm_pos(3, 1)),
          "de gang recht vooruit is niet zichtbaar, dus de rest van de test zuigt")
    check(fog.is_zichtbaar(*mm_pos(2, 2)),
          "de flood-fill stopt op de eerste muur en ziet de hoek niet om, dus de "
          "kaart is veel te blind")
    check(not fog.is_zichtbaar(*mm_pos(1, 3)),
          "achter de rug van de speler is zichtbaar, maar dit is een raycaster")
    check(not fog.is_zichtbaar(*mm_pos(3, 3)),
          "die tegel ligt in de kijkhoek en toch achter een muur, dus de hoek "
          "werkt niet als er een muur tussen zit")
    check(fog.is_zichtbaar(*mm_pos(1, 1)),
          "de tegel waar de speler op staat is niet zichtbaar, dus de kaart "
          "tekent een gat onder zijn eigen voeten")


@test
def minimap_onthoudt_tegels_die_je_al_gezien_hebt():
    fog = Minimap()
    fog.update(MM_GANG, 5, 5, *mm_pos(1, 1), 0.0, MM_GEZIEN)
    check(fog.is_zichtbaar(*mm_pos(2, 1)), "sanity: die tegel moet zichtbaar zijn")
    fog.update(MM_GANG, 5, 5, *mm_pos(1, 1), pi, MM_GEZIEN)
    check(not fog.is_zichtbaar(*mm_pos(2, 1)),
          "teken je om, dan blijft het zicht staan: je kijkt immers de andere kant op")
    check(fog.is_gezien(*mm_pos(2, 1)),
          "een gezien tegel wordt vergeten zodra je je omdraait, dus de kaart "
          "verdwijnt terwijl je er nog loopt")


@test
def minimap_vergeet_alles_bij_een_nieuw_level():
    # De eerste level is een open kamertje: vanuit de hoek zie je het helemaal.
    # Het volgende level is even groot maar heeft een muur in het midden, dus
    # vanaf dezelfde plek zie je veel minder. Precies daarom is te controleren
    # of er iets is overgeërfd: was het volgende level identiek, dan zou dat
    # ononderscheidbaar zijn van "opnieuw alles gezien".
    kamer = mm_kaart([
        "#####",
        "#...#",
        "#...#",
        "#...#",
        "#####",
    ])
    fog = Minimap()
    fog.update(kamer, 5, 5, *mm_pos(1, 1), 0.0, MM_GEZIEN)
    eerste = set(fog.gezien)
    check(len(eerste) > 1, "sanity: er is meer dan één tegel onthouden")

    # Zelfde positie, zelfde kijkrichting, zelfde kaart: dat is de tweede frame,
    # en die mag niets vergeten. Zou dit resetten, dan is de kaart na een
    # seconde leeg en ziet de speler er nooit iets van.
    fog.update(kamer, 5, 5, *mm_pos(1, 1), 0.0, MM_GEZIEN)
    check(fog.gezien == eerste,
          "dezelfde kaart opnieuw aanbieden vergeet de onthouden tegels, dus de "
          "kaart is na een frame al weer leeg")

    # Een nieuw level: zelfde afmetingen, andere lijst, want png_to_list_fast
    # maakt er bij elke level een nieuwe aan. De muur in het midden zorgt dat
    # er vanaf dezelfde hoek nu minder te zien is dan er onthouden is.
    fog.update(MM_GANG, 5, 5, *mm_pos(1, 1), 0.0, MM_GEZIEN)
    check(fog.zichtbaar < eerste,
          "sanity: het volgende level ziet minder dan het vorige onthouden had, "
          "dus er valt hier echt iets te verliezen")
    check(fog.gezien == fog.zichtbaar,
          "een nieuw level begint met de kaart van het vorige er al uit onthouden")


@test
def minimap_groeit_met_waar_je_hebt_geloopen():
    # Een gang van 22 tegels, ruim driemaal het zichtbereik van 7. Eén blik is
    # dus nadrukkelijk niet genoeg om hem te kennen.
    gang = mm_kaart([
        "#" * 24,
        "#" + "." * 22 + "#",
        "#" * 24,
    ])
    fog = Minimap()
    fog.update(gang, 24, 3, *mm_pos(1, 1), 0.0, MM_GEZIEN)
    check(not fog.is_zichtbaar(*mm_pos(22, 1)),
          "de speler ziet het eind van een 22 tegels lange gang in één blik, dus "
          "het zichtbereik wordt niet toegepast")
    oost = set(fog.zichtbaar)
    fog.update(gang, 24, 3, *mm_pos(22, 1), pi, MM_GEZIEN)
    check(fog.gezien > oost,
          "de kaart groeit niet mee met waar je loopt, dus verkennen levert "
          "niets op: je blijft hetzelfde stukje gang zien")


@test
def minimap_cheatstand_onthoudt_niets():
    fog = Minimap()
    fog.update(MM_GANG, 5, 5, *mm_pos(1, 1), 0.0, MM_GEZIEN)
    vooraf = set(fog.gezien)
    fog.update(MM_GANG, 5, 5, *mm_pos(1, 1), 0.0, MM_VOLLEDIG)
    check(len(fog.zichtbaar) == 25, "de cheatstand toont niet de hele kaart")
    check(fog.gezien == vooraf,
          "de cheatstand onthoudt de hele kaart, dus terugschakelen naar 'alleen "
          "gezien' kan niet meer: je heet dan alles te hebben gezien")
    fog.update(MM_GANG, 5, 5, *mm_pos(1, 1), 0.0, MM_GEZIEN)
    check(fog.gezien == vooraf,
          "terugschakelen naar 'alleen gezien' geeft niet de ontdekte kaart terug")


@test
def minimap_uit_onthoudt_niets():
    fog = Minimap()
    for _ in range(3):
        fog.update(MM_GANG, 5, 5, *mm_pos(1, 1), 0.0, MM_UIT)
    check(not fog.gezien,
          "met de kaart uit wordt er alsnog onthouden, dus aanzetten toont meteen "
          "al je verkende gebied van een vorige sessie")
    check(not fog.zichtbaar, "uitgezette kaart meldt toch wat er zichtbaar is")


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
import pygame
from src.ui.Menu import Menu_inst, Tekstballon
from src.network.protocol import encode_packet, decode_packet
from src.core.map_loader import M
from src.core.config import TILE_SIZE
from src.core import config as _cfg
from src.core.theme import theme
from src.core.minimap import Minimap, UIT as MINIMAP_UIT, GEZIEN as MINIMAP_GEZIEN, VOLLEDIG as MINIMAP_VOLLEDIG


def check_ui(cond, msg):
    if not cond:
        raise AssertionError(msg)


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

    # De tutorial-ballon. Dit is de route die crashte zodra de tutorial aan
    # stond: Tekstballon is geen Menu en riep daarom self._font_px aan, wat
    # daar niet bestaat. Game.__init__ zet al vijf welkomstregels in de
    # wachtrij, dus een update() maakt er een zichtbaar.
    game.bilal.update()
    game.bilal.draw()

    # Dezelfde route via interrupt, en via een lange regel zodat het omvullen
    # en de breedte-instelling ook echt getekend worden.
    game.bilal.interrupt("Onderbreking", 30)
    game.bilal.draw()
    game.bilal.clear()
    game.bilal.say("Een heel lange testregel voor het omvullen " * 8, 30)
    game.bilal.update()
    game.bilal.draw()

    # En de ballon rechtstreeks, want dat is de klasse die het deed klappen.
    Tekstballon("kort", 100, 10, game).draw()

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

    # ── de minimap ───────────────────────────────────────────
    #
    # De standaard is uit, en dat is een eis: de kaart onthoudt alleen wat je
    # echt hebt gezien, en dat is een manier van spelen, geen gratis voordeel.
    # `_settings_path` wijken we uit naar een tijdelijk bestand, want anders leest
    # de test de echte settings.json van de speler, en dan hangt de uitkomst af
    # van wat die toevallig op die dag bevat.
    import json, tempfile
    tmp_settings = os.path.join(tempfile.gettempdir(), "gunk_minimap_settings.json")
    if os.path.exists(tmp_settings):
        os.unlink(tmp_settings)
    game._settings_path = lambda: tmp_settings
    with open(tmp_settings, "w") as f:
        json.dump({"sfx_volume": 0.3}, f)          # bewust zonder minimap-sleutel
    game._load_settings()
    check_ui(game.minimap_mode == MINIMAP_UIT,
             "zonder instelling start de minimap niet uit")
    game.minimap = Minimap()
    menu.draw_minimap(game)                          # uit: tekent niets
    check_ui(not game.minimap.gezien,
             "een uitgezette minimap onthoudt alsnog wat de speler heeft gezien")

    # Uitgezet wordt er helemaal niets getekend. De eerste stap van het tekenen
    # is het opbouwen van de tegellagen, dus blijft die cache leeg, dan is er ook
    # niets op het scherm gezet.
    #
    # Niet het scherm zelf vergelijken: met de dummy videodriver is de inhoud
    # van het schermbuffer niet betrouwbaar, en zo'n vergelijking gaat dan
    # willekeurig rood zonder dat er iets stuk is.
    menu._minimap_vergeet()
    menu.draw_minimap(game)
    check_ui(menu._mm_kaart is None,
             "met de minimap uit worden de tegellagen toch opgebouwd, dus er is "
             "alsnog iets getekend")

    # Het pijltje van de speler moet op de plek staan waar de speler ook staat.
    # Dat is van alle markers de enige die ooit in het midden van het vakje stond,
    # en dat viel alleen met een blik op het scherm op. We tekenen daarom op een
    # eigen oppervlak in plaats van het scherm, en kijken waar het pijltje
    # terechtkomt ten opzichte van de tegel waar de speler op staat.
    game.minimap = Minimap()
    game.minimap_mode = MINIMAP_VOLLEDIG
    game.remote_players = []
    game.objects = {"enemies": [], "exit": None, "keycard": [], "ammo": [], "health": []}
    # Een tegel die open is, middenin het level, zodat het pijltje niet tegen de
    # rand aan komt te liggen.
    open_midden = [(x, y) for y in range(M.height) for x in range(M.width)
                   if M.MAP[y][x] != 1 and 2 <= x < M.width - 2 and 2 <= y < M.height - 2]
    check_ui(bool(open_midden), "geen open tegel met ruimte eromheen gevonden")
    tx, ty = open_midden[0]
    game.player.pos.x = (tx + 0.5) * TILE_SIZE
    game.player.pos.y = (ty + 0.5) * TILE_SIZE
    game.player.angle = 0.0                       # naar rechts, dus de punt wijst +x

    echt_scherm = _cfg.SCREEN
    try:
        _cfg.SCREEN = pygame.Surface((_cfg.WIDTH, _cfg.HEIGHT))
        menu.draw_minimap(game)
        plaatje = _cfg.SCREEN
    finally:
        _cfg.SCREEN = echt_scherm

    # Waar hoort het pijltje te staan? Zelfde omrekening als in draw_minimap:
    # de kaart is vierkant met de verhouding erin, dus met zwarte rand erbovenop.
    mm_size = theme.scaled("minimap.size", 0.12, "min")
    kaart_w, kaart_h = M.width, M.height
    if kaart_w >= kaart_h:
        doel_w = mm_size
        doel_h = max(1, int(mm_size * kaart_h / kaart_w))
    else:
        doel_h = mm_size
        doel_w = max(1, int(mm_size * kaart_w / kaart_h))
    in_x = (mm_size - doel_w) / 2
    in_y = (mm_size - doel_h) / 2
    screen_x, screen_y = menu._minimap_positie(mm_size)

    def op_scherm(px, py):
        """Waar een tegel van de kaart op het scherm terechtkomt."""
        mx = in_x + (px / TILE_SIZE) / kaart_w * doel_w
        my = in_y + (py / TILE_SIZE) / kaart_h * doel_h
        return int(screen_x + mx), int(screen_y + my)

    speler_scherm = op_scherm(game.player.pos.x, game.player.pos.y)
    # Het midden van het vakje: waar het pijltje vroeger onterecht stond.
    midden_scherm = (int(screen_x + mm_size / 2), int(screen_y + mm_size / 2))

    speler_kleur = tuple(theme.color("minimap.player", (0, 255, 0)))
    # De punt steekt een paar pixels voor de speler uit, dus kijk in een klein
    # raamwerk om de tegel heen in plaats van op één pixel.
    raam = 3
    groen_bij_speler = any(
        plaatje.get_at((speler_scherm[0] + dx, speler_scherm[1] + dy))[:3] == speler_kleur
        for dy in range(-raam, raam + 1) for dx in range(0, raam + 2))
    check_ui(groen_bij_speler,
             f"het pijltje van de speler staat niet op de tegel waar hij staat "
             f"({tx},{ty}), dus de kaart zegt op de verkeerde plek dat hij is")
    groen_midden = any(
        plaatje.get_at((midden_scherm[0] + dx, midden_scherm[1] + dy))[:3] == speler_kleur
        for dy in range(-raam, raam + 1) for dx in range(-raam, raam + 1))
    check_ui(not groen_midden,
             "het pijltje van de speler staat in het midden van het vakje in "
             "plaats van op zijn eigen positie")

    # De drie standen tekenen, en de knop schakelt ze in de juiste volgorde.
    for stand in (MINIMAP_UIT, MINIMAP_GEZIEN, MINIMAP_VOLLEDIG):
        game.minimap_mode = stand
        menu.draw_minimap(game)
    game.minimap_mode = MINIMAP_UIT
    for _i in range(3):
        game.cycle_minimap()
        check_ui(game.minimap_mode in (MINIMAP_GEZIEN, MINIMAP_VOLLEDIG, MINIMAP_UIT),
                 f"cycle_minimap gaf een onbekende stand: {game.minimap_mode}")
    check_ui(game.minimap_mode == MINIMAP_UIT,
             "drie keer doorschakelen komt niet terug op uit")

    # Een levelwissel terwijl de minimap aanstaat: de getekende lagen horen op
    # de nieuwe kaart, niet op de kaart van daarvoor.
    game.minimap_mode = MINIMAP_GEZIEN
    menu.draw_minimap(game)
    game.level_up()
    menu.draw_minimap(game)
    check_ui(menu._mm_kaart is M.MAP,
             "na een levelwissel tekent de minimap nog de vorige kaart")

    # Het scherm zelf, met de knop die de stand toont.
    game.state = "settings"
    game._settings_return = "menu"
    menu.draw_settings([], game)

    # En nu in de pixels kijken. "Tekent zonder fout" zegt niets over wát er
    # getekend wordt, dus hier staan we de tegellagen tegenover de tegels die
    # de tracker kent. Zonder de omgeving erbij te zetten, want die tekent ook
    # over de kaart heen.
    game.minimap = Minimap()
    game.minimap_mode = MINIMAP_GEZIEN
    game.remote_players = []
    game.objects = {"enemies": [], "exit": None, "keycard": [], "ammo": [], "health": []}
    open_tegels = [(x, y) for y in range(M.height) for x in range(M.width)
                   if M.MAP[y][x] != 1]
    for i, (x, y) in enumerate(open_tegels[::7]):
        game.player.pos.x = (x + 0.5) * TILE_SIZE
        game.player.pos.y = (y + 0.5) * TILE_SIZE
        game.player.angle = i * 0.7
        menu.draw_minimap(game)

    onthouden, _muur, _vloer = menu._minimap_lagen(game.minimap)
    muur_gezien, vloer_gezien = None, None
    for y in range(M.height):
        for x in range(M.width):
            kleur = onthouden.get_at((x, y))
            if (x, y) in game.minimap.gezien:
                check_ui(kleur.a == 255,
                         f"tegel ({x},{y}) is onthouden maar staat niet op de kaart")
                if M.MAP[y][x] == 1:
                    muur_gezien = kleur
                else:
                    vloer_gezien = kleur
            else:
                check_ui(kleur.a == 0,
                         f"tegel ({x},{y}) is nooit gezien maar staat alsnog op de kaart")
    check_ui(muur_gezien is not None and vloer_gezien is not None,
             "sanity: er is geen muur én geen vloer onthouden, dus hierboven valt "
             "niets te toetsen")
    check_ui(muur_gezien != vloer_gezien,
             "muren en vloeren hebben dezelfde kleur, dus je ziet niet meer wat een "
             "muur is en wat een gang")

    # De stand overleeft een herstart, en een onzinwaarde geeft geen crash maar
    # terugval op uit.
    for stand in (MINIMAP_GEZIEN, MINIMAP_VOLLEDIG, MINIMAP_UIT):
        game.minimap_mode = stand
        game.save_settings()
        game.minimap_mode = -1
        game._load_settings()
        check_ui(game.minimap_mode == stand, f"stand {stand} overleeft save/load niet")
    with open(tmp_settings, "w") as f:
        json.dump({"minimap": "onzin"}, f)
    game._load_settings()
    check_ui(game.minimap_mode == MINIMAP_UIT,
             "een onbekende stand in settings.json geeft geen terugval op uit")
    os.unlink(tmp_settings)
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


# ── spatiebalk als schietknop ───────────────────────────────────
#
# Dit is een Game-test, dus die hoort in een eigen proces: game.py is één
# grote staat en een stukgelopen muziek- of menutoestand in het
# hoofdproces is niet te herstellen voor de tests die erna komen.
#
# Het lastige deel is dat spatie zich anders moet gedragen dan elk ander
# toetsenbordevent. pygame.key.set_repeat(400, 50) laat pygame het
# KEYDOWN-event herhalen zolang je de toets vasthoudt, dus een
# implementatie op dat event zou een semi-autowapen ongemerkt automatisch
# laten vuren. Vandaar de flankdetectie op de tussenstand van de vorige
# frame. Hier bootsen we dat na door get_pressed() te vervangen, en we
# doen alsof de herlaadtijd elke frame voorbij is - precies de situatie
# waarin het wapen wél kan vuren maar het toch niet mag doen.

SPATIE_DRIVER = r'''
import os, sys
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ.pop("GUNK_HEADLESS", None)
ROOT = sys.argv[1]
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.argv = ["game.py"]

import pygame
import game

fouten = []


def check(voorwaarde, bericht):
    if not voorwaarde:
        fouten.append(bericht)


g = game.Game()
gun = g.current_gun
check(gun.ammo_weight > 0,
      "testwapen heeft munitiegewicht nodig om schoten te tellen")

origineel_pressed = pygame.key.get_pressed
spatie = {"aan": False}


class _Toetsen:
    """Vervangt get_pressed(): alleen de spatieborpel is bekend."""

    def __getitem__(self, key):
        return spatie["aan"] if key == pygame.K_SPACE else False


def frame():
    """Eén frame laten lopen; geeft het aantal schoten terug."""
    oud_delta = g._ammo_delta
    gun.weapon_state = 0   # alsof de herlaadtijd net voorbij is
    g.handle_input()
    return (oud_delta - g._ammo_delta) // gun.ammo_weight


pygame.key.get_pressed = lambda: _Toetsen()
try:
    g.state = "game"
    g.escaped = False
    g.elevator_locked = False
    g.network_client = None
    g.global_ammo = 9999
    g._ammo_delta = 0

    # Semi-auto: precies één schot per druk. De tweede frame is de
    # proef op de som - het wapen kan weer vuren, maar de toets staat
    # nog steeds ingedrukt en dat mag niet als een nieuwe druk tellen.
    gun.auto = False
    spatie["aan"] = True
    check(frame() == 1, "spatie vuurt niet bij de eerste druk")
    check(frame() == 0,
          "semi-autowapen bleef vuren terwijl de spatie ingedrukt bleef")
    spatie["aan"] = False
    check(frame() == 0, "spatie vuurde terwijl hij losgelaten was")
    spatie["aan"] = True
    check(frame() == 1, "een nieuwe druk op spatie vuurt niet opnieuw")

    # Auto: zolang ingedrukt blijven vuren, loslaten stopt het.
    gun.auto = True
    check(frame() == 1, "autowapen vuurt niet met spatie ingedrukt")
    check(frame() == 1,
          "autowapen stopte terwijl de spatie ingedrukt bleef")
    spatie["aan"] = False
    check(frame() == 0, "autowapen bleef vuren na het loslaten")
finally:
    pygame.key.get_pressed = origineel_pressed

if fouten:
    for f in fouten:
        print("FOUT:", f)
    sys.exit(1)
print("SPATIE OK")
'''


@test
def spatiebalk_is_een_schietknop():
    """Spatie is een tweede schietknop naast de linkermuisknop."""
    path = os.path.join(TEMP_DIR, "gunk_spatie_driver.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(SPATIE_DRIVER)
    try:
        proc = subprocess.run([sys.executable, path, ROOT],
                              capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        check(False, "de spatiebalktest liep vast (time-out)")
        return
    if proc.returncode != 0:
        tail = (proc.stdout + "\n" + proc.stderr).splitlines()
        check(False, "de spatiebalktest gaf fouten:\n"
              + "\n".join(tail[-25:]))
        return
    check("SPATIE OK" in proc.stdout,
          f"geen 'SPATIE OK' in de uitvoer:\n{proc.stdout[-500:]}")


# ── zelfhosten: de lift en de gedeelde M ─────────────────────────
#
# Bij zelfhosten draait de server in een draadje in hetzelfde proces en
# deelt hij de module-singleton M. Dat werkt twee kanten op, en de tweede
# kant was nog niet dicht: _send_client_state stuurde M.map_level mee.
# De server zet die al in _setup_level, nog vóór de client de nieuwe state
# ontvangen heeft. Het pakket zei dus "level 1" met een positie die nog op
# level 0 lag, en process_input keurt een positie af als de getallen NIET
# kloppen - dus hier klopten ze wél en werd de oude liftpositie overgenomen.
# Die ligt op de nieuwe kaart midden in een muur.
#
# Alleen de host heeft dit, want alleen hij deelt die M. Een externe client
# heeft een eigen M, meldt nog level 0, en wordt netjes geweigerd.

ZELFHOST_DRIVER = r'''
import os, sys
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ.pop("GUNK_HEADLESS", None)
ROOT = sys.argv[1]
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.argv = ["game.py"]

import pygame
import game
from src.core.map_loader import M, will_collide
from src.core.vector import Vector
from src.network.server_game import ServerGame

fouten = []


def check(voorwaarde, bericht):
    if not voorwaarde:
        fouten.append(bericht)


class _Net:
    """Vangt het pakket dat de client naar de server zou sturen."""

    def __init__(self):
        self.pakket = None

    def send_input(self, pakket):
        self.pakket = pakket


# 1. De server draait de lift: level 0 -> 1. Dat zet M.map_level alvast
#    op 1, precies zoals bij zelfhosten gebeurt.
sg = ServerGame()
sg.register_player(0, "host")
sg.init_world()
oude_liftpositie = (sg.exit_pos.x, sg.exit_pos.y)
check(will_collide(oude_liftpositie[0], oude_liftpositie[1], 0) is False,
      "de liftpositie van level 0 hoort open te zijn, anders bewijst deze "
      "test niets")

sg.level = 1
sg._setup_level()
check(M.map_level == 1,
      f"de server zou M.map_level op 1 moeten zetten, staat op {M.map_level}")

# 2. De host-client: die heeft de nieuwe state nog niet gezien. Zijn positie
#    staat nog op de lift van level 0.
g = game.Game()
g.multiplayer = True
g.state = "game"
g._client_loaded_level = 0
g.player.pos = Vector(oude_liftpositie[0], oude_liftpositie[1])
g.network_client = _Net()
g._pos_seq = 1  # zodat de teller na ophogen deelbaar door 2 is

check(M.map_level == 1 and g._client_loaded_level == 0,
      "de proefopstelling klopt niet: gedeeld M is 1, de client is nog 0")

g._send_client_state()
check(g.network_client.pakket is not None,
      "_send_client_state stuurde niets")

pakket = g.network_client.pakket
check(pakket.get("level") == 0,
      f"het pakket meldt level {pakket.get('level')} terwijl de positie van "
      f"level 0 komt; de server zal het dan toch accepteren")

# 3. De server verwerkt precies dat pakket.
sg.process_input(0, pakket)

p = sg.players[0]["pos"]
check(will_collide(p.x, p.y, 0) is False,
      f"de host staat na de lift in een muur op ({p.x:.0f}, {p.y:.0f}) op "
      f"level {sg.level}")

# En de spawn die de server zelf had bedacht mag niet overschreven zijn door
# de stille positie van vóór de overgang.
spawn = [sg.players[0]["pos"].x, sg.players[0]["pos"].y]
check((spawn[0], spawn[1]) != oude_liftpositie,
      "de oude liftpositie is doorgelaten naar de nieuwe level")

if fouten:
    for f in fouten:
        print("FOUT:", f)
    sys.exit(1)
print("ZELFHOST OK")
'''


@test
def zelfhost_blijft_buiten_de_muur_na_de_lift():
    """De host deelt M met de server, dus zijn eigen level is leidend."""
    path = os.path.join(TEMP_DIR, "gunk_zelfhost_lift.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(ZELFHOST_DRIVER)
    try:
        proc = subprocess.run([sys.executable, path, ROOT],
                              capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        check(False, "de zelfhosttest liep vast (time-out)")
        return
    if proc.returncode != 0:
        tail = (proc.stdout + "\n" + proc.stderr).splitlines()
        check(False, "de zelfhosttest gaf fouten:\n"
              + "\n".join(tail[-25:]))
        return
    check("ZELFHOST OK" in proc.stdout,
          f"geen 'ZELFHOST OK' in de uitvoer:\n{proc.stdout[-500:]}")


# ── geen audio-uitgang ───────────────────────────────────────────
#
# Zonder geluidsuitgang weigert SDL de mixer, en pygame.init() vangt dat af
# zonder één woord. De eerste aanroep die het merkte was pygame.mixer.Sound()
# in de wapens, die bij het opstarten gemaakt wordt: een traceback meteen bij
# het openen, en alleen op machines zonder geluid. Vandaar een driver die dat
# nadoet, want dit is precies de situatie die niet op de machine van de
# ontwikkelaar voorkomt.

AUDIO_DRIVER = r'''
import os, sys
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "bestaat_niet"   # een machine zonder geluidsuitgang
os.environ.pop("GUNK_HEADLESS", None)
ROOT = sys.argv[1]
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.argv = ["game.py"]

import pygame
import game
from src.core import audio

fouten = []


def check(voorwaarde, bericht):
    if not voorwaarde:
        fouten.append(bericht)


g = game.Game()

check(audio.status == "dummy",
      "verwachtte de stille mixer als terugval, kreeg "
      f"{audio.status!r}: {audio.detail}")
check(pygame.mixer.get_init() is not None,
      "de mixer is niet open, dus elk Sound-object zou alsnog crashen")
for naam, gun in (("pistol", g.pistol), ("minigun", g.minigun),
                  ("rifle", g.rifle)):
    check(isinstance(gun.shoot_sound, pygame.mixer.Sound),
          f"{naam} kreeg geen echt Sound-object: "
          f"{type(gun.shoot_sound).__name__}")
check(sorted(g.sounds) == ["ammo", "damage", "drink", "elev_ding", "key",
                           "victory"],
      f"niet alle geluiden zijn geladen: {sorted(g.sounds)}")
check(isinstance(g.main_music_loop, pygame.mixer.Sound),
      "de muziekloop is niet geladen")

# Alles wat het spel tijdens het spelen aanraakt moet het blijven doen.
g.pistol.shoot_sound.set_volume(0.3)
g.pistol.shoot_sound.play()
g.sounds["damage"].play()
g.main_music_loop.play(loops=-1)
audio.stop_all()
audio.pause()
audio.unpause()

if fouten:
    for f in fouten:
        print("FOUT:", f)
    sys.exit(1)
print("GEEN AUDIO OK")
'''


@test
def spel_start_zonder_audio_uitgang():
    """Een machine zonder geluidsuitgang start het spel gewoon op."""
    path = os.path.join(TEMP_DIR, "gunk_geen_audio_driver.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(AUDIO_DRIVER)
    try:
        proc = subprocess.run([sys.executable, path, ROOT],
                              capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        check(False, "de test zonder geluid liep vast (time-out)")
        return
    if proc.returncode != 0:
        tail = (proc.stdout + "\n" + proc.stderr).splitlines()
        check(False, "de test zonder geluid gaf fouten:\n"
              + "\n".join(tail[-25:]))
        return
    check("GEEN AUDIO OK" in proc.stdout,
          f"geen 'GEEN AUDIO OK' in de uitvoer:\n{proc.stdout[-500:]}")


@test
def stille_sound_doet_wat_een_sound_doet():
    """SilentSound heeft alles wat het spel op een Sound aanroept."""
    from src.core.audio import SilentSound
    s = SilentSound()
    # play() returnt None omdat game.py dat kanaal bewaart en er get_busy()
    # aan vraagt; een kanaal dat niet bestaat zou dat laten crashen.
    check(s.play(loops=-1) is None,
          "play() returnt geen None")
    s.stop()
    s.pause()
    s.unpause()
    s.fadeout(100)
    s.set_volume(0.5)
    check(s.get_volume() == 0.0, "stil geluid meldt volume")
    check(s.get_length() == 0.0, "stil geluid meldt lengte")
    check(s.get_busy() is False, "stil geluid meldt dat er iets speelt")


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
