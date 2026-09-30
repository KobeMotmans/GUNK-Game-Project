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

# Een skin van een paar honderd kB is ruim zevenhonderd UDP-stukken. UDP
# gooit er willekeurig weg, dus na elke ronde blijft er een gat over. Deze
# bepalen hoe geduldig we daarop reageren: na een halve seconde stilte
# vragen we opnieuw, en dat mag een aantal rondes duren voordat we het
# opgeven. Vraag je niet de gaten maar de hele rij opnieuw, dan komt er bij
# deze hoeveelheid data simpelweg geen moment waarop alles toevallig
# binnenkomt.
SKIN_DOWNLOAD_ROUNDS = 80

# Hoe lang we wachten op het volgende stuk. Zolang er stukken binnenkomt
# schuift dit mee, dus een trage of verstopte server kost hier geen extra
# ronde; pas als er echt niets meer komt beginnen we opnieuw.
SKIN_DOWNLOAD_STILTE = 0.4

# Hoeveel gaten we in één verzoek opvullen. Meer dan dit in één pakket
# zou het verzoek boven de 1500-byte MTU duwen, en dan is het pakket zelf
# het slachtoffer van een verloren fragment. In de gewone situatie is er
# maar een handvol gaten en doet dit er niet voor.
SKIN_DOWNLOAD_GAPS = 128

# Een ruime ontvangstbuffer, omdat de server de stukken met korte pauzes
# stuurt. Zonder dit loopt de buffer vol terwijl we nog aan het lezen zijn.
SKIN_DOWNLOAD_RCVBUF = 4 * 1024 * 1024

def _get_builtin_dir():
    return asset_path(os.path.join("assets", "players"))

def _get_cache_dir():
    """Waar de opgehaalde skins worden bewaard.

    De voorkeur is naast het spel, maar dat is niet altijd een plek waar
    geschreven mag worden. Zou dit klappen, dan belandt de fout via
    has_skin_locally in start_background_download en van daar in
    NetworkClient.connect, en dan kan een speler niet eens meer verbinden
    omdat er geen schrijfplek voor de skins is. Daarom zoeken we een
    bruikbare plek en anders de tijdelijke map: een skin die nergens
    bewaard kan worden is beter dan een spel dat niet inlogt.
    """
    kandidaten = [appdata_path(os.path.join("cache", "skins")),
                  os.path.join(tempfile.gettempdir(), "GUNK", "cache", "skins")]
    for pad in kandidaten:
        try:
            os.makedirs(pad, exist_ok=True)
            # Ook echt schrijven: een map die alleen gelezen mag worden
            # klapt pas bij het downloaden, dus daar is makedirs niet genoeg.
            # mkstemp geeft elke aanroep een eigen naam, zodat twee
            # draadjes elkaar niet het proefbestand weghalen.
            fd, probe = tempfile.mkstemp(dir=pad, prefix=".schrijftest")
            os.close(fd)
            os.unlink(probe)
            return pad
        except OSError:
            continue
    # Niets bruikbaars gevonden. Dan geven we de voorkeursplek terug, zodat
    # de fout bij het wegschrijven zelf ontstaat met een duidelijke melding,
    # in plaats van hier al te klappen of stilzwijgend naar een plek te
    # wijzen waar toch niets kan.
    return kandidaten[0]

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
        try:
            if skin_id < BUILTIN_MAX:
                path = os.path.join(_get_builtin_dir(), f"player_{skin_id}.png")
                return os.path.exists(path)
            return os.path.exists(_get_custom_path(skin_id))
        except OSError:
            # Onbekend is in dit geval "nee": dan wordt de skin opgehaald
            # in plaats van dat het hele verbinden eraan stukloopt.
            return False

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
            except (FileNotFoundError, pygame.error, OSError):
                # Het bestand bestaat maar is geen bruikbare afbeelding. Zou
                # je het laten staan, dan probeert het spel hetzelfde
                # kapotte bestand elke frame opnieuw te lezen en blijft de
                # skin voor altijd grijs. Weggooien zorgt ervoor dat de
                # volgende keer dat hij van de server wordt opgehaald.
                # Alleen voor opgehaalde skins: een ingebouwde asset die niet
                # te lezen valt komt niet meer terug en zou wegblijven.
                if skin_id >= BUILTIN_MAX:
                    try:
                        os.unlink(path)
                    except OSError:
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
    def _write_skin_file(cls, skin_id, raw):
        """Schrijf de skin atomair weg: eerst naar een tijdelijk bestand, dan
        omzetten. Zo kan een onderbroken download nooit een half bestand
        achterlaten dat de volgende start alsnog inlaadt."""
        out = _get_custom_path(skin_id)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(dir=os.path.dirname(out), delete=False,
                                         suffix=".tmp")
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
        # Het sprite kan gecachet zijn van een vorige, mislukte poging.
        cls._cache.pop(skin_id, None)
        return True

    @classmethod
    def download_skin(cls, skin_id):
        if cls._server_addr is None:
            print(f"[SKIN] download_skin({skin_id}): _server_addr is None")
            return False
        host, port = cls._server_addr
        chunks = {}
        total_chunks = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except OSError as e:
            print(f"[SKIN] download_skin({skin_id}): kon geen socket openen: {e}")
            return False
        try:
            sock.settimeout(SKIN_DOWNLOAD_STILTE)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF,
                                SKIN_DOWNLOAD_RCVBUF)
            except OSError:
                pass  # sommige platformen weigeren dit; dan maar zonder

            for ronde in range(SKIN_DOWNLOAD_ROUNDS):
                gevraagd = None
                if total_chunks:
                    # Alleen de gaten. De hele rij opnieuw vragen zou bij
                    # deze hoeveelheid stukken nooit compleet worden, want
                    # dan komt er bij elke poging weer een gat bij.
                    gevraagd = [i for i in range(total_chunks) if i not in chunks]
                    if not gevraagd:
                        break
                    gevraagd = gevraagd[:SKIN_DOWNLOAD_GAPS]
                req = {"type": "skin_request", "skin_id": skin_id}
                if gevraagd is not None:
                    req["chunks"] = gevraagd
                try:
                    sock.sendto(encode_packet(req), (host, port))
                except OSError:
                    pass  # volgende ronde proberen we het opnieuw

                # Lezen tot het stil valt. De timeout op de socket doet dat al,
                # want die loopt pas af als er niets meer binnenkomt; zodra er
                # een gat overblijft vragen we dus meteen opnieuw, in plaats
                # van tien seconden op de klok te blijven zitten zoals
                # vroeger. De klok hieronder is alleen een vangnet voor een
                # server die blijft doorzeuren, en schuift mee met elk stuk.
                rond_einde = time.time() + SKIN_DOWNLOAD_STILTE
                while time.time() < rond_einde:
                    try:
                        data, _addr = sock.recvfrom(65536)
                    except (socket.timeout, OSError):
                        break
                    rond_einde = time.time() + SKIN_DOWNLOAD_STILTE
                    try:
                        resp = decode_packet(data)
                    except Exception:
                        continue
                    if resp.get("skin_id") != skin_id:
                        continue
                    if resp.get("type") == "skin_data":
                        raw = resp.get("data")
                        if raw is None:
                            print(f"[SKIN] download_skin({skin_id}): "
                                  f"server has no such skin (None)")
                            return False
                        return cls._write_skin_file(skin_id, raw)
                    if resp.get("type") == "skin_chunk":
                        chunks[resp["chunk"]] = resp["data"]
                        total_chunks = resp["total"]
                        if len(chunks) == total_chunks:
                            raw = b''.join(chunks[i] for i in range(total_chunks))
                            return cls._write_skin_file(skin_id, raw)

            print(f"[SKIN] download_skin({skin_id}): opgegeven na {ronde + 1} "
                  f"rondes, {len(chunks)}/{total_chunks or '?'} stukken")
            return False
        except OSError as e:
            print(f"[SKIN] download_skin({skin_id}): netwerkfout {e}")
            return False
        finally:
            sock.close()

    @classmethod
    def start_background_download(cls):
        # Nieuwe skins aan de bestaande wachtrij toevoegen in plaats van de
        # rij te vervangen. Iemand die midden in het spel een skin uploadt
        # krijgt een manifest-update, en die komt hier langs terwijl de
        # eerste ronde nog bezig is. Vervingen we de lijst dan werkt de
        # draadje op de nieuwe lijst en begint er straks nog een tweede
        # draadje, zodat twee draadjes dezelfde skins proberen te halen.
        #
        # Dit draait midden in NetworkClient.connect, dus een skinprobleem
        # mag daar nooit de verbinding mee blokkeren.
        try:
            nieuw = [s["id"] for s in cls._manifest
                     if not cls.has_skin_locally(s["id"])]
        except Exception:
            return
        for sid in nieuw:
            if sid not in cls._download_queue:
                cls._download_queue.append(sid)
        if not cls._download_queue:
            return
        cls._download_progress = {
            "total": len(cls._download_queue),
            "done": 0,
            "current": None,
            "error": None,
        }
        cls._download_completed = set()
        if cls.is_downloading():
            return  # de lopende draadje pakt de nieuwe skins wel mee
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


