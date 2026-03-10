"""
map_loader.py - Laadt en beheert de game map
"""

from PIL import Image
from config import TILE_SIZE, MAP_PATH

def png_to_list_fast(path):
    """Converteer een PNG afbeelding naar een 2D grid (0 = leeg, 1 = muur)"""
    img = Image.open(path).convert("L")
    w, h = img.size  # <-- FIX: size is een property, niet van getdata()
    data = list(img.getdata())
    return [
        [0 if data[y * w + x] > 127 else 1 for x in range(w)]
        for y in range(h)
    ]

# Laad de map bij startup
MAP = png_to_list_fast(MAP_PATH)
MAP_W = len(MAP[0])
MAP_H = len(MAP)


def cord_to_map(cord):
    """Converteer pixel coördinaat naar map grid coördinaat"""
    return cord / TILE_SIZE


def map_to_cord(mapcord):
    """Converteer map grid coördinaat naar pixel coördinaat"""
    return mapcord * TILE_SIZE


def hit_wall(pos):
    """Check of een positie op een muur ligt"""
    if pos.x % 1 == 0:
        x = int(pos.x)
        y = int(pos.y)
        if MAP[y][x - 1] == 1 or MAP[y][x] == 1:
            return True
    elif pos.y % 1 == 0:
        x = int(pos.x)
        y = int(pos.y)
        if MAP[y - 1][x] == 1 or MAP[y][x] == 1:
            return True
    return False


def will_collide(nx, ny, radius=10):
    """
    Check of een cirkel met gegeven radius botst met muren.
    Checkt 4 hoekpunten van de collision box.
    """
    check_positions = [
        (nx - radius, ny - radius),
        (nx + radius, ny - radius),
        (nx - radius, ny + radius),
        (nx + radius, ny + radius)
    ]

    for cx, cy in check_positions:
        mx = int(cx // TILE_SIZE)
        my = int(cy // TILE_SIZE)

        # Out of bounds = collision
        if mx < 0 or my < 0 or mx >= MAP_W or my >= MAP_H:
            return True

        if MAP[my][mx] == 1:
            return True

    return False