"""
run_server.py - Standalone headless server
Start met: python run_server.py [--port POORT]
Alle clients connecten via JOIN met dit IP + poort.
"""
import os

os.environ["GUNK_HEADLESS"] = "1"

import sys
import signal
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

    def shutdown(sig, frame):
        print("\n[SERVER] Stoppen...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            signal.pause()
    except AttributeError:
        import time
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
