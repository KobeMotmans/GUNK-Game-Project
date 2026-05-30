"""
config.py - Centrale configuratie en constanten voor het spel
"""

import os
import pygame
from math import pi
from .paths import asset_path, resolve_asset

# ── Display initialisatie (headless-vriendelijk) ─────────────
# Zet GUNK_HEADLESS=1 in de omgeving om pygame display over te slaan.
# Gebruikt door run_server.py om geen venster te openen.
_HEADLESS = os.environ.get("GUNK_HEADLESS") == "1"

if not _HEADLESS:
    pygame.init()
    infoObject = pygame.display.Info()
    WIDTH = infoObject.current_w
    HEIGHT = infoObject.current_h - 50
    SCREEN = pygame.display.set_mode((WIDTH, HEIGHT))
else:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    WIDTH = 1920
    HEIGHT = 1080
    SCREEN = None

# Map instellingen
TILE_SIZE = 100
MAP_PATH = [asset_path("assets/textures/floor/floor_5.png"), asset_path("assets/textures/floor/floor_3.png"), asset_path("assets/textures/floor/floor_2.png"), asset_path("assets/textures/floor/floor_1.png"), asset_path("assets/textures/floor/floor_0.png")]
MAX_LEVEL = len(MAP_PATH)-1
START_ANGLES = [-pi/2, 0, 0, pi/2, -pi/2]
ELEV_SPEED = 10
ELEV_TIME = 120

# Raycasting instellingen
FOV = pi / 2
MAX_DEPTH = 1000
PROJ_DIST = (WIDTH / 2) / (pi / 4)  # tan(FOV/2) = tan(pi/4) = 1
NUM_RAYS = 0
DELTA_ANGLE = 0

def set_resolution(quality: str):
    global NUM_RAYS, DELTA_ANGLE
    if _HEADLESS:
        return
    divisor = 4 if quality == "high" else 8
    NUM_RAYS = WIDTH // divisor
    DELTA_ANGLE = FOV / NUM_RAYS

# Speler instellingen
PLAYER_RADIUS = 10
PLAYER_SPEED = 6
PLAYER_ROT_SPEED = 0.0008

START_HEALTH = 10

# Sprite instellingen
SPRITE_SIZE = 100
MIN_DIST = 40
ATTACK_DIST = 43

# Hoe vaak A* opnieuw berekend wordt (in frames)
PATHFIND_INTERVAL = 20

# Wapen instellingen
WEAPON_SIZE = (300, 300)
WEAPON_OFFSET_X = 0.04  # 4% van schermbreedte

#Object instellingen
HEALTH_CHANCE = 0.20

SFX_VOLUME = 0.3
HEALTH_REGEN = 2

START_AMMO = 100
AMMO_CAP = 200

FONT = asset_path('assets/font/ocraextended.ttf')
SILLY_FONT = asset_path('assets/font/Hyro.ttf')   # kept for direct font access; packs use pack_config("font")
    

MENU_BG = (70,70,70)

if not _HEADLESS:
    SCREEN_FLASH = pygame.transform.scale(pygame.image.load(asset_path("assets/textures/ui/Damage_Flash.png")).convert_alpha(), (WIDTH, HEIGHT))
    SCREEN_DEAD = pygame.transform.scale(pygame.image.load(resolve_asset("textures/ui/dead.png")).convert_alpha(), (WIDTH, HEIGHT))
    BILAL = pygame.transform.scale(pygame.image.load(asset_path("assets/textures/ui/bilal.png")).convert_alpha(), (200, 200))

    VICTORY_SCREEN = pygame.transform.scale(pygame.image.load(asset_path("assets/textures/ui/victory.png")).convert_alpha(), (WIDTH, HEIGHT))


    DAMAGE_FLASH = SCREEN_FLASH.copy()
    DAMAGE_FLASH.fill((255,0,0), special_flags=pygame.BLEND_MULT)

    AMMO_FLASH = SCREEN_FLASH.copy()
    AMMO_FLASH.fill((255,215,0), special_flags=pygame.BLEND_MULT)

    KEYCARD_FLASH = SCREEN_FLASH.copy()
    KEYCARD_FLASH.fill((0,0,255), special_flags=pygame.BLEND_MULT)

    HEALTH_FLASH = SCREEN_FLASH.copy()
    HEALTH_FLASH.fill((0,255,0), special_flags=pygame.BLEND_MULT)
else:
    SCREEN_FLASH = None
    SCREEN_DEAD = None
    BILAL = None
    VICTORY_SCREEN = None
    DAMAGE_FLASH = None
    AMMO_FLASH = None
    KEYCARD_FLASH = None
    HEALTH_FLASH = None

#Enemy instellingen
AGGRO_DIST = 1000

# Multiplayer instellingen
DEFAULT_PORT = 5555
MAX_PLAYERS = 4
ELEVATOR_WAIT_DIST = 200   # pixels van exit tot speler
ELEVATOR_WAIT_FRAMES = 90  # frames na "allemaal klaar" voor lift vertrekt

