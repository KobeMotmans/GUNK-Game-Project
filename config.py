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
MAP_PATH = ["assets/floor_5.png", "assets/floor_3.png","assets/floor_2.png","assets/floor_1.png","assets/floor_0.png"]
MAX_LEVEL = len(MAP_PATH)-1
START_ANGLES = [-pi/2, 0, 0, pi/2, -pi/2]
ELEV_SPEED = 10

# Raycasting instellingen
FOV = pi / 2
MAX_DEPTH = 1000
PROJ_DIST = (WIDTH / 2) / (pi / 4)  # tan(FOV/2) = tan(pi/4) = 1
NUM_RAYS = 0
DELTA_ANGLE = 0
def set_resolution(quality: str):
    global NUM_RAYS, DELTA_ANGLE
    divisor = 4 if quality == "high" else 8
    NUM_RAYS = WIDTH // divisor
    DELTA_ANGLE = FOV / NUM_RAYS

# Speler instellingen
PLAYER_RADIUS = 10
PLAYER_SPEED = 6
PLAYER_ROT_SPEED = 0.0007

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

FONT = 'ocraextended'

SCREEN_FLASH = pygame.transform.scale(pygame.image.load("assets/Damage_Flash.png").convert_alpha(), (WIDTH, HEIGHT))
SCREEN_DEAD = pygame.transform.scale(pygame.image.load("assets/dead.png").convert_alpha(), (WIDTH, HEIGHT))
BILAL = pygame.transform.scale(pygame.image.load("assets/bilal.png").convert_alpha(), (200, 200))

VICTORY_SCREEN = pygame.transform.scale(pygame.image.load("assets/victory.png").convert_alpha(), (WIDTH, HEIGHT))


DAMAGE_FLASH = SCREEN_FLASH.copy()
DAMAGE_FLASH.fill((255,0,0), special_flags=pygame.BLEND_MULT)

AMMO_FLASH = SCREEN_FLASH.copy()
AMMO_FLASH.fill((255,215,0), special_flags=pygame.BLEND_MULT)

KEYCARD_FLASH = SCREEN_FLASH.copy()
KEYCARD_FLASH.fill((0,0,255), special_flags=pygame.BLEND_MULT)

HEALTH_FLASH = SCREEN_FLASH.copy()
HEALTH_FLASH.fill((0,255,0), special_flags=pygame.BLEND_MULT)

#Enemy instellingen
AGGRO_DIST = 1000

