import time
import os
import sys


_LOG_PATH = None


def log_path():
    global _LOG_PATH
    if _LOG_PATH is None:
        if getattr(sys, 'frozen', False):
            d = os.path.dirname(sys.executable)
        else:
            d = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _LOG_PATH = os.path.join(d, "gunk.log")
    return _LOG_PATH


def log(msg):
    p = log_path()
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def clear_log():
    p = log_path()
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"--- gunk session {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    except OSError:
        pass
