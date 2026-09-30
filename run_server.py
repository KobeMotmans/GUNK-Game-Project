"""
run_server.py - Standalone headless server
Start met: python run_server.py [--port POORT] [--max-players N]
                                 [--no-port-map] [--gateway IP]
                                 [--public-ip IP]
Alle clients connecten via JOIN met dit IP + poort.

De server probeert bij het starten zelf of hij vanaf internet bereikbaar is:
via NAT-PMP wordt de poort bij de router aangevraagd, via STUN wordt het
publieke adres opgezocht. Lukt dat niet, dan staat de poort in de uitvoer
en kun je hem handmatig in je router openzetten.
"""
import os

os.environ["GUNK_HEADLESS"] = "1"

import sys
import signal
import threading
from src.network.network import ServerIO
from src.network.port_map import discover, format_banner
from src.network.discovery import DiscoveryResponder
from src.core.config import DEFAULT_PORT, MAX_PLAYERS


def _arg_int(argv, flag, default):
    """Leest `flag <getal>` uit argv, met fallback op default."""
    if flag not in argv:
        return default
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        return default
    try:
        return int(argv[idx + 1])
    except ValueError:
        return default


def _arg_str(argv, flag):
    """Leest `flag <tekst>` uit argv, of None als de flag er niet staat."""
    if flag not in argv:
        return None
    idx = argv.index(flag)
    return argv[idx + 1] if idx + 1 < len(argv) else None


def main():
    port = _arg_int(sys.argv, "--port", DEFAULT_PORT)
    max_players = max(1, min(_arg_int(sys.argv, "--max-players", MAX_PLAYERS), 16))
    want_mapping = "--no-port-map" not in sys.argv
    gateway = _arg_str(sys.argv, "--gateway")
    public_ip = _arg_str(sys.argv, "--public-ip")

    server = ServerIO(port, max_players=max_players)
    server.start()
    print(f"[SERVER] Gestart op poort {port}")
    print(f"[SERVER] Maximaal {max_players} spelers")
    for line in format_banner(port, discover(
            port, gateway=gateway, want_mapping=want_mapping,
            public_ip=public_ip)):
        print(line)

    # Meld jezelf op het eigen netwerk, zodat spelers in de buurt je in
    # hun multiplayer-menu vinden zonder het IP te hoeven typen. Dit is
    # een extraatje: als broadcast niet doorkomt (campus-wifi, docker,
    # verschillende VLAN's) doet het verder geen kwaad.
    responder = DiscoveryResponder(
        port, get_info=lambda: {"players": len(server.get_lobby_players()),
                                "max_players": max_players, "is_host": True})
    responder.start()

    print("[SERVER] Druk Ctrl+C om te stoppen")

    stop_event = threading.Event()

    def shutdown(sig, frame):
        print("\n[SERVER] Stoppen...")
        responder.stop()
        server.stop()
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        stop_event.wait()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
