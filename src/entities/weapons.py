"""
weapons.py - Wapen klassen en rendering
"""

import pygame
from ..core.config import SCREEN, WIDTH, HEIGHT, WEAPON_OFFSET_X, MAX_DEPTH
from math import sin, cos
from ..core.vector import Vector
from ..core.paths import resolve_asset
from ..core.theme import theme
from ..assets.texture_cache import get as get_cached_texture

class Gun:
    def __init__(self, damage, recoil_speed, shoot_speed, ammo_weight, guntype, default_sound, auto=False):
        self.damage = damage
        self.recoil_speed = recoil_speed
        self.weapon_state = 0
        self.ammo_weight = ammo_weight
        self.flash_time = shoot_speed
        self.recoil_time = recoil_speed
        self.auto = auto
        self.guntype = guntype
        self.default_sound = default_sound

        self.played_sound = False

        self.gun_rest = self._load_texture(resolve_asset(theme.get(f"textures.weapons.{guntype}.rest", f"textures/weapons/{guntype}/GUN.png")))
        self.gun_recoil = self._load_texture(resolve_asset(theme.get(f"textures.weapons.{guntype}.recoil", f"textures/weapons/{guntype}/GUN_recoil.png")))
        self.gun_shoot = self._load_texture(resolve_asset(theme.get(f"textures.weapons.{guntype}.muzzle", f"textures/weapons/{guntype}/GUN_muzzle.png")))

        sound_path = resolve_asset(theme.get(f"sounds.sfx.{guntype}", f"sounds/sfx/{default_sound}"))
        self.shoot_sound = pygame.mixer.Sound(sound_path)

        self.weapon_rect = self.gun_rest.get_rect()

    def reload(self):
        self.gun_rest = self._load_texture(resolve_asset(theme.get(f"textures.weapons.{self.guntype}.rest", f"textures/weapons/{self.guntype}/GUN.png")))
        self.gun_recoil = self._load_texture(resolve_asset(theme.get(f"textures.weapons.{self.guntype}.recoil", f"textures/weapons/{self.guntype}/GUN_recoil.png")))
        self.gun_shoot = self._load_texture(resolve_asset(theme.get(f"textures.weapons.{self.guntype}.muzzle", f"textures/weapons/{self.guntype}/GUN_muzzle.png")))
        sound_path = resolve_asset(theme.get(f"sounds.sfx.{self.guntype}", f"sounds/sfx/{self.default_sound}"))
        self.shoot_sound = pygame.mixer.Sound(sound_path)
        self.weapon_rect = self.gun_rest.get_rect()

    def _load_texture(self, path):
        """Helper om texture te laden en te scalen (via texture cache)"""
        weapon_size = theme.get("sizes.weapon.texture", (300, 300))
        return get_cached_texture(path, weapon_size)

    def shoot(self, pos, angle, enemies, apply_damage=True):
        """Start schiet animatie als wapen in rust is. Returnt hit enemy pos of None."""
        if self.weapon_state == 0:
            self.weapon_state = 1
            self.temp_flash_time = self.flash_time
            self.temp_recoil_time = self.recoil_time
            ray_pos = pos
            dx = cos(angle)
            dy = sin(angle)
            while (ray_pos - pos).norm() < MAX_DEPTH:
                ray_pos = Vector(ray_pos.x + dx, ray_pos.y + dy)
                for i, enemy in enumerate(enemies):
                    if enemy.is_los:
                        if enemy.is_hit(ray_pos):
                            if apply_damage:
                                enemy.take_dmg(self.damage)
                            return i, (enemy.pos.x, enemy.pos.y)
                else:
                    continue
        return None

    def update(self):
        """Update wapen staat (animatie timing)"""
        if self.weapon_state != 0:
            if self.temp_flash_time > 0:
                self.temp_flash_time -= 1
            elif self.temp_recoil_time > 0:
                self.temp_recoil_time -= 1
                self.weapon_state = 2
            else:
                self.weapon_state = 0

    def draw(self):
        """Teken het wapen op scherm volgens huidige staat"""
        x_pos = (WIDTH - self.weapon_rect[2]) // 2 + WIDTH * WEAPON_OFFSET_X
        y_pos = HEIGHT - self.weapon_rect[3]
        if self.weapon_state == 0:
            SCREEN.blit(self.gun_rest, (x_pos, y_pos))
            self.played_sound = False
        elif self.weapon_state == 1:
            SCREEN.blit(self.gun_shoot, (x_pos, y_pos))
            if not self.played_sound:
                self.shoot_sound.play()
                self.played_sound = True
        elif self.weapon_state == 2:
            SCREEN.blit(self.gun_recoil, (x_pos, y_pos))
            


class Pistol(Gun):
    def __init__(self, damage=2, recoil_speed=10, shoot_speed=10, ammo_weight=2):
        super().__init__(damage, recoil_speed, shoot_speed, ammo_weight, "pistol", "pistol.ogg")

class Rifle(Gun):
    def __init__(self, damage=6, recoil_speed=60, shoot_speed=15, ammo_weight=5):
        super().__init__(damage, recoil_speed, shoot_speed, ammo_weight, "rifle", "musket.ogg")

class Minigun(Gun):
    def __init__(self, damage=0.75, recoil_speed=0, shoot_speed=5, ammo_weight=1, auto=True):
        super().__init__(damage, recoil_speed, shoot_speed, ammo_weight, "minigun", "minigun.ogg", auto)