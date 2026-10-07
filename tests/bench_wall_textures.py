"""Benchmark: muurtexturen vs. de huidige platte kolom.

Meet hoeveel ms de muurlaag kost per frame bij de echte GUNK-instellingen
(1920x1030, NUM_RAYS = WIDTH//4 = 480, kolombreedte 4 px).

De camera beweegt in de meetlus, zodat wandelhoogtes elke frame veranderen
(geen kunstmatig warme caches).

Run:  py -3.10 bench_walls.py
"""
import os
import statistics
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

# ── GUNK-parameters ────────────────────────────────────────────────
WIDTH, HEIGHT = 1920, 1030
NUM_RAYS = WIDTH // 4          # 480, zoals config.set_resolution("high")
COL_W = WIDTH // NUM_RAYS      # 4
TILE_SIZE = 100
PROJ_DIST = WIDTH // 2         # FOV = 90 graden -> tan(45) = 1
MAX_DEPTH = 1000
TEX = 64                       # textuurresolutie
N_BANDS = 8                    # afstandslicht-banden
N_TEX = 3                      # aantal muurtexturen
BG = (20, 24, 30)

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))


def make_brick(seed):
    """Procedurele bakstenen muur, 64x64."""
    import random
    rng = random.Random(seed)
    surf = pygame.Surface((TEX, TEX))
    base = (90 + seed * 30 % 60, 70, 62)
    surf.fill(base)
    bh = 16
    for row in range(TEX // bh):
        off = 0 if row % 2 == 0 else TEX // 4
        for col in range(-1, 3):
            x = off + col * (TEX // 2)
            shade = rng.randint(-18, 18)
            c = tuple(max(0, min(255, v + shade)) for v in base)
            pygame.draw.rect(surf, c, (x, row * bh, TEX // 2 - 2, bh - 2))
            pygame.draw.rect(surf, tuple(min(255, v + 25) for v in c),
                             (x, row * bh, TEX // 2 - 2, 2))
    return surf.convert()


TEXTURES = [make_brick(i) for i in range(N_TEX)]
TEX_ARR = np.stack([pygame.surfarray.array3d(t) for t in TEXTURES])  # (n,TX,TX,3)

SHADE = [max(0, min(255, 255 - (b + 1) * 255 // N_BANDS)) for b in range(N_BANDS)]
STRIPS = []
for t in range(N_TEX):
    per_band = []
    for b in range(N_BANDS):
        shaded = TEXTURES[t].copy()
        shaded.fill((SHADE[b],) * 3, special_flags=pygame.BLEND_MULT)
        per_band.append([shaded.subsurface((x, 0, 1, TEX)) for x in range(TEX)])
    STRIPS.append(per_band)


def frame_rays(t):
    """Zicht op moment t: camera draait en schuift licht vooruit."""
    rays = []
    drift = 0.85 + 0.3 * (t % 1)
    for r in range(NUM_RAYS):
        # twee wandvlakken op verschillende diepte, met een zigzag zodat
        # aangrenzende rays niet exact dezelfde hoogte delen
        wave = 1.0 + 0.25 * ((r // 24) % 3)
        dist = (60 + 780 * wave) * drift
        dist *= 1.0 + 0.06 * ((r * 37) % 11) / 11
        h = TILE_SIZE * PROJ_DIST / dist
        y = HEIGHT / 2 - h / 2 + 3 * (1 if int(t * 60) % 2 else -1)
        rays.append((y, h, (r + int(t * 90)) % TEX, r % N_TEX,
                     min(N_BANDS - 1, int(dist) * N_BANDS // MAX_DEPTH)))
    return rays


def clipped(y, h):
    y0 = max(0, int(y))
    y1 = min(HEIGHT, int(y + h))
    return y0, y1, y1 - y0


# ── Methodes ───────────────────────────────────────────────────────
def m_rect(rays):
    """Huidige renderer: 1 pygame.draw.rect per ray."""
    for i, (y, h, _tx, _tid, band) in enumerate(rays):
        s = SHADE[band]
        pygame.draw.rect(screen, (s, s, s), (i * COL_W, y, COL_W, h))


def m_setat(rays):
    """Wat de meeste eerste pogingen doen: per pixel set_at()."""
    for i, (y, h, tx, tid, band) in enumerate(rays):
        strip = STRIPS[tid][band][tx]
        x0 = i * COL_W
        y0, y1, n = clipped(y, h)
        if n <= 0:
            continue
        step = TEX / max(1, n)
        for yy in range(y0, y1):
            ty = min(TEX - 1, int((yy - y) * step))
            c = strip.get_at((0, ty))
            for xx in range(COL_W):
                screen.set_at((x0 + xx, yy), c)


def m_sub_scale(rays):
    """Naieve variant: subsurface + transform.scale, elk frame opnieuw."""
    for i, (y, h, tx, tid, _band) in enumerate(rays):
        x0 = i * COL_W
        y0, y1, n = clipped(y, h)
        if n <= 0:
            continue
        col = TEXTURES[tid].subsurface((tx, 0, 1, TEX))
        screen.blit(pygame.transform.scale(col, (COL_W, n)), (x0, y0))


def m_strip_scale(rays):
    """Voorgesneden strips + 8 lichtbanden: scale + blit."""
    for i, (y, h, tx, tid, band) in enumerate(rays):
        x0 = i * COL_W
        y0, y1, n = clipped(y, h)
        if n <= 0:
            continue
        screen.blit(pygame.transform.scale(STRIPS[tid][band][tx], (COL_W, n)),
                    (x0, y0))


_cache = {}


def m_strip_cache(rays):
    """Zelfde, met cache op gekwantiseerde hoogte (4 px)."""
    cache = _cache
    for i, (y, h, tx, tid, band) in enumerate(rays):
        x0 = i * COL_W
        y0, y1, n = clipped(y, h)
        if n <= 0:
            continue
        nq = (n + 3) & ~3
        key = (tid, band, tx, nq)
        col = cache.get(key)
        if col is None:
            col = pygame.transform.scale(STRIPS[tid][band][tx], (COL_W, nq))
            if len(cache) < 60000:
                cache[key] = col
        screen.blit(col, (x0, y0 - (nq - n) // 2))


def m_numpy_gather(rays):
    """Alles vectoriseren met numpy op 480 px breed, dan opschalen."""
    ys = np.fromiter((r[0] for r in rays), dtype=np.float64, count=NUM_RAYS)
    hs = np.fromiter((r[1] for r in rays), dtype=np.float64, count=NUM_RAYS)
    us = np.fromiter((r[2] for r in rays), dtype=np.intp, count=NUM_RAYS)
    tids = np.fromiter((r[3] for r in rays), dtype=np.intp, count=NUM_RAYS)
    sh = np.fromiter((SHADE[r[4]] / 255.0 for r in rays),
                     dtype=np.float64, count=NUM_RAYS)

    rows = np.arange(HEIGHT, dtype=np.float64)
    v = ((rows[None, :] - ys[:, None]) / hs[:, None] * TEX)
    np.clip(v, 0, TEX - 1, out=v)
    v = v.astype(np.intp)
    col = TEX_ARR[tids[:, None], us[:, None], v]           # (R, H, 3)
    col = (col * sh[:, None, None]).astype(np.uint8)
    valid = (rows[None, :] >= ys[:, None]) & (rows[None, :] < ys[:, None] + hs[:, None])
    col[~valid] = BG

    if m_numpy_gather.layer is None:
        m_numpy_gather.layer = pygame.Surface((NUM_RAYS, HEIGHT))
    pygame.surfarray.blit_array(m_numpy_gather.layer, col)
    screen.blit(pygame.transform.scale(m_numpy_gather.layer, (WIDTH, HEIGHT)), (0, 0))


m_numpy_gather.layer = None

METHODS = [
    ("0 huidig: draw.rect", m_rect, 40, False),
    ("1 set_at per pixel", m_setat, 2, False),
    ("2 subsurface+scale (rauw)", m_sub_scale, 40, False),
    ("3 strips+8 lichtbanden", m_strip_scale, 40, False),
    ("4 strips + hoogte-cache", m_strip_cache, 40, True),
    ("5 numpy gather + scale", m_numpy_gather, 40, False),
]

print(f"{WIDTH}x{HEIGHT}, {NUM_RAYS} rays, kolom {COL_W}px, tekstuur {TEX}px")
print("camera beweegt in de meetlus\n")
print(f"{'methode':26} {'mediaan':>9} {'beste':>9}   (ms/frame)")
print("-" * 58)
for name, fn, frames, keep_cache in METHODS:
    if not keep_cache:
        _cache.clear()
    for t in range(3):                      # warmup
        screen.fill(BG)
        fn(frame_rays(t))
    if not keep_cache:
        _cache.clear()
    times = []
    for f in range(frames):
        screen.fill(BG)
        t0 = time.perf_counter()
        fn(frame_rays(3 + f * 0.05))
        times.append(time.perf_counter() - t0)
    med = statistics.median(times) * 1000
    best = min(times) * 1000
    print(f"{name:26} {med:8.2f} {best:8.2f}   ~{1000 / med:.0f} fps enkel")
