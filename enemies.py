from dda import *
from math import atan2, hypot

SPRITE_SIZE = 200



class Enemy:
    def __init__(self, health, speed, enemy, x, y):
        self.health = health
        self.speed = speed
        self.x = x
        self.y = y
        self.sprite = pygame.image.load("assets/enemies/" + enemy + ".png").convert_alpha()
    def render(self, player, player_angle):
        dx = self.x - player.x
        dy = self.y - player.y

        angle = atan2(dy, dx) - player_angle

        screen_x = WIDTH / 2 + tan(angle) * PROJ_DIST

        dist = hypot(dx, dy)

        sprite_h = SPRITE_SIZE * PROJ_DIST / dist

        scaled = pygame.transform.scale(self.sprite, (sprite_h, sprite_h))
        screen.blit(scaled, (screen_x - sprite_h / 2, HEIGHT / 2 - sprite_h / 2))
class Andrei(Enemy):
    def __init__(self, x, y, health=10, speed=10):
        super().__init__(health, speed, "andrei", x, y)



