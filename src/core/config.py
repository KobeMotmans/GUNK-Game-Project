"""
config.py - Centrale configuratie en constanten voor het spel
"""

import os
import pygame
from math import pi, tan
from .paths import asset_path, resolve_asset
from .theme import theme

# ── Display initialisatie (headless-vriendelijk) ─────────────
# Zet GUNK_HEADLESS=1 in de omgeving om pygame display over te slaan.
# Gebruikt door run_server.py om geen venster te openen.
_HEADLESS = os.environ.get("GUNK_HEADLESS") == "1"

_resolution_quality = "high"

def set_resolution(quality: str):
    global _resolution_quality, NUM_RAYS, DELTA_ANGLE
    _resolution_quality = quality
    if _HEADLESS:
        return
    divisor = 4 if quality == "high" else 8
    NUM_RAYS = WIDTH // divisor
    DELTA_ANGLE = FOV / NUM_RAYS

def resize_display(w, h):
    global WIDTH, HEIGHT, SCREEN, PROJ_DIST, NUM_RAYS, DELTA_ANGLE
    global SCREEN_FLASH, SCREEN_DEAD, VICTORY_SCREEN, TUTORIAL
    global DAMAGE_FLASH, AMMO_FLASH, KEYCARD_FLASH, HEALTH_FLASH
    if _HEADLESS:
        return
    WIDTH = w
    HEIGHT = h
    SCREEN = pygame.display.set_mode((w, h), pygame.RESIZABLE | pygame.DOUBLEBUF)
    PROJ_DIST = int((WIDTH / 2) / tan(FOV / 2))
    set_resolution(_resolution_quality)

    SCREEN_FLASH = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.damage_flash", "textures/ui/Damage_Flash.png"))).convert_alpha(), (WIDTH, HEIGHT))
    SCREEN_DEAD = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.dead", "textures/ui/dead.png"))).convert_alpha(), (WIDTH, HEIGHT))
    TUTORIAL = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.tutorial", "textures/ui/bilal.png"))).convert_alpha(), (200, 200))
    VICTORY_SCREEN = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.victory", "textures/ui/victory.png"))).convert_alpha(), (WIDTH, HEIGHT))

    DAMAGE_FLASH = SCREEN_FLASH.copy()
    DAMAGE_FLASH.fill((255,0,0), special_flags=pygame.BLEND_MULT)
    AMMO_FLASH = SCREEN_FLASH.copy()
    AMMO_FLASH.fill((255,215,0), special_flags=pygame.BLEND_MULT)
    KEYCARD_FLASH = SCREEN_FLASH.copy()
    KEYCARD_FLASH.fill((0,0,255), special_flags=pygame.BLEND_MULT)
    HEALTH_FLASH = SCREEN_FLASH.copy()
    HEALTH_FLASH.fill((0,255,0), special_flags=pygame.BLEND_MULT)

if not _HEADLESS:
    pygame.init()
    infoObject = pygame.display.Info()
    WIDTH = infoObject.current_w
    HEIGHT = infoObject.current_h - 50
    SCREEN = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE | pygame.DOUBLEBUF)
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
ELEV_TIME = 30

# Raycasting instellingen
FOV = pi / 2
MAX_DEPTH = 1000
PROJ_DIST = int((WIDTH / 2) / tan(FOV / 2))  # tan(FOV/2) = tan(pi/4) = 1
NUM_RAYS = 0
DELTA_ANGLE = 0

# Speler instellingen
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
WEAPON_OFFSET_X = 0.04  # 4% van schermbreedte

#Object instellingen
HEALTH_CHANCE = 0.20

SFX_VOLUME = 0.3
HEALTH_REGEN = 2

START_AMMO = 100
AMMO_CAP = 200


if not _HEADLESS:
    SCREEN_FLASH = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.damage_flash", "textures/ui/Damage_Flash.png"))).convert_alpha(), (WIDTH, HEIGHT))
    SCREEN_DEAD = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.dead", "textures/ui/dead.png"))).convert_alpha(), (WIDTH, HEIGHT))
    TUTORIAL = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.tutorial", "textures/ui/bilal.png"))).convert_alpha(), (200, 200))

    VICTORY_SCREEN = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.victory", "textures/ui/victory.png"))).convert_alpha(), (WIDTH, HEIGHT))


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
    TUTORIAL = None
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

