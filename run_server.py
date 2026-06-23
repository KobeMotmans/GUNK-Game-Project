"""
run_server.py - Standalone headless server
Start met: python run_server.py [--port POORT]
Alle clients connecten via JOIN met dit IP + poort.
"""
import os

os.environ["GUNK_HEADLESS"] = "1"

import sys
import signal
import threading
from src.network.network import ServerIO
from src.core.config import DEFAULT_PORT


def main():
    port = DEFAULT_PORT
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            try:
                port = int(sys.argv[idx + 1])
            except ValueError:
                pass

    server = ServerIO(port, max_players=4)
    server.start()
    print(f"[SERVER] Gestart op poort {port}")
    print(f"[SERVER] Druk Ctrl+C om te stoppen")

    stop_event = threading.Event()

    def shutdown(sig, frame):
        print("\n[SERVER] Stoppen...")
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
