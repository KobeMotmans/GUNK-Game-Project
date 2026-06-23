import os
import glob
import socket
import time
import threading
import tempfile
import pygame
from ..core.paths import asset_path, appdata_path
from ..network.protocol import encode_packet, decode_packet

BUILTIN_MAX = 99

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

    _download_thread = None
    _download_queue = []
    _download_progress = {"total": 0, "done": 0, "current": None, "error": None}
    _download_completed = set()

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
        cls._download_completed = set()

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

        if os.path.exists(path):
            try:
                sprite = pygame.image.load(path).convert_alpha()
                cls._cache[skin_id] = sprite
                return sprite
            except (FileNotFoundError, pygame.error) as e:
                pass
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
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(10.0)
            req = {"type": "skin_request", "skin_id": skin_id}
            sock.sendto(encode_packet(req), (host, port))

            chunks = {}
            total_chunks = None
            deadline = time.time() + 30.0
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(65536)
                    resp = decode_packet(data)
                    if resp.get("type") == "skin_data" and resp.get("skin_id") == skin_id:
                        raw = resp["data"]
                        if raw is None:
                            print(f"[SKIN] download_skin({skin_id}): server has no such skin (None)")
                            sock.close()
                            return False
                        out = _get_custom_path(skin_id)
                        os.makedirs(os.path.dirname(out), exist_ok=True)
                        tmp = tempfile.NamedTemporaryFile(dir=os.path.dirname(out), delete=False, suffix=".tmp")
                        try:
                            tmp.write(raw)
                            tmp.close()
                            os.replace(tmp.name, out)
                        except Exception:
                            try:
                                os.unlink(tmp.name)
                            except OSError:
                                pass
                            raise
                        cls._cache.pop(skin_id, None)
                        sock.close()
                        return True
                    elif resp.get("type") == "skin_chunk" and resp.get("skin_id") == skin_id:
                        chunks[resp["chunk"]] = resp["data"]
                        total_chunks = resp["total"]
                        if len(chunks) == total_chunks:
                            raw = b''.join(chunks[i] for i in range(total_chunks))
                            out = _get_custom_path(skin_id)
                            os.makedirs(os.path.dirname(out), exist_ok=True)
                            tmp = tempfile.NamedTemporaryFile(dir=os.path.dirname(out), delete=False, suffix=".tmp")
                            try:
                                tmp.write(raw)
                                tmp.close()
                                os.replace(tmp.name, out)
                            except Exception:
                                try:
                                    os.unlink(tmp.name)
                                except OSError:
                                    pass
                                raise
                            cls._cache.pop(skin_id, None)
                            sock.close()
                            return True
                except socket.timeout:
                    print(f"[SKIN] download_skin({skin_id}): timeout waiting for chunk, retrying...")
                    sock.sendto(encode_packet(req), (host, port))
            sock.close()
            print(f"[SKIN] download_skin({skin_id}): finished after deadline, got {len(chunks)}/{total_chunks or '?'} chunks")
            return False
        except (socket.timeout, OSError, Exception) as e:
            print(f"[SKIN] download_skin({skin_id}): exception {e}")
            return False

    @classmethod
    def start_background_download(cls):
        cls._download_queue = [
            s["id"] for s in cls._manifest
            if not cls.has_skin_locally(s["id"])
        ]
        cls._download_progress = {
            "total": len(cls._download_queue),
            "done": 0,
            "current": None,
            "error": None,
        }
        cls._download_completed = set()
        if not cls._download_queue:
            return
        cls._download_thread = threading.Thread(target=cls._download_worker, daemon=True)
        cls._download_thread.start()

    @classmethod
    def _download_worker(cls):
        while cls._download_queue:
            sid = cls._download_queue.pop(0)
            cls._download_progress["current"] = sid
            try:
                ok = cls.download_skin(sid)
                if ok:
                    cls._download_completed.add(sid)
                print(f"[SKIN] bg download skin {sid}: {'OK' if ok else 'FAILED'}")
            except Exception as e:
                cls._download_progress["error"] = str(e)
            cls._download_progress["done"] += 1
        cls._download_progress["current"] = None
        print(f"[SKIN] bg download: done ({cls._download_progress['done']} total)")

    @classmethod
    def is_downloading(cls):
        return cls._download_thread is not None and cls._download_thread.is_alive()

    @classmethod
    def get_download_progress(cls):
        return dict(cls._download_progress)

    @classmethod
    def get_completed_downloads(cls):
        return list(cls._download_completed)

    @classmethod
    def clear_completed_downloads(cls):
        cls._download_completed.clear()


