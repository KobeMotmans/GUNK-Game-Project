import pygame
from math import atan2, hypot, cos, sin, tan, pi

from config import SCREEN, WIDTH, HEIGHT, FOV, MAX_DEPTH, PROJ_DIST, SPRITE_SIZE, NUM_RAYS, MIN_DIST
from vector import Vector

class RenderInteractObject:
    def __init__(self, x, y, sprite_path, size):
        self.pos = Vector(x, y)
        sprite_path = sprite_path
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


class PickupObject(RenderInteractObject):
    def __init__(self, x, y):
        super().__init__(x, y)
