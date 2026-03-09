from dda import *

class Gun:
    def __init__(self, damage, reload_speed, guntype):
        self.damage = damage
        self.reload_speed = reload_speed
        self.weapon_state = 0
        self.flash_time = 20
        self.recoil_time = self.flash_time * 1.5

        self.gun_rest = pygame.image.load("assets/weapons/" + guntype + "/GUN.png").convert_alpha()
        self.gun_rest = pygame.transform.scale(self.gun_rest, (300, 300))
        self.weapon_rect = self.gun_rest.get_rect()

        self.gun_recoil = pygame.image.load("assets/weapons/" + guntype + "/GUN_recoil.png").convert_alpha()
        self.gun_recoil = pygame.transform.scale(self.gun_recoil, (300, 300))

        self.gun_shoot = pygame.image.load("assets/weapons/" + guntype + "/GUN_muzzle.png").convert_alpha()
        self.gun_shoot = pygame.transform.scale(self.gun_shoot, (300, 300))
    def shoot(self):
        if self.weapon_state == 0:
            self.weapon_state = 1
            self.temp_flash_time = self.flash_time
            self.temp_recoil_time = self.recoil_time
    def shooting(self):
        if self.weapon_state != 0:
            if self.temp_flash_time > 0:
                self.temp_flash_time -= 1
            elif self.temp_recoil_time > 0:
                self.temp_recoil_time -= 1
                self.weapon_state = 2
            else:
                self.weapon_state = 0
        draw_weapon(None, self.weapon_state, self.gun_rest, self.gun_shoot, self.gun_recoil, self.weapon_rect)

class Pistol(Gun):
    def __init__(self, damage=1, reload_speed=1):
        super().__init__(damage, reload_speed, "pistol")


class Bazooka(Gun):
    def __init__(self, damage=5, reload_speed=5):
        super().__init__(damage, reload_speed, "bazooka")

class Minigun(Gun):
    def __init__(self, damage=0.2, reload_speed=0.1):
        super().__init__(damage, reload_speed, "minigun")
