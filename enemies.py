"""
enemies.py - Vijand klassen en rendering
"""

import pygame
from math import atan2, hypot, cos, sin, tan, pi

from config import SCREEN, WIDTH, HEIGHT, FOV, MAX_DEPTH, PROJ_DIST, SPRITE_SIZE, NUM_RAYS, MIN_DIST
from vector import Vector
from map_loader import map_to_cord, cord_to_map, is_in_wall


class Enemy:
    def __init__(self, health, damage, speed, enemy_type, x, y, size):
        self.health = health
        self.speed = speed
        self.pos = Vector(x, y)
        self.damage = damage

        sprite_path = f"assets/enemies/{enemy_type}.png"
        self.sprite = pygame.image.load(sprite_path).convert_alpha()

        # Cache voor sprite scaling
        self._cached_scale = None
        self._cached_dist = -1

        self.size = size

    def get_render_data_fast(self, player_pos, player_angle, wall_distances):
        """
        World-to-camera transformatie.
        Returnt (dist, screen_x, angle) of (None, None, None) als niet zichtbaar
        """
        # Vector van speler naar enemy
        dx = self.pos.x - player_pos.x
        dy = self.pos.y - player_pos.y

        # Bereken hoek naar enemy in wereldcoordinaten
        world_angle = atan2(dy, dx)

        # Relatieve hoek tot speler kijkrichting
        rel_angle = world_angle - player_angle

        # Normaliseer naar [-pi, pi]
        while rel_angle > pi:
            rel_angle -= 2 * pi
        while rel_angle < -pi:
            rel_angle += 2 * pi

        # Niet zichtbaar buiten FOV
        if abs(rel_angle) > FOV / 2:
            return None, None, None

        # Echte afstand (hypot)
        dist = hypot(dx, dy)

        # Te ver weg
        if dist > MAX_DEPTH or dist < MIN_DIST:
            return None, None, None

        # Projectie: screen_x = center + tan(rel_angle) * PROJ_DIST
        screen_x = WIDTH / 2 + tan(rel_angle) * PROJ_DIST

        # Ray nummer
        ray_num = int((screen_x / WIDTH) * NUM_RAYS)

        # Bounds check
        if ray_num < 0 or ray_num >= NUM_RAYS:
            return None, None, None

        # Check of sprite voor de muur staat op deze ray
        if dist >= wall_distances[ray_num]:
            return None, None, None

        return dist, screen_x, rel_angle

    def render_fast(self, dist, screen_x):
        """Render sprite op gegeven afstand en scherm x positie"""
        # Scale sprite op basis van afstand
        sprite_h = SPRITE_SIZE * PROJ_DIST / dist

        # Cache check
        if int(dist) != self._cached_dist:
            self._cached_scale = pygame.transform.scale(
                self.sprite, (int(sprite_h), int(sprite_h))
            )
            self._cached_dist = int(dist)

        # Centreer sprite
        draw_x = screen_x - sprite_h / 2
        draw_y = HEIGHT / 2 - sprite_h / 2

        SCREEN.blit(self._cached_scale, (draw_x, draw_y))

    def is_player_los(self, player_pos):
        # Vector van enemy naar speler
        dx = player_pos.x - self.pos.x
        dy = player_pos.y - self.pos.y

        # Bereken hoek naar player in wereldcoordinaten
        world_angle = atan2(dy, dx)
        # Echte afstand (hypot)
        dist = hypot(dx, dy)

        # Te ver weg
        if dist > MAX_DEPTH:
            return False, dist
        i = 0
        while i<dist:
            i += 2
            ray_pos = Vector(self.pos.x + i*cos(world_angle), self.pos.y + i*sin(world_angle))
            r_pos_m = cord_to_map(ray_pos)
            if is_in_wall(r_pos_m):
                return False, dist
        return True, dist

    def move_towards(self, pos):
        dx = pos.x - self.pos.x
        dy = pos.y - self.pos.y
        angle = atan2(dy, dx)
        self.pos += Vector(self.speed * cos(angle), self.speed * sin(angle))

    def find_path(self, player):
        player_pos = player.pos
        is_los, dist = self.is_player_los(player_pos)
        if is_los and dist >= MIN_DIST:
            self.move_towards(player_pos)
        elif dist < MIN_DIST:
            player.take_damage(self.damage)


    def is_hit(self, pos):
        dist = (self.pos - pos).norm()
        if dist < self.size:
            return True
        return False

    def take_dmg(self,dmg):
        self.health -= dmg
        print("Took",dmg, "damage. Has health:", self.health)



class Andrei(Enemy):
    def __init__(self, x, y, health=10, damage=1, speed=1.5, size=40):
        super().__init__(health, damage, speed, "andrei", x, y, size)