import os
import json
from .paths import _project_root


class Theme:
    def __init__(self):
        self._theme_configs = []
        self._lang_configs = []
        self._pack_names = []

    def set_packs(self, names):
        self._theme_configs = []
        self._lang_configs = []
        self._pack_names = list(names)
        root = _project_root()
        for name in names:
            pack_dir = os.path.join(root, "assets", "packs", name)
            pack_json_path = os.path.join(pack_dir, "pack.json")
            if not os.path.exists(pack_json_path):
                continue
            with open(pack_json_path, encoding="utf-8") as f:
                meta = json.load(f)

            config = {k: v for k, v in meta.items() if k != "lang"}
            self._theme_configs.append(config)

            lang_ref = meta.get("lang")
            if lang_ref:
                lang_path = os.path.join(pack_dir, lang_ref)
                if os.path.exists(lang_path):
                    with open(lang_path, encoding="utf-8") as f:
                        self._lang_configs.append(json.load(f))

    def get(self, key, default=None):
        for config in self._theme_configs:
            val = self._deep_get(config, key)
            if val is not None:
                return val
        return default

    def color(self, key, default=(70, 70, 70)):
        val = self.get(f"colors.{key}", default)
        return tuple(val) if isinstance(val, (list, tuple)) else val

    def string(self, key, default=""):
        for config in self._lang_configs:
            val = config.get(key)
            if val is not None:
                return str(val)
        return default

    def size(self, key, default=0):
        return int(self.get(f"sizes.{key}", default))

    def pos(self, key, default=0.0):
        return float(self.get(f"positions.{key}", default))

    def _deep_get(self, config, dotted_key):
        parts = dotted_key.split(".")
        val = config
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                return None
        return val


theme = Theme()
