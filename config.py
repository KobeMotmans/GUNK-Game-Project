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
HEIGHT = infoObject.current_h
SCREEN = pygame.display.set_mode((WIDTH, HEIGHT))

# Map instellingen
TILE_SIZE = 100
MAP_PATH = "assets/map.png"

# Raycasting instellingen
FOV = pi / 2
NUM_RAYS = WIDTH // 4
MAX_DEPTH = 1000
DELTA_ANGLE = FOV / NUM_RAYS
SCALE = WIDTH // NUM_RAYS
PROJ_DIST = (WIDTH / 2) / (pi / 4)  # tan(FOV/2) = tan(pi/4) = 1

# Speler instellingen
PLAYER_RADIUS = 10
PLAYER_SPEED = 3
PLAYER_ROT_SPEED = 0.001

# Sprite instellingen
SPRITE_SIZE = 50

# Wapen instellingen
WEAPON_SIZE = (300, 300)
WEAPON_OFFSET_X = 0.04  # 4% van schermbreedte