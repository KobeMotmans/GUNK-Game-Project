import sys
import os
import shutil


def _ensure_assets():
    if not getattr(sys, 'frozen', False):
        return
    appdata_root = os.path.join(os.environ.get('APPDATA', os.path.expanduser("~")), 'GUNK')
    marker = os.path.join(appdata_root, '.assets_copied')
    if os.path.exists(marker):
        return
    src = os.path.join(sys._MEIPASS, 'assets')
    if os.path.exists(src):
        dst = os.path.join(appdata_root, 'assets')
        shutil.copytree(src, dst, dirs_exist_ok=True)
    open(marker, 'w').close()


_ensure_assets()


def asset_path(rel_path):
    if getattr(sys, 'frozen', False):
        base = os.environ.get('APPDATA') or os.path.expanduser("~")
        return os.path.join(base, "GUNK", rel_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path)


def appdata_path(rel_path):
    base = os.environ.get('APPDATA') or os.path.expanduser("~")
    return os.path.join(base, "GUNK", rel_path)
