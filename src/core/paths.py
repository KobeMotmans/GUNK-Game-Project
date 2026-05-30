import sys
import os
import json
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


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def asset_path(rel_path):
    if getattr(sys, 'frozen', False):
        base = os.environ.get('APPDATA') or os.path.expanduser("~")
        return os.path.join(base, "GUNK", rel_path)
    return os.path.join(_project_root(), rel_path)


def appdata_path(rel_path):
    base = os.environ.get('APPDATA') or os.path.expanduser("~")
    return os.path.join(base, "GUNK", rel_path)


# ── Texture pack system ──────────────────────────────────────────────

TEXTURE_PACK = None
_pack_config = {}


def set_pack(pack_name):
    global TEXTURE_PACK, _pack_config
    TEXTURE_PACK = pack_name
    _pack_config = {}
    if pack_name:
        p = os.path.join(_project_root(), "assets", "packs", pack_name, "pack.json")
        if os.path.exists(p):
            with open(p) as f:
                _pack_config = json.load(f)


def pack_config(key, default=None):
    return _pack_config.get(key, default)


def resolve_asset(subpath):
    """resolve_asset('textures/enemies/andrei.png') -> volledig pad
       Checkt: pack override map → pack direct → base assets"""
    if not TEXTURE_PACK:
        return asset_path(os.path.join("assets", subpath))
    root = _project_root()
    overrides = _pack_config.get("override_map", {})
    if subpath in overrides:
        p = os.path.join(root, "assets", "packs", TEXTURE_PACK, overrides[subpath])
        if os.path.exists(p):
            return p
    p = os.path.join(root, "assets", "packs", TEXTURE_PACK, subpath)
    if os.path.exists(p):
        return p
    return asset_path(os.path.join("assets", subpath))
