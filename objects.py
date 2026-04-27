import pygame
from math import atan2, hypot, cos, sin, tan, pi

import config
from config import SCREEN, WIDTH, HEIGHT, FOV, MAX_DEPTH, PROJ_DIST, SPRITE_SIZE, MIN_DIST, START_HEALTH, HEALTH_REGEN
from vector import Vector

class RenderObject:
    def __init__(self, type, x, y):
        self.pos = Vector(x, y)
        self.type = type
        sprite_path = f"assets/{type}.png"
        self.sprite = pygame.image.load(sprite_path).convert_alpha()
        # Cache voor sprite scaling
        self._cached_scale = None
        self._cached_dist = -1
        self.dist = 100000000

        self.size = SPRITE_SIZE
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

        # Echte afstand (hypot)
        self.dist = hypot(dx, dy)
        is_hit = False
        if self.dist < MIN_DIST:
            is_hit = True

        # Niet zichtbaar buiten FOV
        if abs(rel_angle) > FOV / 2:
            return None, None, None, is_hit

        # Te ver weg
        if self.dist > MAX_DEPTH or self.dist < MIN_DIST:
            return None, None, None, is_hit

        # Projectie: screen_x = center + tan(rel_angle) * PROJ_DIST
        screen_x = WIDTH / 2 + tan(rel_angle) * PROJ_DIST

        # Ray nummer
        ray_num = int((screen_x / WIDTH) * config.NUM_RAYS)

        # Bounds check
        if ray_num < 0 or ray_num >= config.NUM_RAYS:
            return None, None, None, is_hit

        # Check of sprite voor de muur staat op deze ray
        if self.dist >= wall_distances[ray_num]:
            return None, None, None, is_hit

        return self.dist, screen_x, rel_angle, is_hit

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
        if hasattr(self, "draw_health_bar"):
            self.draw_health_bar(sprite_h, draw_x, draw_y)

        SCREEN.blit(self._cached_scale, (draw_x, draw_y))

    def interact(self, player):
        pass

class PickupObject(RenderObject):
    def __init__(self, type, x, y):
        super().__init__(type, x, y)
    def interact(self, player):
        if self.type == "objects/ammo":
            player.ammo = min(player.ammo+50, 200)
            pygame.mixer.Sound("assets/ammo.mp3").play()
        if self.type == "objects/keycard":
            player.got_keycard = True
            pygame.mixer.Sound("assets/key.mp3").play()
        if self.type == "objects/exit":
            if player.got_keycard:
                player.level += 0.5
            else:
                SCREEN.blit(pygame.font.SysFont('ocraextended', 80, True).render("NO KEYCARD", True,'green'),(WIDTH/2-200,HEIGHT/2))
                return "fail"
        if self.type == "objects/health":
            player.health = min(player.health+HEALTH_REGEN, START_HEALTH)
            pygame.mixer.Sound("assets/drink.mp3").play()
        return "succes"
                





