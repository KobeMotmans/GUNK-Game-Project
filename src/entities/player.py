"""
player.py - Speler klasse met movement en rotatie
"""
import pygame
from math import sin, cos, pi

from ..core.config import PLAYER_SPEED, PLAYER_ROT_SPEED, START_HEALTH
from ..core.map_loader import will_collide
from ..core.vector import Vector


class Player:
    def __init__(self, x=150, y=150, health=START_HEALTH, angle=None):
        self.pos = Vector(x, y)
        from math import pi
        self.angle = angle if angle is not None else -pi / 2
        self.health = health
        self.inv_time = 0
        self.death = False
        self.score = 0
        self.got_keycard = False
        self.door_pos = 0

    def rotate(self, direction):
        """
        Roteer speler. direction: -1 voor links, 1 voor rechts
        """
        self.angle += direction * PLAYER_ROT_SPEED
        self.angle %= 2 * pi

    def move(self, direction, speed=PLAYER_SPEED):
        """
        Beweeg speler vooruit (1) of achteruit (-1)
        Checkt collision per as (slide along walls)
        """
        dx, dy = 0, 0
        if direction == "up" or direction == "down":
            if direction == "up":
                direction = 1
            else:
                direction = -1
            dx += cos(self.angle) * direction
            dy += sin(self.angle) * direction
        if direction == "left" or direction == "right":
            if direction == "left":
                direction = -1
            else:
                direction = 1
            dx += cos(self.angle+pi/2) * direction
            dy += sin(self.angle+pi/2) * direction
        normalised = Vector(dx, dy).normalize() * speed
        dx, dy = normalised.x, normalised.y

        # Probeer X beweging
        new_x = self.pos.x + dx
        if not will_collide(new_x, self.pos.y):
            self.pos.x = new_x

        # Probeer Y beweging
        new_y = self.pos.y + dy
        if not will_collide(self.pos.x, new_y):
            self.pos.y = new_y

    def get_pos(self):
        return self.pos

    def get_angle(self):
        return self.angle

    def take_damage(self, damage, game):
        if self.inv_time == 0:
            self.inv_time = 60
            game.global_health -= damage
            game._health_delta -= damage
            game.sounds["damage"].set_volume(game.sfx_volume)
            game.sounds["damage"].play()
            if game.global_health <= 0:
                pygame.mixer.stop()
                game.sounds["damage"].set_volume(game.sfx_volume)
                game.sounds["damage"].play()
                self.death = True
                

    def tick(self):
        if self.inv_time > 0:
            self.inv_time -= 1


