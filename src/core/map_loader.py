"""
map_loader.py - Laadt en beheert de game map
"""

from PIL import Image
from .config import (TILE_SIZE, WALL_TEXTURES, kaart_voor, DEFAULT_GAMEMODE)

color_to_number = {
    (255, 255, 255): 0, #Open space
    (0,0,0): 1, # Wall
    (0, 255, 0): 2, # Exit
    (255, 0, 0): 3, #Enemy
    (0, 255, 255): 4, #Player Spawn
    (0, 0, 255): 5, #Keycard
    (255, 255, 0): 6, #Ammo
    (255, 0, 255): 7, #Final Boss
    # Health. Oranje, en voor zover bekend nergens anders in gebruik: de
    # health die in de campaign verschijnt is een drop van een dode vijand
    # (HEALTH_CHANCE in game.py en server_game.py) en kijkt nooit naar een
    # kleur. Een kaart zonder H-tegel levert dus een lege lijst op en
    # verandert verder niets. Zie SURVIVAL.md, openstaande keuze 2.
    (255, 128, 0): 8, #Health
}

# ── Wat telt als muur? ──────────────────────────────────────────────
# Dit is hét antwoord op "is dit een muur?", afgeleid van de tekstuur-
# tabel in config. Collision, raycaster, minimap en padvinding vragen hier
# allemaal naar, zodat er niet zes plekken zijn die over muurtegels
# beslissen: een nieuwe muursoort toevoegen is één regel in
# config.WALL_TEXTURES plus één kleur in color_to_number.
WALL_VALUES = frozenset(WALL_TEXTURES)


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
        "keycard": [],
        # Oranje tegels. Staat er geen in de kaart dan blijft de lijst leeg,
        # en dat is het gewone geval: de campaign zet health willekeurig.
        "health": [],
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
                spawns["keycard"].append((x_center,y_center))
            elif number == 6:
                spawns["ammo"].append((x_center,y_center))
            elif number == 7:
                spawns["final_boss"] = (x_center, y_center)
            elif number == 8:
                spawns["health"].append((x_center, y_center))
    return map_list, spawns, w, h

class MapClass:
    # Stand van de dev-console. Als klasseattribuut staat hij er altijd,
    # ook als er nog geen Game bestaat (server, tests, headless).
    noclip = False

    def __init__(self, map_level = 0):
        self.map_level = map_level
        # Standaardmodus: dit object wordt één keer bij import aangemaakt,
        # nog vóór er een mode gekozen is. Elke mode wisselt daarna de kaart
        # zelf via kaart_voor(); dit is alleen de begintoestand.
        kaart, hoek = kaart_voor(DEFAULT_GAMEMODE, map_level)
        self.MAP, self.SPAWNS, self.width, self.height = png_to_list_fast(kaart)
        self.start_angle = hoek
        
M = MapClass()

# Laad de map bij startup

def hit_wall(pos, allow_all=False):
    """Check of een positie op een muur ligt"""
    MAP = M.MAP
    if M.noclip:
        return False
    if pos.x % 1 == 0:
        x = int(pos.x)
        y = int(pos.y)
        if MAP[y][x - 1] in WALL_VALUES or MAP[y][x] in WALL_VALUES:
            return True
    elif pos.y % 1 == 0:
        x = int(pos.x)
        y = int(pos.y)
        if MAP[y - 1][x] in WALL_VALUES or MAP[y][x] in WALL_VALUES:
            return True
    return False


def wall_face(pos):
    """Welke muur raakte de ray, en waar op dat vlak?

    Keert dezelfde twee-cellen-check terug als hit_wall(), zodat de
    raycaster en de collision nooit over een verschillende muur
    discussieren. Returnt (tegelwaarde, u in 0..1 over de breedte van het
    muurvlak) - de coördinaat die de tekstuurkolom bepaalt.

    `pos` is in map-coördinaten, dus precies zoals de DDA hem heeft vóór
    hij naar pixels wordt omgerekend: precies één van beide assen is een
    geheel getal (de grens die is overgestoken).
    """
    MAP = M.MAP
    x = int(pos.x)
    y = int(pos.y)
    if pos.x % 1 == 0:
        # Verticaal vlak: de muur loopt langs y, dus y is de tekstuur-as.
        # x - 1 eerst, net als hit_wall.
        for cx in ((x - 1, x) if x > 0 else (x,)):
            if 0 <= cx < len(MAP[y]) and MAP[y][cx] in WALL_VALUES:
                return MAP[y][cx], pos.y - y
    elif pos.y % 1 == 0:
        # Horizontaal vlak: de muur loopt langs x.
        for cy in ((y - 1, y) if y > 0 else (y,)):
            if 0 <= cy < len(MAP) and MAP[cy][x] in WALL_VALUES:
                return MAP[cy][x], pos.x - x
    # Randgeval (hoek of afgeronde coördinaat): val terug op de eerste
    # muur in de tabel. Er wordt getekend, dus er ís een muur.
    return next(iter(WALL_TEXTURES)), 0.0


def will_collide(nx, ny, radius=10):
    MAP = M.MAP
    MAP_W = len(MAP[0])
    MAP_H = len(MAP)
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

        if MAP[my][mx] in WALL_VALUES:
            return True

    return False


def is_in_wall(pos):
    MAP = M.MAP
    pos = pos // 1
    if MAP[pos.y][pos.x] in WALL_VALUES:
        return True
    return False