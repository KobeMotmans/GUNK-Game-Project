"""
config.py - Centrale configuratie en constanten voor het spel
"""

import pygame
from math import pi

# Pygame init voor display info
pygame.init()
infoObject = pygame.display.Info()

# Scherm instellingen
WIDTH = infoObject.current_w
HEIGHT = infoObject.current_h - 50
SCREEN = pygame.display.set_mode((WIDTH, HEIGHT))

# Map instellingen
TILE_SIZE = 100
MAP_PATH = ["assets/floor_0.png", "assets/map_level_2.png","assets/lvl3.png"]
MAX_LEVEL = len(MAP_PATH)-1
START_ANGLES = [4, pi, 0]
ELEV_SPEED = 10

# Raycasting instellingen
FOV = pi / 2
MAX_DEPTH = 1000
PROJ_DIST = (WIDTH / 2) / (pi / 4)  # tan(FOV/2) = tan(pi/4) = 1
NUM_RAYS = 0
DELTA_ANGLE = 0
def set_resolution(quality: str):
    """Update raycasting constants. quality = 'high' or 'low'"""
    global NUM_RAYS, DELTA_ANGLE
    divisor = 4 if quality == "high" else 8
    NUM_RAYS = WIDTH // divisor
    DELTA_ANGLE = FOV / NUM_RAYS

# Speler instellingen
PLAYER_RADIUS = 10
PLAYER_SPEED = 6
PLAYER_ROT_SPEED = 0.001

START_HEALTH = 10

# Sprite instellingen
SPRITE_SIZE = 100
MIN_DIST = 40

# Wapen instellingen
WEAPON_SIZE = (300, 300)
WEAPON_OFFSET_X = 0.04  # 4% van schermbreedte

#Object instellingen
HEALTH_CHANCE = 0.20
HEALTH_REGEN = 2

START_AMMO = 100
AMMO_CAP = 200

SCREEN_FLASH = pygame.transform.scale(pygame.image.load("assets/Damage_Flash.png").convert_alpha(), (WIDTH, HEIGHT))
SCREEN_DEAD = pygame.transform.scale(pygame.image.load("assets/dead.png").convert_alpha(), (WIDTH, HEIGHT))
DAMAGE_FLASH = SCREEN_FLASH.copy()
DAMAGE_FLASH.fill((255,0,0), special_flags=pygame.BLEND_MULT)

AMMO_FLASH = SCREEN_FLASH.copy()
AMMO_FLASH.fill((255,215,0), special_flags=pygame.BLEND_MULT)

KEYCARD_FLASH = SCREEN_FLASH.copy()
KEYCARD_FLASH.fill((0,0,255), special_flags=pygame.BLEND_MULT)

HEALTH_FLASH = SCREEN_FLASH.copy()
HEALTH_FLASH.fill((0,255,0), special_flags=pygame.BLEND_MULT)

#Enemy instellingen
AGGRO_DIST = 30

