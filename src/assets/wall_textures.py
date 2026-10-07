"""
wall_textures.py - Muurtexturen, één keer voorbereid voor de raycaster

De raycaster tekent per ray één kolom van `col_w` breed. Een tekstuur per
frame per-pixel bemonsteren kost ~90 ms (de klassieke set_at-lus), en zelfs
numpy op volledige resolutie kost ~50 ms; zie tests/bench_wall_textures.py.
Het enige wat wél snel is, is per kolom één transform.scale op een vooraf
gesneden strip.

Daarom gebeurt hier alles wat niet per frame verandert, één keer:

 * de tekstuur laden (of procedureel opbouwen als het bestand ontbreekt),
 * alpha plat slaan zodat een muur nooit doorzichtig wordt,
 * WALL_SHADE_BANDS verdunde kopieën maken voor het afstandslicht,
 * elke kop snijden in verticale strips van 1 px breed.

Per frame blijft over: één tabelindex, één transform.scale, één blit.
"""

import os

import pygame

from ..core import config as cfg
from ..core.logger import log
from ..core.paths import asset_path, resolve_asset

# pad -> (breedte, hoogte, [strip, ...])
_cache = {}
# De oppervlakken waarin gesneden is. Strips zijn subsurfaces en delen dus
# de pixels met hun parent; die moet blijven bestaan zolang er strips van
# in gebruik zijn. Vandaar deze tweede tabel naast _cache.
_sources = {}
_missing = set()


def clear():
    """Voorbereide strips weggooien, bv. na een texture-pack wissel."""
    _cache.clear()
    _sources.clear()


def _resolve(path):
    """Vind een tekstuurbestand.

    Een pad mag drie dingen zijn: een asset-subpad (assets/..., waarbij
    packs voorgaan), een pad relatief t.o.v. de spelmap, of een absoluut
    pad. Zo kan WALL_TEXTURES ook wijzen op iets buiten assets/, zoals een
    opgehaalde skin van de multiplayer-server.
    """
    if os.path.isabs(path):
        return path if os.path.exists(path) else None
    found = resolve_asset(path)
    if os.path.exists(found):
        return found
    found = asset_path(path)
    if os.path.exists(found):
        return found
    return None


def _flatten(surf):
    """Maak een tekstuur volledig dekkend.

    Een skin van de multiplayer-server is RGBA. Transparante pixels op een
    muur worden ofwel doorzichtig (gaten in de muur) ofwel zwart (vlekken),
    dus we plakken de afbeelding op een egale ondergrond.
    """
    if not surf.get_flags() & pygame.SRCALPHA:
        return surf
    flat = pygame.Surface(surf.get_size())
    flat.fill((96, 94, 90))
    flat.blit(surf, (0, 0))
    return flat


def _placeholder(stem):
    """Bouwt een muur op als het tekstuurbestand ontbreekt.

    Beter een herkenbare betonnen muur dan een verrassing: de game moet ook
    zonder kunstwerken starten en de tekstuurlaag meteen zichtbaar zijn.
    Leg je het bestand in assets/textures/wall/, dan verdwijnt deze
    procedurele versie vanzelf.
    """
    import random
    size = 64
    if "baksteen" in stem:
        base = (124, 76, 58)
    elif "metaal" in stem:
        base = (104, 112, 124)
    elif "hout" in stem:
        base = (126, 96, 60)
    else:
        base = (112, 110, 104)
    dark = tuple(max(0, v - 26) for v in base)
    light = tuple(min(255, v + 18) for v in base)

    surf = pygame.Surface((size, size))
    surf.fill(base)
    rnd = random.Random(stem)
    for _ in range(size * size // 6):
        x = rnd.randrange(size)
        y = rnd.randrange(size)
        d = rnd.randint(-16, 16)
        surf.set_at((x, y), tuple(max(0, min(255, v + d)) for v in base))

    if "baksteen" in stem:
        for row in range(4):
            y = row * 16
            pygame.draw.line(surf, dark, (0, y), (size, y), 2)
            for x in range(0 if row % 2 == 0 else 16, size, 32):
                pygame.draw.line(surf, dark, (x, y), (x, y + 16), 2)
    elif "metaal" in stem:
        for y in (0, 32):
            pygame.draw.rect(surf, dark, (0, y, size, 32), 2)
        for x in (4, 28, 52):
            for y in (8, 40):
                pygame.draw.circle(surf, light, (x, y), 3)
    else:
        pygame.draw.line(surf, dark, (0, 32), (size, 32), 2)
        pygame.draw.line(surf, light, (0, 34), (size, 34), 1)
    return surf.convert()


def _load(path):
    full = _resolve(path)
    if full is None:
        if path not in _missing:
            _missing.add(path)
            log(f"muurtextuur ontbreekt: {path} (procedureel patroon gebruikt)")
        return _placeholder(os.path.splitext(os.path.basename(path))[0])
    return _flatten(pygame.image.load(full)).convert()


def _prepare(surf):
    """Verdunnen per afstandsband en in kolomstrips snijden."""
    w, h = surf.get_size()
    max_size = cfg.WALL_TEXTURE_SIZE
    if w > max_size or h > max_size:
        # Muurtexturen zijn sowieso klein: per ray bemonsteren we één
        # texelkolom per schermkolom van 4 px, dus extra resolutie kost
        # alleen geheugen en laadtijd.
        s = max_size / max(w, h)
        surf = pygame.transform.scale(surf, (max(1, int(w * s)), max(1, int(h * s))))
        w, h = surf.get_size()

    bands = cfg.WALL_SHADE_BANDS
    sources = [surf]
    strips = []
    for b in range(bands):
        shade = 255 - int(b * 255 / max(1, bands - 1))
        if shade >= 255:
            shaded = surf
        else:
            shaded = surf.copy()
            shaded.fill((shade, shade, shade), special_flags=pygame.BLEND_MULT)
            sources.append(shaded)
        # Eén platte lijst i.p.v. genest: index = band * breedte + kolom.
        strips.extend(shaded.subsurface((x, 0, 1, h)) for x in range(w))
    return w, h, strips, sources


def strips(tile_value):
    """Kolomstrips voor een muurtegel: (breedte, hoogte, strips)."""
    path = cfg.wall_texture(tile_value)
    entry = _cache.get(path)
    if entry is None:
        w, h, cols, src = _prepare(_load(path))
        entry = (w, h, cols)
        _cache[path] = entry
        _sources[path] = src
    return entry
