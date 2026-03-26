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
MAP_PATH = "assets/map.png"

# Raycasting instellingen
FOV = pi / 2
NUM_RAYS = WIDTH // 6
MAX_DEPTH = 1000
DELTA_ANGLE = FOV / NUM_RAYS
SCALE = WIDTH // NUM_RAYS
PROJ_DIST = (WIDTH / 2) / (pi / 4)  # tan(FOV/2) = tan(pi/4) = 1

# Speler instellingen
PLAYER_RADIUS = 10
PLAYER_SPEED = 6
PLAYER_ROT_SPEED = 0.001

# Sprite instellingen
SPRITE_SIZE = 100
MIN_DIST = 40

# Wapen instellingen
WEAPON_SIZE = (300, 300)
WEAPON_OFFSET_X = 0.04  # 4% van schermbreedte

START_AMMO = 100
AMMO_CAP = 200

SCREEN_FLASH = pygame.transform.scale(pygame.image.load("assets/Damage_Flash.png").convert_alpha(), (WIDTH, HEIGHT))
DAMAGE_FLASH = SCREEN_FLASH.copy()
DAMAGE_FLASH.fill((255,0,0), special_flags=pygame.BLEND_MULT)

AMMO_FLASH = SCREEN_FLASH.copy()
AMMO_FLASH.fill((255,215,0), special_flags=pygame.BLEND_MULT)

KEYCARD_FLASH = SCREEN_FLASH.copy()
KEYCARD_FLASH.fill((0,0,255), special_flags=pygame.BLEND_MULT)

