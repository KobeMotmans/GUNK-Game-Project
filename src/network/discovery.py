"""
discovery.py - Servers in je eigen netwerk opzoeken, zoals Minecraft

Een speler die op LAN speelt moet normaal het IP-adres van de host intypen.
Dat is omslachtig en de host weet vaak niet eens wat zijn eigen adres is.
Daarom zendt een draaiende server elke twee seconden een korte aankondiging
op de LAN. Elk spel dat meeluistert ziet de server daardoor vanzelf in een
lijstje staan.

Belangrijk om te weten: dit werkt met UDP-broadcast en heeft **niets** met
NAT te maken. Broadcast verlaat je netwerk nooit, dus een router of
firewall thuis speelt er geen rol in. Het nadeel is precies de spiegelbeeld-
kant: omdat broadcast nergens doorheen gaat, werkt het alleen binnen één
broadcast-domein. Twee laptops achter dezelfde thuisrouter: prima. Twee
laptops op een zakelijk of campus-WLAN: meestal niet, want die schermen
client-naar-client verkeer bewust uit.

De aankondiging is bewust één klein datagram (~75 bytes) met een vast
formaat, zodat een speler zonder discovery-code hem toch kan lezen.
"""

import socket
import struct
import threading
import time

from ..core.logger import log as _log

DISCOVERY_PORT = 4445
DISCOVERY_INTERVAL = 2.0      # hoe vaak een server zich meldt
DISCOVERY_TIMEOUT = 8.0       # na zoveel seconden stilte valt een server weg
DISCOVERY_TIMEOUT_SLOW = 5.0  # enige reactietijd die we bij het zoeken geven

MAGIC = b"GUNK"
VERSION = 1
MAX_MOTD = 64

# magic(4) + versie(1) + poort(2) + spelers(1) + max(1) + host(1) + motd
_HEADER = struct.Struct("!4sBHHBBB")
MAX_PACKET = _HEADER.size + MAX_MOTD


# ── het formaat (pure functies, dus rechtstreeks te testen) ────

def encode_announcement(port, players=0, max_players=0, is_host=True, motd=""):
    """Bouw het aankondigings-datagram."""
    text = motd.encode("utf-8", "replace")[:MAX_MOTD]
    return _HEADER.pack(MAGIC, VERSION, port, players, max_players,
                        1 if is_host else 0, len(text)) + text


def decode_announcement(data):
    """Lees een aankondiging uit. Geeft None bij iets dat ons niet toe hoort.

    Een vreemd programma op je netwerk kan op dezelfde poort meesturen, dus
    we controleren het magisch getal en de versie en negeren de rest.
    """
    if not data or len(data) > MAX_PACKET + 64:
        return None
    if len(data) < _HEADER.size:
        return None
    magic, version, port, players, max_players, host, motd_len = \
        _HEADER.unpack(data[:_HEADER.size])
    if magic != MAGIC or version != VERSION:
        return None
    text = data[_HEADER.size:_HEADER.size + motd_len]
    try:
        motd = text.decode("utf-8")
    except UnicodeDecodeError:
        motd = text.decode("utf-8", "replace")
    return {
        "port": port,
        "players": players,
        "max_players": max_players,
        "is_host": bool(host),
        "motd": motd,
    }


def broadcast_targets(local_ip, prefix=24):
    """De adressen waarnaar een aankondiging verstuurd kan worden.

    Twee bestemmingen, want netwerken verschillen:

      * 255.255.255.255 is de beperkte broadcast en komt op élke interface
        binnen. Maar sommige netwerken (en sommige VPN's) filteren die er uit.
      * het subnet-broadcast-adres is gerichter. Daarvoor is de prefix
        nodig, en die levert Python niet; vraag dus local_prefix_length()
        en geef die hier door. Zonder dat valt de gok terug op /24, wat
        voor de meeste thuisnetten klopt maar op een campusnetwerk met
        een /18 een adres oplevert dat daar niet bestaat.
    """
    targets = ["255.255.255.255"]
    parts = local_ip.split(".")
    if len(parts) == 4 and prefix >= 0 and prefix <= 30:
        try:
            octets = [int(p) for p in parts]
        except ValueError:
            return targets
        host_bits = 32 - prefix
        # Het netwerk = het eigen adres met het hostgedeelte op nul; het
        # broadcast-adres is dat met het hostgedeelte op enen.
        address = (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]
        mask = (0xFFFFFFFF << host_bits) & 0xFFFFFFFF
        network = address & mask
        broadcast = network | (0xFFFFFFFF ^ mask)
        targets.append(socket.inet_ntoa(struct.pack("!I", broadcast)))
    return targets


def is_own_address(ip):
    """True als dit IP-adres bij deze machine hoort (of niet routeerbaar is).

    Zonder deze check zou een server zichzelf in de lijst zien staan.
    """
    if not ip:
        return True
    parts = ip.split(".")
    if len(parts) != 4:
        return True
    try:
        first = int(parts[0])
    except ValueError:
        return True
    return first == 127 or first == 0


# ── de serverkant ──────────────────────────────────────────────

class DiscoveryResponder(threading.Thread):
    """Zendt periodiek een aankondiging van de draaiende server."""

    def __init__(self, port, get_info=None, interval=DISCOVERY_INTERVAL):
        """
        `get_info` levert bij elke ronde {"players": n, "max_players": m,
        "is_host": b}. Zo hoeft de aanroeper geen toestand bij te houden.
        """
        super().__init__(daemon=True)
        self.port = port
        self.get_info = get_info or (lambda: {})
        self.interval = interval
        # Niet `_stop` heten: threading.Thread heeft zelf een interne
        # methode `_stop()` en die zou je dan overschrijven.
        self._stop_event = threading.Event()
        self._socket = None

    def run(self):
        from .port_map import local_ipv4, local_prefix_length
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.5)
            self._socket = sock
        except OSError as e:
            _log(f"[LAN] kon niet zenden: {e}")
            return
        # Het subnet verandert niet zolang je op hetzelfde netwerk zit, en
        # de prefixlengte opvragen kost een shellsessie. Daarom per IP
        # onthouden in plaats van elke ronde opnieuw te vragen.
        prefix_for_ip = None
        prefix = 24
        while not self._stop_event.is_set():
            lan_ip = local_ipv4()
            if lan_ip:
                if lan_ip != prefix_for_ip:
                    prefix_for_ip = lan_ip
                    prefix = local_prefix_length(lan_ip)
                info = self.get_info() or {}
                data = encode_announcement(
                    self.port,
                    players=info.get("players", 0),
                    max_players=info.get("max_players", 0),
                    is_host=info.get("is_host", True))
                for target in broadcast_targets(lan_ip, prefix):
                    try:
                        sock.sendto(data, (target, DISCOVERY_PORT))
                    except OSError:
                        # Broadcast is op sommige netwerken verboden; dan
                        # horen anderen ons simpelweg niet.
                        pass
            self._stop_event.wait(self.interval)

    def stop(self):
        self._stop_event.set()


# ── de klantkant ───────────────────────────────────────────────

class DiscoveryListener(threading.Thread):
    """Luistert naar aankondigingen en houdt een lijstje servers bij."""

    def __init__(self, interval=DISCOVERY_TIMEOUT_SLOW, timeout=DISCOVERY_TIMEOUT):
        super().__init__(daemon=True)
        self.interval = interval
        self.timeout = timeout
        self.servers = {}          # "ip:poort" -> {..., "seen": monotonic}
        self._lock = threading.Lock()
        # Niet `_stop` heten: threading.Thread heeft zelf een interne
        # methode `_stop()` en die zou je dan overschrijven.
        self._stop_event = threading.Event()
        self._socket = None
        self.listening = False

    def run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # SO_REUSEADDR zodat een tweede GUNK op dezelfde pc niet struikelt
            # en een herstart meteen weer kan luisteren.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(0.5)
            self._socket = sock
            self.listening = True
        except OSError as e:
            _log(f"[LAN] kon niet luisteren op poort {DISCOVERY_PORT}: {e}")
            return
        while not self._stop_event.is_set():
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                self._prune()
                continue
            except OSError:
                return
            self._on_packet(data, addr)
        self.listening = False

    def _on_packet(self, data, addr):
        """Verwerk één ontvangen datagram.

        Bewust losgehaald van de lus eromheen: zo is het gedrag van de
        luisteraar te testen zonder een echte socket te openen.
        """
        packet = decode_announcement(data)
        if packet is None:
            return
        ip = addr[0]
        if is_own_address(ip):
            return
        with self._lock:
            self.servers[f"{ip}:{packet['port']}"] = {
                "ip": ip,
                "port": packet["port"],
                "players": packet["players"],
                "max_players": packet["max_players"],
                "is_host": packet["is_host"],
                "motd": packet["motd"],
                "seen": time.monotonic(),
            }

    def _prune(self):
        """Haal servers weg die al een tijdje stil zijn."""
        cutoff = time.monotonic() - self.timeout
        with self._lock:
            for key in [k for k, v in self.servers.items() if v["seen"] < cutoff]:
                del self.servers[key]

    def list_servers(self):
        """De gevonden servers, volledigste eerst."""
        self._prune()
        with self._lock:
            servers = [dict(v) for v in self.servers.values()]
        servers.sort(key=lambda s: (not s["is_host"], s["max_players"] or 99,
                                     s["ip"], s["port"]))
        return servers

    def stop(self):
        self._stop_event.set()
        sock = self._socket
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        self.listening = False
