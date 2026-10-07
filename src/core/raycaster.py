"""
raycaster.py - DDA raycasting algoritme voor 3D rendering
"""

import pygame
from math import sin, cos, tan, pi

from . import config as cfg
from .config import TILE_SIZE, MAX_DEPTH, PROJ_DIST
from .map_loader import cord_to_map, map_to_cord, hit_wall, wall_face
from .vector import Vector
from ..assets.wall_textures import strips as wall_strips

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

def draw_wall(dist, ray, y_offset=0, tile_value=1, u=0.0):
    """Tekent één muurkolom, getextureerd.

    Alles wat duur is - de verdunning voor afstandslicht, het snijden in
    kolommen, het schalen naar schermformaat - gebeurt bij het laden van de
    tekstuur (zie assets/wall_textures.py). Hier blijft één tabelindex, één
    transform.scale en één blit over. Per-pixel bemonsteren zou ~90 ms kosten.

    dist      afstand tot de muur (al gecorrigeerd voor vissenoog)
    ray       raynummer, bepaalt de schermkolom
    y_offset  cam-bob, verschuift de kolom verticaal
    tile_value tegelwaarde van de geraakte muur, kiest de tekstuur
    u         positie op het muurvlak in 0..1, kiest de tekstuurkolom
    """
    wall_height = TILE_SIZE * PROJ_DIST / dist
    col_w = cfg.WIDTH // cfg.NUM_RAYS
    column_x = ray * col_w
    y = cfg.HEIGHT / 2 - wall_height / 2 + y_offset

    tex_w, tex_h, all_strips = wall_strips(tile_value)
    band = int(dist * cfg.WALL_SHADE_BANDS / MAX_DEPTH)
    if band >= cfg.WALL_SHADE_BANDS:
        band = cfg.WALL_SHADE_BANDS - 1
    elif band < 0:
        band = 0
    col = int(u * tex_w)
    if col >= tex_w:
        col = tex_w - 1
    strip = all_strips[band * tex_w + col]

    top = y
    bottom = y + wall_height
    y0 = 0 if top < 0 else int(top)
    y1 = cfg.HEIGHT if bottom >= cfg.HEIGHT else int(bottom) + 1
    if y1 <= y0:
        return

    if y0 > top or y1 < bottom:
        # De muur is hoger dan het scherm. Zonder deze bijsnede zou pygame een
        # oppervlak van wall_height pixels moeten aanmaken - dicht op een muur
        # zijn dat tienduizenden pixels. We knippen de strip in plaats van hem
        # op die onmogelijke hoogte te schalen.
        sy0 = int((y0 - top) * tex_h / wall_height)
        sy1 = int((y1 - top) * tex_h / wall_height)
        if sy0 < 0:
            sy0 = 0
        elif sy0 > tex_h - 1:
            sy0 = tex_h - 1
        if sy1 <= sy0:
            sy1 = sy0 + 1
        elif sy1 > tex_h:
            sy1 = tex_h
        strip = strip.subsurface((0, sy0, 1, sy1 - sy0))

    cfg.SCREEN.blit(pygame.transform.scale(strip, (col_w, y1 - y0)),
                    (column_x, y0))


def dda(player_pos, player_angle, y_offset=0):
    """
    Digital Differential Analysis raycasting.
    Returnt lijst van muur afstanden per ray voor sprite sorting.
    """
    wall_distances = []  # Alleen afstanden, geen dictionaries!

    for ray in range(cfg.NUM_RAYS):
        angle = player_angle - pi / 4 + (ray + 0.5) * cfg.DELTA_ANGLE
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
                # Vóór de omrekening naar pixels: de DDA staat dan precies op
                # de muurgrens, dus dit is het punt waarop we de tekstuur
                # bemonsteren.
                tile_value, u = wall_face(ray_pos)
                ray_pos = map_to_cord(ray_pos)

                # Bereken afstand
                dist = ((player_pos.x - ray_pos.x) ** 2 +
                        (player_pos.y - ray_pos.y) ** 2) ** 0.5
                dist *= cos(player_angle - angle)  # Fisheye correctie

                # Sla op voor sprite sorting, teken direct
                wall_distances.append(dist)
                draw_wall(dist, ray, y_offset=y_offset,
                          tile_value=tile_value, u=u)
                break

    return wall_distances
        