"""
tests/wall_texture_test.py - Muurtexturen bemonsteren echt (geen pytest nodig)

Zet WALL_TEXTURES[1] tijdelijk om naar een echte skin uit de multiplayer-server
(cache/skins/skin_100.png) en controleert dat de raycaster daaruit tekent in
plaats van de oude grijze kolom. Ook de voorbereiding (lichtbanden, strips,
schalen) en de framekosten worden nagelopen.

Heeft een display nodig (SDL dummy-driver, dus geen venster), daarom staat er
hier géén GUNK_HEADLESS: config.convert() werkt niet zonder display.

Gebruik:
    py -3.10 tests/wall_texture_test.py
"""

import os
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # offscreen, geen venster
os.environ.pop("GUNK_HEADLESS", None)              # convert() heeft een display nodig

from src.core import config as cfg                     # noqa: E402

# Alleen hier, alleen voor deze run: de rest van de game ziet de gewone tabel.
SKIN = os.path.join("cache", "skins", "skin_100.png")
assert os.path.exists(SKIN), f"skin niet gevonden: {SKIN}"
cfg.WALL_TEXTURES[1] = SKIN
cfg.set_resolution("high")  # NUM_RAYS staat bij import nog op 0

from src.assets import wall_textures                   # noqa: E402
from src.core.map_loader import M                      # noqa: E402
from src.core.raycaster import dda                     # noqa: E402
from src.core.vector import Vector                     # noqa: E402
from pygame import surfarray                           # noqa: E402

ok = True


def check(label, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'OK  ' if cond else 'FOUT'} {label}" + (f"  ({detail})" if detail else ""))


print(f"muurtextuur = {cfg.wall_texture(1)}\n")

# ── 1. Voorbereiding ────────────────────────────────────────────────
print("1. voorbereiding")
t0 = time.perf_counter()
w, h, cols = wall_textures.strips(1)
prep_ms = (time.perf_counter() - t0) * 1000

check("strip per band en kolom", len(cols) == cfg.WALL_SHADE_BANDS * w,
      f"{len(cols)} = {cfg.WALL_SHADE_BANDS} banden x {w} kolommen")
check("strip is 1 px breed", cols[0].get_size() == (1, h), f"{cols[0].get_size()}")
check("geschaald naar WALL_TEXTURE_SIZE", max(w, h) <= cfg.WALL_TEXTURE_SIZE,
      f"{w}x{h}")
check("geladen, niet procedureel (echt bestand gevonden)",
      SKIN not in wall_textures._missing)
print(f"  laadtijd {prep_ms:.1f} ms\n")

# ── 2. Zit er echte beeldinformatie in de strips? ──────────────────
print("2. inhoud")
def strip_colors(i):
    return [cols[i].get_at((0, y))[:3] for y in range(h)]


kol0, kol1 = strip_colors(0), strip_colors(1)
check("kolommen verschillen van elkaar (echte beeldinformatie)", kol0 != kol1)

alle = set()
for i in (0, 1, w // 2, w - 1):
    alle.update(strip_colors(i))
check("meerdere kleuren", len(alle) > 20, f"{len(alle)} unieke")
niet_grijs = [c for c in alle if not (c[0] == c[1] == c[2])]
check("niet-grijze kleuren (de oude renderer geeft enkel grijs)",
      len(niet_grijs) > 10, f"{len(niet_grijs)} stuks")

laatste = strip_colors((cfg.WALL_SHADE_BANDS - 1) * w)  # laatste band, dezelfde kolom
gem0 = sum(map(sum, kol0)) / (len(kol0) * 3)
gem31 = sum(map(sum, laatste)) / (len(laatste) * 3)
check("afstandslicht verduwt met de afstand", gem31 < gem0 * 0.6,
      f"band 0 = {gem0:.0f}, band 31 = {gem31:.0f}")
print()

# ── 3. Echt level renderen ──────────────────────────────────────────
print("3. renderen")
px, py = M.SPAWNS["player"]
angle = M.start_angle
print(f"  spawn ({px:.0f}, {py:.0f}), hoek {angle:.2f}")

cfg.SCREEN.fill((0, 0, 0))
t0 = time.perf_counter()
wall_distances = dda(Vector(px, py), angle)
eerste_ms = (time.perf_counter() - t0) * 1000

check("elke ray raakt een muur", len(wall_distances) == cfg.NUM_RAYS,
      f"{len(wall_distances)} / {cfg.NUM_RAYS}")
check("wand op zinnige afstand", all(0 < d <= 2000 for d in wall_distances),
      f"{min(wall_distances):.0f}..{max(wall_distances):.0f} px")

px_arr = surfarray.array3d(cfg.SCREEN)
kleuren = {tuple(int(v) for v in px_arr[x, y])
           for x in range(0, cfg.WIDTH, 3) for y in range(0, cfg.HEIGHT, 3)}
grijs = {c for c in kleuren if c[0] == c[1] == c[2]}
niet_grijs_pct = 100 * len(kleuren - grijs) // max(1, len(kleuren))
check("veel kleuren op het scherm", len(kleuren) > 60, f"{len(kleuren)} unieke")
check("grootste deel van het scherm is niet-grijs", niet_grijs_pct > 50,
      f"{niet_grijs_pct}%")

tijd = []
for _ in range(40):
    cfg.SCREEN.fill((0, 0, 0))
    t0 = time.perf_counter()
    dda(Vector(px, py), angle)
    tijd.append(time.perf_counter() - t0)
tekst_ms = statistics.median(tijd) * 1000

# A/B in dezelfde DDA: alleen het tekenen wisselt. DDA-march, hit_wall,
# wall_face en het sprite-sortwerk doen in beide gevallen exact hetzelfde,
# dus het verschil is puur wat het textureren kost.
import pygame
import src.core.raycaster as rc


def plat(dist, ray, y_offset=0, tile_value=1, u=0.0):
    """De oude implementatie: één grijze pygame.draw.rect per ray."""
    wall_height = cfg.TILE_SIZE * cfg.PROJ_DIST / dist
    y = cfg.HEIGHT / 2 - wall_height / 2 + y_offset
    col_w = cfg.WIDTH // cfg.NUM_RAYS
    shade = max(0, min(255, 255 - int(dist * 255 / cfg.MAX_DEPTH)))
    pygame.draw.rect(cfg.SCREEN, (shade, shade, shade),
                     (ray * col_w, y, col_w, wall_height))


def meet(n=40):
    tijden = []
    for _ in range(n):
        cfg.SCREEN.fill((0, 0, 0))
        t0 = time.perf_counter()
        dda(Vector(px, py), angle)
        tijden.append(time.perf_counter() - t0)
    return statistics.median(tijden) * 1000


origineel = rc.draw_wall
rc.draw_wall = plat
plat_ms = meet()
rc.draw_wall = origineel
tekst_ab_ms = meet()

delta = tekst_ab_ms - plat_ms
print(f"  resolutie {cfg.WIDTH}x{cfg.HEIGHT}, {cfg.NUM_RAYS} rays, kolom "
      f"{cfg.WIDTH // cfg.NUM_RAYS} px")
print(f"  dda() platte kolom     : {plat_ms:.2f} ms")
print(f"  dda() met tekstuur     : {tekst_ab_ms:.2f} ms  (los gemeten {tekst_ms:.2f} ms)")
print(f"  verschil = {delta:+.2f} ms per frame")
check("textureren kost minder dan 3 ms extra", delta < 3.0, f"{delta:+.2f} ms")
check("eerste frame (koude cache) blijft acceptabel", eerste_ms < 40,
      f"{eerste_ms:.1f} ms")

# ── Screenshot ──────────────────────────────────────────────────────
cfg.SCREEN.fill((0, 0, 0))
dda(Vector(px, py), angle)
shot = os.path.join(tempfile.gettempdir(), "gunk_wall_met_skin.png")
import pygame
pygame.image.save(cfg.SCREEN, shot)
print(f"\nscreenshot: {shot}")

print("\nALLE CHECKS GROEN" if ok else "\nER ZIJN FOUTEN")
raise SystemExit(0 if ok else 1)
