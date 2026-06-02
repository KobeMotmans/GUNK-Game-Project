"""
enemies.py - Vijand klassen en rendering
"""

import pygame
from math import atan2, hypot, cos, sin

from ..core.config import SCREEN, WIDTH, HEIGHT, AGGRO_DIST, PATHFIND_INTERVAL, ATTACK_DIST, SFX_VOLUME, SPRITE_SIZE, PROJ_DIST
from ..core.vector import Vector
from ..core.paths import load_font, resolve_asset
from ..core.theme import theme
from .objects import RenderObject
from .enemy_ai import EnemyAI


class Enemy(EnemyAI, RenderObject):
    def __init__(self, health, damage, speed, enemy_type, x, y):
        self.path = f"enemies/{enemy_type}"
        super().__init__(self.path, x, y)
        self.max_health = health
        self.health = health
        self.speed = speed
        self.damage = damage
        self.spotted_player = False
        self.is_los = False
        self.target = None
        self._full_path = []
        self._path_timer = 0

    def draw_health_bar(self, sprite_h, draw_x, draw_y):
        health_ratio = max(0, self.health / self.max_health)

        if self.type == "enemies/final_boss":
            bar_width = theme.size("boss_hp.bar_w", WIDTH // 2)
            bar_height = theme.size("boss_hp.bar_h", 20)
            bar_x = theme.size("boss_hp.bar_x", WIDTH // 4)
            bar_y = theme.size("boss_hp.bar_y", 30)

            font = load_font(theme.size("boss_hp.name_font", 28), bold=True)
            label = font.render("Jan Lemeire", True, (255, 220, 0))
            SCREEN.blit(label, (bar_x + bar_width // 2 - label.get_width() // 2, bar_y - theme.pos("boss_hp.label_offset", 30)))

            pygame.draw.rect(SCREEN, (80, 0, 0), (bar_x, bar_y, bar_width, bar_height))

            color = (200, 0, 0) if health_ratio <= 0.25 else (200, 200, 0) if health_ratio <= 0.5 else (0, 200, 0)
            pygame.draw.rect(SCREEN, color, (bar_x, bar_y, int(bar_width * health_ratio), bar_height))
            return

        bar_width = sprite_h
        bar_height = sprite_h * 0.1
        bar_x = draw_x
        bar_y = draw_y - bar_height - theme.size("enemy_hp.bar_offset", 4)

        bg_rect = pygame.Rect(bar_x, bar_y, bar_width, bar_height)
        pygame.draw.rect(SCREEN, (120, 0, 0), bg_rect)

        if health_ratio > 0.5:
            color = (0, 200, 0)
        elif health_ratio > 0.25:
            color = (200, 200, 0)
        else:
            color = (200, 0, 0)

        fg_rect = pygame.Rect(bar_x, bar_y, bar_width * health_ratio, bar_height)
        pygame.draw.rect(SCREEN, color, fg_rect)
        pygame.draw.rect(SCREEN, (0, 0, 0), bg_rect, 1)

    def find_path(self, player, game, deal_damage=True, do_movement=True):
        player_pos = player.pos

        self.is_los, dist = self.is_in_los(player_pos)

        if dist > AGGRO_DIST:
            self.spotted_player = False

        if self.is_los:
            self.spotted_player = True
            self._full_path = []
            self.target = None

        if do_movement:
            if self.is_los and dist > ATTACK_DIST:
                self.move_towards(player_pos)

            if self.spotted_player and dist < AGGRO_DIST and not self.is_los:
                self._path_timer -= 1
                if not self.has_target() or self._path_timer <= 0:
                    path = self.A_star(player.pos)
                    if path:
                        self._full_path = path[1:]
                        self.target = path[0]
                    else:
                        self._full_path = []
                        self.target = None
                    self._path_timer = PATHFIND_INTERVAL

            if self.has_target() and not self.is_los:
                self.move_towards(self.target)

        if self.is_los and dist <= ATTACK_DIST:
            if deal_damage:
                player.take_damage(self.damage, game)

    def is_hit(self, pos):
        return (self.pos - pos).norm() < self.size

    def take_dmg(self, dmg):
        self.health -= dmg


class NormalEnemy(Enemy):
    def __init__(self, x, y, health=13, damage=3, speed=3):
        super().__init__(health, damage, speed, "normal_enemy", x, y)

class FastEnemy(Enemy):
    def __init__(self, x, y, health=6, damage=2, speed=5):
        super().__init__(health, damage, speed, "fast_enemy", x, y)

class TankEnemy(Enemy):
    def __init__(self, x, y, health=19, damage=2, speed=2):
        super().__init__(health, damage, speed, "tank_enemy", x, y)
        self.last_fire_time = 0

    def find_path(self, player, game, deal_damage=True, do_movement=True):
        player_pos = player.pos
        self.is_los, dist = self.is_in_los(player_pos)
        if self.is_los and dist >= TANK_ENEMY_ATTACK_DIST:
            result = super().find_path(player, game, deal_damage=False, do_movement=do_movement)
            now = pygame.time.get_ticks()
            if now - self.last_fire_time > FIRE_COOLDOWN:
                self.last_fire_time = now
                angle = atan2(player.pos.y - self.pos.y, player.pos.x - self.pos.x)
                if Fireball._fire_sound is None:
                    Fireball._fire_sound = pygame.mixer.Sound(resolve_asset(
                        theme.get("sounds.sfx.tank_enemy", "proj_fire.mp3")
                    ))
                Fireball._fire_sound.set_volume(game.sfx_volume)
                Fireball._fire_sound.play()
                return Fireball(self.pos.x, self.pos.y, angle)
            return result
        return super().find_path(player, game, deal_damage=deal_damage, do_movement=do_movement)

TANK_ENEMY_ATTACK_DIST = 500
FIRE_COOLDOWN = 1800


class Fireball(RenderObject):
    _fire_sound = None
    FIREBALL_SIZE = 40

    @classmethod
    def clear_sound_cache(cls):
        cls._fire_sound = None

    def __init__(self, x, y, angle, speed=8):
        super().__init__("enemies/projectile", x, y)
        self.size = self.FIREBALL_SIZE
        self.angle = angle
        self.speed = speed
        self.alive = True

    def update(self, player, game):
        self.pos.x += cos(self.angle) * self.speed
        self.pos.y += sin(self.angle) * self.speed
        px = int(self.pos.x)
        py = int(self.pos.y)
        if 0 <= py < len(game.map) and 0 <= px < len(game.map[0]):
            if game.map[py][px] == 1:
                self.alive = False
        if (self.pos - player.pos).norm() < self.size / 2 + SPRITE_SIZE / 2:
            player.take_damage(2, game)
            if Fireball._fire_sound is None:
                Fireball._fire_sound = pygame.mixer.Sound(resolve_asset(
                    theme.get("sounds.sfx.proj_hit", "proj_hit.mp3")
                ))
            Fireball._fire_sound.set_volume(game.sfx_volume)
            Fireball._fire_sound.play()
            self.alive = False

    def render_fast(self, dist, screen_x):
        sprite_h = self.FIREBALL_SIZE * PROJ_DIST / dist
        if int(dist) != self._cached_dist:
            self._cached_scale = pygame.transform.scale(
                self.sprite, (int(sprite_h), int(sprite_h))
            )
            self._cached_dist = int(dist)
        draw_x = screen_x - sprite_h / 2
        draw_y = HEIGHT / 2 - sprite_h / 2
        SCREEN.blit(self._cached_scale, (draw_x, draw_y))


class FinalBoss(Enemy):
    def __init__(self, x, y, health=200, damage=6, speed=3):
        super().__init__(health, damage, speed, "final_boss", x, y)
