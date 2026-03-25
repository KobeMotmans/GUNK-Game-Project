"""
enemies.py - Vijand klassen en rendering
"""

import pygame
from math import atan2, hypot, cos, sin, tan, pi

from config import SCREEN, WIDTH, HEIGHT, FOV, MAX_DEPTH, PROJ_DIST, SPRITE_SIZE, NUM_RAYS, MIN_DIST
from vector import Vector
from map_loader import map_to_cord, cord_to_map, is_in_wall
from objects import RenderObject


class Enemy(RenderObject):
    def __init__(self, health, damage, speed, enemy_type, x, y):
        super().__init__(f"enemies/{enemy_type}", x, y)
        self.health = health
        self.speed = speed
        self.damage = damage

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
    def __init__(self, x, y, health=10, damage=3, speed=3):
        super().__init__(health, damage, speed, "andrei", x, y)