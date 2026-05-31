import sys
import os
import json
from ..assets.texture_cache import clear as clear_texture_cache


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def asset_path(rel_path):
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), rel_path)
    return os.path.join(_project_root(), rel_path)


def appdata_path(rel_path):
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), rel_path)
    base = os.environ.get('APPDATA') or os.path.expanduser("~")
    return os.path.join(base, "GUNK", rel_path)


# ── Texture pack system ──────────────────────────────────────────────

TEXTURE_PACK = None
_pack_config = {}


def set_pack(pack_name):
    global TEXTURE_PACK, _pack_config
    TEXTURE_PACK = pack_name
    _pack_config = {}
    clear_texture_cache()
    if pack_name:
        p = os.path.join(_project_root(), "assets", "packs", pack_name, "pack.json")
        if os.path.exists(p):
            with open(p) as f:
                _pack_config = json.load(f)


def pack_config(key, default=None):
    return _pack_config.get(key, default)


def list_packs():
    """Returns [{"label": str, "value": name|None}, ...] for all packs in assets/packs/"""
    packs = [{"label": "None", "value": None}]
    packs_dir = os.path.join(_project_root(), "assets", "packs")
    if os.path.isdir(packs_dir):
        for entry in sorted(os.listdir(packs_dir)):
            p = os.path.join(packs_dir, entry, "pack.json")
            if os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        cfg = json.load(f)
                except:
                    continue
                packs.append({
                    "label": cfg.get("display_name", entry),
                    "value": entry
                })
    return packs


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
