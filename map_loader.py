"""
map_loader.py - Laadt en beheert de game map
"""

from PIL import Image
from config import TILE_SIZE, MAP_PATH

color_to_number = {
    (255, 255, 255): 0, #Open space
    (0,0,0): 1, # Wall
    (255, 0, 0): 2, # Exit
    (0, 255, 0): 3, #Enemy
    (0,0,255): 4, #Player Spawn
    (255, 255, 0): 5, #Keycard
    (0, 255, 255): 6 #Ammo
}


def cord_to_map(cord):
    """Converteer pixel coördinaat naar map grid coördinaat"""
    return cord / TILE_SIZE


def map_to_cord(mapcord):
    """Converteer map grid coördinaat naar pixel coördinaat"""
    return mapcord * TILE_SIZE

def png_to_list_fast(path):
    """Converteer een PNG afbeelding naar een 2D grid (0 = leeg, 1 = muur)"""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    map_list = []
    spawns = {
        "player": (150,150), #Default location
        "enemies": [],
        "ammo": [],
        "keycard": (0,0),
        "end_point": (0,0)
    }
    for y in range(h):
        map_list.append([])
        for x in range(w):
            number = color_to_number[img.getpixel((x, y))]
            map_list[y].append(number)
            x_center = map_to_cord(x) + TILE_SIZE/2 #Center object in tile
            y_center = map_to_cord(y) + TILE_SIZE/2
            if number == 2:
                spawns["end_point"] = (x_center,y_center)
            elif number == 3:
                spawns["enemies"].append((x_center,y_center))
            elif number == 4:
                spawns["player"] = (x_center,y_center)
            elif number == 5:
                spawns["keycard"]= (x_center,y_center)
            elif number == 6:
                spawns["ammo"].append((x_center,y_center))

    return map_list, spawns

# Laad de map bij startup
MAP ,SPAWNS = png_to_list_fast(MAP_PATH)
MAP_W = len(MAP[0])
MAP_H = len(MAP)


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


def is_in_wall(pos):
    pos = pos // 1
    if MAP[pos.y][pos.x] == 1:
        return True
    return False