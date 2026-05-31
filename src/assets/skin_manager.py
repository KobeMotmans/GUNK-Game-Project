import os
import glob
import struct
import socket
import pickle
import pygame
from ..core.paths import asset_path, appdata_path

BUILTIN_MAX = 99
CUSTOM_MIN = 100

def _get_builtin_dir():
    return asset_path(os.path.join("assets", "players"))

def _get_cache_dir():
    path = appdata_path(os.path.join("cache", "skins"))
    os.makedirs(path, exist_ok=True)
    return path

def _get_custom_path(skin_id):
    return os.path.join(_get_cache_dir(), f"skin_{skin_id}.png")

def _fallback_sprite():
    surf = pygame.Surface((64, 64), pygame.SRCALPHA)
    surf.fill((100, 100, 100, 255))
    return surf


class SkinManager:
    _cache = {}
    _manifest = []
    _server_addr = None

    @classmethod
    def get_available_skins(cls):
        builtin = []
        pattern = os.path.join(_get_builtin_dir(), "player_*.png")
        files = sorted(glob.glob(pattern))
        for fp in files:
            basename = os.path.splitext(os.path.basename(fp))[0]
            sid = basename.replace("player_", "")
            try:
                sid = int(sid)
            except ValueError:
                continue
            builtin.append({"id": sid, "name": f"Skin {sid}", "type": "builtin"})
        if not builtin:
            builtin.append({"id": 0, "name": "Default", "type": "builtin"})
        custom = [dict(s) for s in cls._manifest]
        for s in custom:
            s["type"] = "custom"
        return builtin + custom

    @classmethod
    def set_server_addr(cls, addr):
        cls._server_addr = addr

    @classmethod
    def set_manifest(cls, manifest):
        cls._manifest = list(manifest)
        manifest_ids = {s["id"] for s in manifest}
        cls._cache = {k: v for k, v in cls._cache.items()
                      if k < BUILTIN_MAX or k in manifest_ids}

    @classmethod
    def has_skin_locally(cls, skin_id):
        if skin_id < BUILTIN_MAX:
            path = os.path.join(_get_builtin_dir(), f"player_{skin_id}.png")
            return os.path.exists(path)
        return os.path.exists(_get_custom_path(skin_id))

    @classmethod
    def load_skin_sprite(cls, skin_id):
        if skin_id in cls._cache:
            return cls._cache[skin_id]

        if skin_id < BUILTIN_MAX:
            path = os.path.join(_get_builtin_dir(), f"player_{skin_id}.png")
        else:
            path = _get_custom_path(skin_id)

        print(f"[SKIN] load_skin_sprite({skin_id}): checking {path}")
        if os.path.exists(path):
            try:
                sprite = pygame.image.load(path).convert_alpha()
                cls._cache[skin_id] = sprite
                print(f"[SKIN] load_skin_sprite({skin_id}): loaded OK from {path}")
                return sprite
            except (FileNotFoundError, pygame.error) as e:
                print(f"[SKIN] load_skin_sprite({skin_id}): load error {e}")
                pass
        print(f"[SKIN] load_skin_sprite({skin_id}): not found, returning fallback")
        return _fallback_sprite()

    @classmethod
    def create_thumbnail(cls, skin_id, size=(64, 64)):
        sprite = cls.load_skin_sprite(skin_id)
        try:
            return pygame.transform.smoothscale(sprite, size)
        except pygame.error:
            return pygame.transform.scale(sprite, size)

    @classmethod
    def download_skin(cls, skin_id):
        if cls._server_addr is None:
            print(f"[SKIN] download_skin({skin_id}): _server_addr is None")
            return False
        host, port = cls._server_addr
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))
            req = {"type": "skin_request", "skin_id": skin_id}
            data = pickle.dumps(req)
            sock.sendall(struct.pack('!I', len(data)) + data)

            size_data = _recv_all(sock, 4)
            if not size_data:
                sock.close()
                print(f"[SKIN] download_skin({skin_id}): no size_data")
                return False
            size = struct.unpack('!I', size_data)[0]
            if not (0 < size < 5 * 1024 * 1024):
                sock.close()
                print(f"[SKIN] download_skin({skin_id}): invalid size {size}")
                return False
            resp_data = _recv_all(sock, size)
            sock.close()
            if not resp_data:
                print(f"[SKIN] download_skin({skin_id}): no resp_data")
                return False
            resp = pickle.loads(resp_data)
            if resp.get("type") != "skin_data":
                print(f"[SKIN] download_skin({skin_id}): wrong type {resp.get('type')}")
                return False
            raw = resp["data"]
            if raw is None:
                print(f"[SKIN] download_skin({skin_id}): server returned None data")
                return False
            out = _get_custom_path(skin_id)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(raw)
            cls._cache.pop(skin_id, None)
            print(f"[SKIN] download_skin({skin_id}): OK -> {out}")
            return True
        except (socket.timeout, ConnectionRefusedError, OSError, pickle.UnpicklingError) as e:
            print(f"[SKIN] download_skin({skin_id}): exception {e}")
            return False

    @classmethod
    def download_all_skins(cls):
        print(f"[SKIN] download_all_skins: manifest has {len(cls._manifest)} entries")
        for s in cls._manifest:
            sid = s["id"]
            cls._cache.pop(sid, None)
            if not cls.has_skin_locally(sid):
                print(f"[SKIN] download_all_skins: skin {sid} not local, downloading...")
                ok = cls.download_skin(sid)
                print(f"[SKIN] download_all_skins: skin {sid} download {'OK' if ok else 'FAILED'}")
            else:
                print(f"[SKIN] download_all_skins: skin {sid} already local at {_get_custom_path(sid)}")
        print(f"[SKIN] download_all_skins: done")

    @classmethod
    def clear_cache(cls):
        cls._cache.clear()


def _recv_all(sock, n):
    data = b''
    while len(data) < n:
        try:
            chunk = sock.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        except socket.timeout:
            return None
    return data
