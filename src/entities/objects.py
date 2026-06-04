import pygame
from math import atan2, hypot, tan, pi

from ..core import config
from ..core.config import SCREEN, WIDTH, HEIGHT, FOV, MAX_DEPTH, PROJ_DIST, SPRITE_SIZE, MIN_DIST, START_HEALTH, HEALTH_REGEN
from ..core.vector import Vector
from ..assets.skin_manager import SkinManager
from ..core.paths import resolve_asset, load_font, load_numeric_font
from ..core.theme import theme
from ..assets.texture_cache import get as get_cached_texture

class RenderObject:
    def __init__(self, type, x, y):
        self.pos = Vector(x, y)
        self.type = type
        theme_key = f"textures.{type.replace('/', '.')}"
        sprite_path = resolve_asset(theme.get(theme_key, f"textures/{type}.png"))
        self.sprite = get_cached_texture(sprite_path)
        self._theme_key = theme_key
        # Cache voor sprite scaling
        self._cached_scale = None
        self._cached_dist = -1
        self.dist = 100000000

        self.size = SPRITE_SIZE

    def reload_texture(self):
        sprite_path = resolve_asset(theme.get(self._theme_key, f"textures/{self.type}.png"))
        self.sprite = get_cached_texture(sprite_path)
        self._cached_scale = None
        self._cached_dist = -1

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
        if hasattr(self, "draw_health_bar") and self.type != "enemies/final_boss":
            self.draw_health_bar(sprite_h, draw_x, draw_y)

        SCREEN.blit(self._cached_scale, (draw_x, draw_y))

    def interact(self, player):
        pass

class PickupObject(RenderObject):
    def __init__(self, type, x, y):
        super().__init__(type, x, y)
    def interact(self, player, game):
        if self.type == "objects/ammo":
            game.global_ammo = min(game.global_ammo + 50, 200)
            game.sounds["ammo"].set_volume(game.sfx_volume)
            game.sounds["ammo"].play()
        if self.type == "objects/keycard":
            player.got_keycard = True
            game.sounds["key"].set_volume(game.sfx_volume)
            game.sounds["key"].play()
        if self.type == "objects/exit":
            if player.got_keycard:
                player.door_pos = 1
                game.elevator_locked = True
            else:
                self.font = load_font(80, bold=True)
                no_kc = self.font.render(theme.string("hud.no_keycard", "NO KEYCARD"), True,'green')
                SCREEN.blit(no_kc, (WIDTH//2 - no_kc.get_width()//2, HEIGHT//2))
                return "fail"
        if self.type == "objects/health":
            game.global_health = min(game.global_health + HEALTH_REGEN, START_HEALTH)
            game.sounds["drink"].set_volume(game.sfx_volume)
            game.sounds["drink"].play()
        return "succes"


class PlayerSprite(RenderObject):
    """Sprite voor remote spelers in de 3D wereld"""
    def __init__(self, name, x=0, y=0, skin_id=0):
        self.pos = Vector(x, y)
        self.name = name
        self.type = "player"
        self._skin_id = skin_id
        self._load_skin()
        self._cached_scale = None
        self._cached_dist = -1
        self.size = SPRITE_SIZE
        self.dist = 100000000

    def _load_skin(self):
        try:
            self.sprite = SkinManager.load_skin_sprite(self._skin_id)
        except (FileNotFoundError, pygame.error):
            sprite = pygame.Surface((SPRITE_SIZE, SPRITE_SIZE * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(sprite, (0, 150, 255), (0, 0, SPRITE_SIZE, SPRITE_SIZE * 2))
            pygame.draw.rect(sprite, (0, 100, 200), (int(SPRITE_SIZE * 0.25), 0, int(SPRITE_SIZE * 0.5), int(SPRITE_SIZE * 0.75)))
            self.sprite = sprite
        self._cached_scale = None
        self._cached_dist = -1

    def set_skin(self, skin_id):
        if skin_id != self._skin_id:
            self._skin_id = skin_id
            self._load_skin()

    def render_fast(self, dist, screen_x):
        super().render_fast(dist, screen_x)
        if dist > 0:
            sprite_h = SPRITE_SIZE * PROJ_DIST / dist
            name_size = max(10, int(sprite_h / 4))
            try:
                font = load_numeric_font(name_size)
            except:
                font = pygame.font.Font(None, name_size)
            name_surf = font.render(self.name, True, (255, 255, 255))
            name_x = screen_x - name_surf.get_width() / 2
            name_y = HEIGHT / 2 - sprite_h / 2 - name_surf.get_height() - 4
            SCREEN.blit(name_surf, (name_x, name_y))





