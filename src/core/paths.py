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

TEXTURE_PACKS = []
_pack_config = {}
_font_path_cache = {}
_font_cache = {}
_PACK_CONFIG_PATH = asset_path("pack_config.json")


def set_packs(names):
    global TEXTURE_PACKS, _pack_config
    from .theme import theme as _theme
    TEXTURE_PACKS[:] = list(names)
    _pack_config = {}
    clear_texture_cache()
    _font_path_cache.clear()
    _font_cache.clear()
    _theme.set_packs(names)
    if names:
        root = _project_root()
        p = os.path.join(root, "assets", "packs", names[0], "pack.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                _pack_config = json.load(f)


def set_pack(pack_name):
    """Backward compat: zet één pack."""
    set_packs([pack_name] if pack_name else [])


def save_active_packs(names):
    with open(_PACK_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"active_packs": names}, f)


def load_active_packs():
    try:
        with open(_PACK_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f).get("active_packs", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def init_packs():
    set_packs(load_active_packs())


def pack_config(key, default=None):
    from .theme import theme as _theme
    if key == "font":
        return _theme.get("font") or _pack_config.get(key, default)
    if key == "font_has_numbers":
        val = _theme.get("font_has_numbers")
        if val is not None:
            return val
        return _pack_config.get(key, default)
    if key == "bg_color":
        val = _theme.get("colors.bg")
        if val is not None:
            return tuple(val) if isinstance(val, (list, tuple)) else val
        return _pack_config.get(key, default)
    if key == "elevator_color":
        val = _theme.get("colors.elevator")
        if val is not None:
            return tuple(val) if isinstance(val, (list, tuple)) else val
        return _pack_config.get(key, default)
    if key == "weapon_sound":
        return _theme.get("sounds.weapon") or _pack_config.get(key, default)
    return _pack_config.get(key, default)


def list_packs():
    """Returns [{"label": str, "value": str}, ...] for all discoverable packs (sorted by display_name)."""
    packs = []
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
    """resolve_asset('textures/enemies/normal_enemy.png') -> volledig pad
       Checkt packs in TEXTURE_PACKS (hoogste prioriteit eerst), dan base assets."""
    root = _project_root()
    for pack_name in TEXTURE_PACKS:
        p = os.path.join(root, "assets", "packs", pack_name, subpath)
        if os.path.exists(p):
            return p
    return asset_path(os.path.join("assets", subpath))


def resolve_font(font_name):
    """Check pack's dirs first, then fall back to base assets/font/.
       If font_name contains a path separator, treat it as a pack-relative path.
       Otherwise, look in the pack's fonts/ subdirectory."""
    root = _project_root()
    has_sep = "/" in font_name or "\\" in font_name
    for pack_name in TEXTURE_PACKS:
        if has_sep:
            p = os.path.join(root, "assets", "packs", pack_name, font_name)
        else:
            p = os.path.join(root, "assets", "packs", pack_name, "fonts", font_name)
        if os.path.exists(p):
            return p
    if has_sep:
        return asset_path(os.path.join("assets", font_name))
    return asset_path(os.path.join("assets", "font", font_name))


_fallback_font_path = None


def _try_load_font(path, size, bold):
    import pygame
    global _fallback_font_path
    if _fallback_font_path is None:
        _fallback_font_path = resolve_font("ocraextended.ttf")
    for attempt in (path, _fallback_font_path):
        try:
            font = pygame.font.Font(attempt, size)
            font.set_bold(bold)
            font.render("W", True, (255, 255, 255))
            return font
        except pygame.error:
            if attempt == _fallback_font_path:
                raise
            continue


def load_font(size, bold=False):
    """Load the active pack's configured font (cached Font object).
    Falls back to ocraextended.ttf if the pack's font fails to render."""
    font_name = pack_config("font", "ocraextended.ttf")
    if font_name not in _font_path_cache:
        _font_path_cache[font_name] = resolve_font(font_name)
    path = _font_path_cache[font_name]
    key = (path, size, bold)
    if key not in _font_cache:
        import pygame
        font = _try_load_font(path, size, bold)
        _font_cache[key] = font
    return _font_cache[key]


def load_numeric_font(size, bold=False):
    """Load a font guaranteed to have number glyphs.
    Falls back to the base font (ocraextended.ttf) when the pack's
    font has font_has_numbers=false in pack.json."""
    font_name = pack_config("font", "ocraextended.ttf")
    if not pack_config("font_has_numbers", True):
        font_name = "ocraextended.ttf"
    if font_name not in _font_path_cache:
        _font_path_cache[font_name] = resolve_font(font_name)
    path = _font_path_cache[font_name]
    key = (path, size, bold)
    if key not in _font_cache:
        font = _try_load_font(path, size, bold)
        _font_cache[key] = font
    return _font_cache[key]
