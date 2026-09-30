"""
port_map.py - Het internetadres van de server achterhalen

Zonder port forwarding ziet niemand je server, ook niet met het juiste IP.
Dit module vraagt de router zelf om de poort open te zetten (NAT-PMP,
RFC 6886) en vraagt een publieke STUN-server wat je publieke adres is
(RFC 5389). Allebei zonder externe bibliotheken, alleen de standaardlib.

Wie geen NAT-PMP heeft (de meeste thuisrouters wel wel) valt terug op
STUN: dat opent niets, maar het zegt wel welk adres de speler moet intypen.

    python run_server.py                    # doet alles wat het kan
    python run_server.py --no-port-map      # geen routerpoging, wel STUN
    python run_server.py --gateway 192.168.1.1
    python run_server.py --public-ip 82.1.2.3   # overslaan van het zoeken
"""

import csv
import io
import os
import random
import socket
import struct
import subprocess
import threading
import time

from ..core.logger import log as _log

# RFC 6886/5389 magic cookie. Ook de XOR-sleutel voor het publieke adres.
MAGIC_COOKIE = 0x2112A442

NATPMP_PORT = 5351
NATPMP_VERSION = 0

STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
]

# Uitkomsten uit RFC 6886 paragraaf 3.5.
NATPMP_OK = 0
NATPMP_UNSUPPORTED_VERSION = 1
NATPMP_NOT_AUTHORIZED = 2
NATPMP_NETWORK_FAILURE = 3
NATPMP_OUT_OF_RESOURCES = 4
NATPMP_UNSUPPORTED_OPCODE = 5

RESULT_TEXT = {
    NATPMP_OK: "ok",
    NATPMP_UNSUPPORTED_VERSION: "router spreekt geen NAT-PMP",
    NATPMP_NOT_AUTHORIZED: "router weigert de aanvraag (STAION poort)",
    NATPMP_NETWORK_FAILURE: "router gaf een netwerkfout",
    NATPMP_OUT_OF_RESOURCES: "router heeft geen poort vrij",
    NATPMP_UNSUPPORTED_OPCODE: "router kent deze functie niet",
}


# ── pure parsers (worden door de tests rechtstreeks gevoed) ────

def _parse_ip_prefix_table(text):
    """Lees IPAddress/PrefixLength uit de CSV van Get-NetIPAddress.

    Geeft {ip: prefix}. Bewust een zuivere functie: de tests voeden hem
    een vast stukje Windows-uitvoer en een lege string, zonder netwerk.
    """
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        ip = (row.get("IPAddress") or "").strip()
        prefix = _as_int(row.get("PrefixLength"), -1)
        if ip and 0 <= prefix <= 32:
            out[ip] = prefix
    return out


def _parse_ip_addr_output(text):
    """Lees de IPv4-adressen met prefixlengte uit `ip addr show`.

    Zowel `ip -o addr` (met regelnummers) als `ip addr` (zonder) wordt
    ondersteund: we zoeken het woord 'inet' en pakken het token ernaast,
    in plaats van een vaste kolom te nemen. 'inet6' wordt niet meegenomen.
    """
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if "inet" not in parts:
            continue
        idx = parts.index("inet")
        if idx + 1 >= len(parts):
            continue
        addr = parts[idx + 1]
        if "/" not in addr:
            continue
        ip, _, bits = addr.partition("/")
        if bits.isdigit() and 0 <= int(bits) <= 32:
            out[ip] = int(bits)
    return out


def parse_natpmp_response(data):
    """Lees een NAT-PMP-antwoord uit. Geeft None bij een korte of rare reply."""
    # De response-header is 7 bytes: version(1), opcode(1), result(1) en
    # seconden-sinds-boot(4). Daarna volgt per opcode een eigen staart.
    if len(data) < 7:
        return None
    version, op_len, result = struct.unpack("!BBB", data[:3])
    epoch = struct.unpack("!I", data[3:7])[0]
    out = {
        "version": version,
        "opcode": op_len & 0x7F,
        "result": result,
        "epoch": epoch,
    }
    # De staart is niet apart gecodeerd: de opcode bepaalt hoeveel bytes er
    # volgen (0 -> intern IP + extern IP, 1/2 -> poorten + levensduur).
    body = data[7:]
    if out["opcode"] == 0 and len(body) >= 8:
        # opcode 0: externe adres opvragen -> intern IP + extern IP
        out["internal_ip"] = socket.inet_ntoa(body[0:4])
        out["external_ip"] = socket.inet_ntoa(body[4:8])
        out["lifetime"] = 0
    elif out["opcode"] in (1, 2) and len(body) >= 8:
        # opcode 1/2: poortmapping
        (internal_port, external_port,
         lifetime) = struct.unpack("!HHI", body[:8])
        out["internal_port"] = internal_port
        out["external_port"] = external_port
        out["lifetime"] = lifetime
    return out


def parse_stun_response(data, transaction_id=None):
    """Haal het publieke adres uit een STUN Binding-success-antwoord."""
    if len(data) < 20:
        return None
    msg_type, msg_len, cookie = struct.unpack("!HHI", data[:8])
    if cookie != MAGIC_COOKIE:
        return None
    if msg_type != 0x0101:  # Binding Success Response
        return None
    if transaction_id is not None and data[8:20] != transaction_id:
        return None  # antwoord op een ander verzoek

    pos = 20
    end = min(len(data), 20 + msg_len)
    while pos + 4 <= end:
        attr_type, attr_len = struct.unpack("!HH", data[pos:pos + 4])
        value = data[pos + 4:pos + 4 + attr_len]
        # attributen worden aangevuld tot een 4-byte grens
        pos += 4 + attr_len + ((-attr_len) % 4)
        if attr_type == 0x0020 and len(value) >= 8:  # XOR-MAPPED-ADDRESS
            # reserved(1) + family(1) + x-port(2) + x-address(4) = 8 bytes
            family = value[1]
            if family != 0x01:  # alleen IPv4
                return None
            port = struct.unpack("!H", value[2:4])[0] ^ (MAGIC_COOKIE >> 16)
            addr = bytes(b ^ c for b, c in
                         zip(value[4:8], struct.pack("!I", MAGIC_COOKIE)))
            return {"ip": socket.inet_ntoa(addr), "port": port}
        if attr_type == 0x0001 and len(value) >= 8:  # MAPPED-ADDRESS
            # dezelfde opbouw, maar zonder de XOR-laag
            if value[1] != 0x01:
                return None
            return {"ip": socket.inet_ntoa(value[4:8]),
                    "port": struct.unpack("!H", value[2:4])[0]}
    return None


def _lookup_stun_host(host):
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


# ── netwerkdetectie ───────────────────────────────────────────

def local_ipv4():
    """Het LAN-adres van deze machine, zonder iets te versturen."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.3)
        # 192.0.2.1 is TEST-NET-1: er vertrekt niets, alleen de route wordt
        # bepaald zodat getsockname() het juiste adapteradres teruggeeft.
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _windows_prefix_table():
    """Vraag Windows welke prefixlengte elk eigen adres heeft."""
    command = ("Get-NetIPAddress -AddressFamily IPv4 "
               "| Select-Object IPAddress,PrefixLength "
               "| ConvertTo-Csv -NoTypeInformation")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0 or not out.stdout.strip():
        return {}
    return _parse_ip_prefix_table(out.stdout)


def _linux_prefix_table():
    """Vraag `ip` welke prefixlengte elk eigen adres heeft."""
    try:
        out = subprocess.run(["ip", "-o", "-4", "addr", "show"],
                            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0 or not out.stdout.strip():
        return {}
    return _parse_ip_addr_output(out.stdout)


def prefix_length_table():
    """De IPv4-adressen van deze machine, met hun prefixlengte."""
    if os.name == "nt":
        table = _windows_prefix_table()
    else:
        table = _linux_prefix_table()
    if not table:
        _log("[netwerk] kon de prefixlengte niet opvragen; /24 aangenomen")
    return table


def local_prefix_length(ip=None, default=24):
    """De prefixlengte van het subnet waar `ip` op zit.

    Standaard /24, want dat klopt voor de meeste thuisnetten en is een
    veilige gok: een verkeerd subnet-broadcastadres wordt door het net
    sowieso genegeerd, en 255.255.255.255 blijft altijd over. Maar op een
    campusnetwerk met een /18 levert die gok 10.240.2.255 op terwijl
    10.240.63.255 het juiste adres is, dus we vragen het gewoon even na.
    """
    if not ip:
        ip = local_ipv4()
    if not ip:
        return default
    return prefix_length_table().get(ip, default)


def _looks_like_gateway(hop):
    """Kan dit adres een router zijn, of is het iets dat we willen overslaan?

    Op een laptop met Tailscale of een VPN staat er vaak een tweede
    'standaardroute' bij die naar een geheel eigen netwerk wijst. Vraag je
    daar NAT-PMP aan, dan krijg je nooit antwoord.
    """
    parts = hop.split(".") if isinstance(hop, str) else []
    if len(parts) != 4:
        return False
    try:
        first, second = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if any(not 0 <= int(p) <= 255 for p in parts):
        return False
    if first == 0 or first >= 224:      # 'dit netwerk' en multicast
        return False
    if first == 127:                    # loopback
        return False
    if first == 169 and second == 254:  # link-local (APIPA, Tailscale)
        return False
    if first == 100 and 64 <= second <= 127:  # CGNAT, waar Tailscale op zit
        return False
    return True


def _as_int(value, fallback=9999):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _pick_gateway(routes):
    """Kies de gateway uit de standaardroutes, met de laagste RouteMetric.

    `routes` is een lijst dicts met de sleutels NextHop en RouteMetric, zoals
    Get-NetRoute op Windows teruggeeft. Bewust pure functie zodat de tests hem
    zonder netwerk kunnen voeden.
    """
    usable = []
    for route in routes:
        hop = (route.get("NextHop") or "").strip()
        if not _looks_like_gateway(hop):
            continue
        usable.append((_as_int(route.get("RouteMetric")), hop))
    if not usable:
        return None
    usable.sort()
    return usable[0][1]


def _parse_route_table(text):
    """Lees de CSV-uitvoer van Get-NetRoute in een lijst dicts."""
    return [{"NextHop": row.get("NextHop", ""),
             "RouteMetric": row.get("RouteMetric", ""),
             "InterfaceAlias": row.get("InterfaceAlias", "")}
            for row in csv.DictReader(io.StringIO(text))]


def _windows_default_gateway():
    """Vraag Windows wat de echte gateway is.

    De x.x.x.1-aanname klopt in de meeste thuissituaties, maar een
    campusnetwerk zet zijn gateway vaak ergens anders: hier draaide het op
    een /18 met gateway 10.240.63.254, terwijl de gok 10.240.2.1 was.
    """
    command = ("Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' "
               "| Select-Object InterfaceAlias,NextHop,RouteMetric "
               "| ConvertTo-Csv -NoTypeInformation")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return _pick_gateway(_parse_route_table(out.stdout))


def _guess_gateway():
    """Terugval: neem x.x.x.1 van het eigen subnet."""
    lan_ip = local_ipv4()
    if not lan_ip:
        return None
    parts = lan_ip.split(".")
    if len(parts) != 4:
        return None
    candidate = ".".join(parts[:3] + ["1"])
    return candidate if _looks_like_gateway(candidate) else None


def default_gateway():
    """Het adres van de router op het standaardpad, of None."""
    if os.name == "nt":
        found = _windows_default_gateway()
        if found:
            return found
    return _guess_gateway()


def find_gateway(explicit=None):
    """De (gateway, poort) om NAT-PMP mee te spreken, of None.

    Merk op dat we hier niet kunnen 'pingen': een UDP-connect stuurt niets,
    dus of er iemand op poort 5351 luistert blijkt pas uit het antwoord op de
    NAT-PMP-aanvraag zelf.
    """
    if explicit:
        return (explicit, NATPMP_PORT)
    gw = default_gateway()
    return (gw, NATPMP_PORT) if gw else None


def _natpmp_request(gateway, payload, tries=4, timeout=0.5):
    """Stuur één NAT-PMP-verzoek en wacht op het antwoord met backoff."""
    addr = (gateway[0], gateway[1])
    deadline_per_try = timeout
    for attempt in range(tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(deadline_per_try)
                s.sendto(payload, addr)
                data, _ = s.recvfrom(64)
        except socket.timeout:
            deadline_per_try = min(deadline_per_try * 2, 3.0)
            continue
        except OSError as e:
            _log(f"[NAT-PMP] socketfout: {e}")
            return None
        parsed = parse_natpmp_response(data)
        if parsed is None:
            continue
        return parsed
    return None


def natpmp_external_address(gateway, tries=3, timeout=0.35):
    """Vraag de router wat ons publieke adres is (opcode 0)."""
    payload = struct.pack("!BBH", 0, NATPMP_VERSION, 0)
    reply = _natpmp_request(gateway, payload, tries=tries, timeout=timeout)
    if not reply:
        return None
    if reply["result"] != NATPMP_OK:
        return {"error": RESULT_TEXT.get(reply["result"], "onbekende fout")}
    return {"ip": reply["external_ip"], "internal_ip": reply["internal_ip"]}


def natpmp_map_udp(gateway, internal_port, lifetime=3600, tries=3, timeout=0.35):
    """Vraag de router om internal_port naar buiten toe open te zetten.

    Een lifetime van 0 trekt de mapping juist in: handig bij het afsluiten,
    zodat de poort niet urenlang voor niets open blijft staan.
    """
    payload = struct.pack("!BBHHI", 1, NATPMP_VERSION,
                          internal_port, internal_port, lifetime)
    reply = _natpmp_request(gateway, payload, tries=tries, timeout=timeout)
    if not reply:
        return None
    if reply["result"] != NATPMP_OK:
        return {"error": RESULT_TEXT.get(reply["result"], "onbekende fout")}
    return {
        "external_ip": None,       # opcode 1 geeft geen adres terug
        "external_port": reply["external_port"],
        "lifetime": reply["lifetime"],
    }


class PortMappingKeeper(threading.Thread):
    """Houdt een NAT-PMP-poortmapping open door hem steeds te verlengen.

    Zonder dit verliest een thuisserver na een uur plotseling alle spelers:
    de router laat de mapping vervallen en de server merkt daar niets van,
    want er is geen foutmelding. We verlengen daarom telkens als de helft
    van de resterende levensduur verstreken is.
    """

    def __init__(self, gateway, internal_port, lifetime=7200, on_change=None):
        super().__init__(daemon=True)
        self.gateway = gateway
        self.internal_port = internal_port
        self.lifetime = lifetime
        self.on_change = on_change
        self.external_port = None
        self.mapped = False
        self._stop = threading.Event()

    def renew(self):
        """Vraag de mapping opnieuw aan. Geeft de externe poort, of None."""
        reply = natpmp_map_udp(self.gateway, self.internal_port, self.lifetime)
        if not reply or reply.get("error"):
            self.mapped = False
            return None
        self.external_port = reply["external_port"]
        self.mapped = True
        # Noem de levensduur die de router gaf, niet die we vroegen: sommige
        # routers kappen hem bewust af.
        self.lifetime = max(60, reply["lifetime"] or self.lifetime)
        return self.external_port

    def release(self):
        """Trek de mapping in zodat de poort niet open blijft staan."""
        try:
            natpmp_map_udp(self.gateway, self.internal_port, 0,
                           tries=1, timeout=0.3)
        except Exception:      # bij het afsluiten mag niets meer misgaan
            pass
        self.mapped = False

    def run(self):
        while True:
            # Wacht eerst: direct na het opstarten is de mapping nog vers.
            if self._stop.wait(max(30.0, self.lifetime / 2.0)):
                return
            if self.renew() is None:
                # De mapping is kwijt of de router reageert niet meer. Elke
                # dertig seconden opnieuw proberen is goedkoop en herstelt
                # het zodra de router weer bereikbaar is.
                self.lifetime = 60
                _log("[NAT-PMP] mapping kwijt; opnieuw aanvragen")
                if self.on_change:
                    self.on_change(False, None)
            else:
                _log(f"[NAT-PMP] mapping verlengd, poort {self.external_port}")
                if self.on_change:
                    self.on_change(True, self.external_port)

    def stop(self):
        self._stop.set()


def stun_external_address(servers=None, timeout=2.0, tries=2):
    """Vraag een STUN-server wat ons publieke adres lijkt (geen mapping)."""
    for host, port in (servers or STUN_SERVERS):
        ip = _lookup_stun_host(host)
        if not ip:
            continue
        for _ in range(tries):
            txn = bytes(random.randrange(256) for _ in range(12))
            request = struct.pack("!HHI", 0x0001, 0, MAGIC_COOKIE) + txn
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.settimeout(timeout)
                    s.sendto(request, (ip, port))
                    data, _ = s.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError as e:
                _log(f"[STUN] socketfout via {host}: {e}")
                break
            result = parse_stun_response(data, txn)
            if result:
                return {"ip": result["ip"], "server": f"{host}:{port}"}
    return None


# ── samenvatten voor de serverstart ────────────────────────────

def discover(port, gateway=None, want_mapping=True, public_ip=None,
             stun=True):
    """Zoal het speelbare adres bij elkaar.

    Geeft een dict met:
        lan_ip      het adres op je eigen netwerk
        public_ip   het adres waarop je vanaf buiten bereikbaar bent
        mapped      of de poort door de router openstaat
        notes       regels voor de serverconsole
    """
    lan_ip = local_ipv4()
    out = {
        "lan_ip": lan_ip,
        "public_ip": None,
        "mapped": False,
        "method": None,
        "external_port": port,
        "notes": [],
    }

    if public_ip:
        out["public_ip"] = public_ip
        out["notes"].append(f"publiek adres opgegeven: {public_ip}:{port}")
        return out

    gw = find_gateway(gateway)
    if want_mapping and gw:
        addr = natpmp_external_address(gw)
        if addr and addr.get("ip"):
            out["public_ip"] = addr["ip"]
            mapped = natpmp_map_udp(gw, port)
            if mapped and not mapped.get("error"):
                out["mapped"] = True
                out["method"] = "NAT-PMP"
                out["external_port"] = mapped["external_port"]
                out["notes"].append(
                    f"poort {port} -> {mapped['external_port']} via NAT-PMP "
                    f"({mapped['lifetime']} s geldig)")
            elif mapped and mapped.get("error"):
                out["notes"].append(f"poortmapping mislukt: {mapped['error']}")
            else:
                out["notes"].append("router gaf geen antwoord op de mapping")
        elif addr and addr.get("error"):
            out["notes"].append(f"externe adres mislukt: {addr['error']}")
        else:
            out["notes"].append(
                "geen antwoord van de router op "
                f"{gw[0]}:{gw[1]} (NAT-PMP)")
    elif want_mapping:
        out["notes"].append("geen gateway gevonden, mapping overgeslagen")

    if not out["public_ip"] and stun:
        found = stun_external_address()
        if found:
            out["public_ip"] = found["ip"]
            out["method"] = out["method"] or "STUN"
            out["notes"].append(
                f"publiek adres {found['ip']} via STUN ({found['server']})")
        else:
            out["notes"].append("geen STUN-server bereikbaar")

    if out["public_ip"] and not out["mapped"]:
        out["notes"].append(
            f"de poort is NIET automatisch opengezet: zet {port}/UDP "
            "handmatig open in je router, anders komt niemand binnen")
    return out


def format_banner(port, info):
    """De regels die run_server.py onder de banner afdrukt."""
    lines = []
    if info.get("lan_ip"):
        lines.append(f"[SERVER] LAN       : {info['lan_ip']}:{port}")
    else:
        lines.append("[SERVER] LAN       : onbekend (geen netwerkadapter?)")
    if info.get("public_ip"):
        ext_port = info.get("external_port", port)
        target = (f"{info['public_ip']}:{ext_port}"
                  if ext_port != port else info["public_ip"])
        label = "via NAT-PMP" if info.get("mapped") else (
            "via STUN, poort nog NIET open")
        lines.append(f"[SERVER] Internet : {target}   ({label})")
    else:
        lines.append("[SERVER] Internet : onbekend (geen NAT-PMP en geen STUN)")
    for note in info.get("notes", []):
        lines.append(f"[SERVER]   - {note}")
    if info.get("public_ip"):
        lines.append(
            f"[SERVER] Geef spelers dit adres en laat hen poort "
            f"{info.get('external_port', port)} invullen.")
    return lines
