"""
weapons.py - Wapen klassen en rendering
"""

import pygame
from config import SCREEN, WIDTH, HEIGHT, WEAPON_SIZE, WEAPON_OFFSET_X, MAX_DEPTH
from math import hypot, sin, cos, atan2
from vector import Vector

# Sound init
pygame.mixer.init()

class Gun:
    def __init__(self, damage, recoil_speed, shoot_speed, ammo_weight, guntype, shoot_sound):
        self.damage = damage
        self.recoil_speed = recoil_speed
        self.weapon_state = 0  # 0=rust, 1=schieten, 2=recoil
        self.ammo_weight = ammo_weight
        self.flash_time = shoot_speed
        self.recoil_time = recoil_speed

        self.played_sound = False

        # Load textures
        base_path = f"assets/weapons/{guntype}/"
        self.gun_rest = self._load_texture(base_path + "GUN.png")
        self.gun_recoil = self._load_texture(base_path + "GUN_recoil.png")
        self.gun_shoot = self._load_texture(base_path + "GUN_muzzle.png")
        self.shoot_sound = pygame.mixer.Sound(shoot_sound)

        self.weapon_rect = self.gun_rest.get_rect()

    def _load_texture(self, path):
        """Helper om texture te laden en te scalen"""
        tex = pygame.image.load(path).convert_alpha()
        return pygame.transform.scale(tex, WEAPON_SIZE)

    def shoot(self, pos, angle, enemies):
        """Start schiet animatie als wapen in rust is"""
        if self.weapon_state == 0:
            self.weapon_state = 1
            self.temp_flash_time = self.flash_time
            self.temp_recoil_time = self.recoil_time
            ray_pos = pos
            dx = cos(angle)
            dy = sin(angle)
            enemy_hit = False
            while (ray_pos - pos).norm() < MAX_DEPTH:
                ray_pos = Vector(ray_pos.x + dx, ray_pos.y + dy)
                for enemy in enemies:
                    if enemy.is_hit(ray_pos):
                        enemy.take_dmg(self.damage)
                        enemy_hit = True
                        break
                if enemy_hit:
                    break

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
    def __init__(self, damage=1.5, recoil_speed=10, shoot_speed=10, ammo_weight=3, shoot_sound = "assets/pistol.mp3"):
        super().__init__(damage, recoil_speed, shoot_speed, ammo_weight, "pistol", shoot_sound)


class Rifle(Gun):
    def __init__(self, damage=3.5, recoil_speed=50, shoot_speed=15, ammo_weight=10, shoot_sound = "assets/musket.mp3"):
        super().__init__(damage, recoil_speed, shoot_speed, ammo_weight, "rifle", shoot_sound)


class Minigun(Gun):
    def __init__(self, damage=0.5, recoil_speed=0, shoot_speed=1, ammo_weight=1, shoot_sound = "assets/pew.mp3"):
        super().__init__(damage, recoil_speed, shoot_speed, ammo_weight, "minigun", shoot_sound)