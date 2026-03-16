"""
weapons.py - Wapen klassen en rendering
"""

import pygame
from config import SCREEN, WIDTH, HEIGHT, WEAPON_SIZE, WEAPON_OFFSET_X

# Sound init
pygame.mixer.init()
shoot_sound = pygame.mixer.Sound("assets/pew.mp3")

class Gun:
    def __init__(self, damage, reload_speed, shoot_speed, guntype):
        self.damage = damage
        self.reload_speed = reload_speed
        self.weapon_state = 0  # 0=rust, 1=schieten, 2=recoil

        self.flash_time = shoot_speed
        self.recoil_time = self.flash_time * 1.5

        self.played_sound = False

        # Load textures
        base_path = f"assets/weapons/{guntype}/"
        self.gun_rest = self._load_texture(base_path + "GUN.png")
        self.gun_recoil = self._load_texture(base_path + "GUN_recoil.png")
        self.gun_shoot = self._load_texture(base_path + "GUN_muzzle.png")

        self.weapon_rect = self.gun_rest.get_rect()

    def _load_texture(self, path):
        """Helper om texture te laden en te scalen"""
        tex = pygame.image.load(path).convert_alpha()
        return pygame.transform.scale(tex, WEAPON_SIZE)

    def shoot(self):
        """Start schiet animatie als wapen in rust is"""
        if self.weapon_state == 0:
            self.weapon_state = 1
            self.temp_flash_time = self.flash_time
            self.temp_recoil_time = self.recoil_time

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
                shoot_sound.play()
                self.played_sound = True
        elif self.weapon_state == 2:
            SCREEN.blit(self.gun_recoil, (x_pos, y_pos))


class Pistol(Gun):
    def __init__(self, damage=1, reload_speed=1, shoot_speed=10):
        super().__init__(damage, reload_speed, shoot_speed, "pistol")


class Bazooka(Gun):
    def __init__(self, damage=5, reload_speed=5):
        super().__init__(damage, reload_speed, "bazooka")


class Minigun(Gun):
    def __init__(self, damage=0.2, reload_speed=0.1):
        super().__init__(damage, reload_speed, "minigun")