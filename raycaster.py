"""
raycaster.py - DDA raycasting algoritme voor 3D rendering
"""

import pygame
from math import sin, cos, tan, pi

from config import (
    SCREEN, WIDTH, HEIGHT, TILE_SIZE,
    NUM_RAYS, MAX_DEPTH, DELTA_ANGLE, PROJ_DIST, SCALE
)
from map_loader import cord_to_map, map_to_cord, hit_wall, MAP
from vector import Vector

# Texture loading
wall_tex = pygame.image.load("assets/muur.jpeg").convert()
wall_tex = pygame.transform.scale(wall_tex, (TILE_SIZE, TILE_SIZE))

floor_tex = pygame.image.load("assets/floor.jpeg").convert()
floor_tex = pygame.transform.scale(floor_tex, (TILE_SIZE, TILE_SIZE))

sign = lambda x: 1 if x >= 0 else -1


def gnc(a, sg):
    """
    Get Next Cell - bepaal de volgende grid coördinaat
    in de richting van het teken (sg = sign)
    """
    if a % 1 == 0:
        return a + sg
    if sg == 1:
        return int(a) + 1
    else:
        return int(a)


def norm_angle(angle):
    """Normaliseer hoek naar [-pi, pi] bereik"""
    angle %= (2 * pi)
    if angle > pi:
        angle -= 2 * pi
    return angle

def append_z_index(p_pos, r_pos, player_angle, angle, ray, Z_index):
    """Teken een verticale muur slice op het scherm"""
    dist = ((p_pos.x - r_pos.x) ** 2 + (p_pos.y - r_pos.y) ** 2) ** 0.5
    dist *= cos(player_angle - angle)
    Z_index.append({"type": "wall", "dist": dist, "arg": ray})
    return Z_index

def draw_wall(dist, ray):
    wall_height = TILE_SIZE * PROJ_DIST / dist
    y = HEIGHT / 2 - wall_height / 2
    col_w = WIDTH // NUM_RAYS
    column_x = ray * col_w

    # Distance-based shading
    shade = max(0, min(255, 255 - int(dist * 255 / MAX_DEPTH)))
    color = (shade, shade, shade)
    pygame.draw.rect(SCREEN, color, (column_x, y, col_w, wall_height))


def dda(player_pos, player_angle):
    """
    Digital Differential Analysis raycasting.
    Returnt lijst van muur afstanden per ray voor sprite sorting.
    """
    wall_distances = []  # Alleen afstanden, geen dictionaries!

    for ray in range(NUM_RAYS):
        angle = player_angle - pi / 4 + (ray + 0.5) * DELTA_ANGLE
        ray_pos = Vector(player_pos.x, player_pos.y)

        sina = sin(angle)
        cosa = cos(angle)

        if cosa != 0 and sina != 0:
            tana = tan(angle)
            cota = 1 / tana
        else:
            tana = 0
            cota = 0

        s_x = sign(cosa)
        s_y = sign(sina)
        ray_pos = cord_to_map(ray_pos)

        while True:
            x = gnc(ray_pos.x, s_x)
            y = gnc(ray_pos.y, s_y)
            dx = x - ray_pos.x
            dy = y - ray_pos.y

            if cosa != 0 and sina != 0:
                dnx = abs(dx / cosa)
                dny = abs(dy / sina)

                if dnx >= dny:
                    dx = dy * cota
                    x = ray_pos.x + dx
                else:
                    dy = dx * tana
                    y = ray_pos.y + dy
            else:
                if cosa == 0:
                    y = ray_pos.y
                else:
                    x = ray_pos.x

            ray_pos = Vector(x, y)

            if hit_wall(ray_pos):
                ray_pos = map_to_cord(ray_pos)

                # Bereken afstand
                dist = ((player_pos.x - ray_pos.x) ** 2 +
                        (player_pos.y - ray_pos.y) ** 2) ** 0.5
                dist *= cos(player_angle - angle)  # Fisheye correctie

                # Sla op voor sprite sorting, teken direct
                wall_distances.append(dist)
                draw_wall(dist, ray)
                break

    return wall_distances