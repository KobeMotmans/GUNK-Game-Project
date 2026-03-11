"""
enemies.py - Vijand klassen en rendering
"""

import pygame
from math import atan2, hypot, cos, pi, sin, tan

from config import SCREEN, WIDTH, HEIGHT, FOV, MAX_DEPTH, PROJ_DIST, SPRITE_SIZE
from vector import Vector


class Enemy:
    def __init__(self, health, speed, enemy_type, x, y):
        self.health = health
        self.speed = speed
        self.pos = Vector(x, y)

        sprite_path = f"assets/enemies/{enemy_type}.png"
        self.sprite = pygame.image.load(sprite_path).convert_alpha()

    def get_render_data(self, player_pos, player_angle):
        """
        Bereken afstand en hoek voor rendering.
        Returnt (dist, angle) of (None, None) als niet zichtbaar.
        """
        dx = self.pos.x - player_pos.x
        dy = self.pos.y - player_pos.y

        # Hoek tot speler relatief aan kijkrichting
        angle = atan2(dy, dx) - player_angle
        if angle > pi:
            angle -= 2 * pi
        if angle < -pi:
            angle += 2 * pi

        # Niet zichtbaar buiten FOV
        if abs(angle) > FOV / 2:
            return None, None

        # Afstand met fisheye correctie
        dist = hypot(dx, dy)
        dist *= cos(angle)

        # Te ver weg
        if dist > MAX_DEPTH:
            return None, None

        return dist, angle


    def render(self, dist, angle):
        # Te ver weg = niet renderen
        if dist > MAX_DEPTH:
            return

        # Fix: tan(angle) = sin(angle)/cos(angle)
        screen_x = WIDTH / 2 + tan(angle) * PROJ_DIST

        # Scale sprite op basis van afstand
        sprite_h = SPRITE_SIZE * PROJ_DIST / dist
        scaled = pygame.transform.scale(self.sprite, (int(sprite_h), int(sprite_h)))

        # Centreer sprite
        draw_x = screen_x - sprite_h / 2
        draw_y = HEIGHT / 2 - sprite_h / 2

        SCREEN.blit(scaled, (draw_x, draw_y))


class Andrei(Enemy):
    def __init__(self, x, y, health=10, speed=10):
        super().__init__(health, speed, "andrei", x, y)