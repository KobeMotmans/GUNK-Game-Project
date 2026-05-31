"""
enemies.py - Vijand klassen en rendering
"""

import pygame
from math import atan2, hypot, cos, sin
import heapq

from config import SCREEN, WIDTH, MAX_DEPTH, MIN_DIST, AGGRO_DIST, TILE_SIZE, PATHFIND_INTERVAL, FONT, SILLY_FONT, ATTACK_DIST, SFX_VOLUME
from vector import Vector
from map_loader import map_to_cord, cord_to_map, is_in_wall, M
from objects import RenderObject
from Menu import Menu_inst


# ── Projectile ────────────────────────────────────────────────────────────────

class Fireball(RenderObject):
    """
    Een recht-vooruit vliegend projectiel dat Ruben afvuurt.
    Sprite placeholder : assets/enemies/projectile.png
    Geluid bij vuren   : assets/proj_fire.mp3      (wordt afgespeeld door Ruben)
    Geluid bij inslag  : assets/proj_hit.mp3
    """

    SPEED       = 8          # pixels per frame
    DAMAGE      = 3
    _hit_sound  = None       # class-level cache zodat het geluid 1x geladen wordt

    @classmethod
    def _load_hit_sound(cls):
        if cls._hit_sound is None:
            try:
                cls._hit_sound = pygame.mixer.Sound("assets/proj_hit.mp3")
                cls._hit_sound.set_volume(SFX_VOLUME)
            except pygame.error:
                pass  # placeholder nog niet aanwezig

    def __init__(self, x, y, angle):
        super().__init__("enemies/projectile", x, y)
        self.angle   = angle          # richting in radialen, vast vanaf het moment van vuren
        self.alive   = True
        self._load_hit_sound()

    def update(self, player, game):
        """Beweeg het projectiel en controleer botsingen. Roep elke frame aan."""
        if not self.alive:
            return

        self.pos.x += self.SPEED * cos(self.angle)
        self.pos.y += self.SPEED * sin(self.angle)

        # Muur-check
        if is_in_wall(cord_to_map(self.pos)):
            self._on_hit()
            return

        # Speler-check
        if (self.pos - player.pos).norm() < MIN_DIST:
            player.take_damage(self.DAMAGE, game)
            self._on_hit()

    def _on_hit(self):
        self.alive = False
        if self._hit_sound:
            self._hit_sound.play()


# ── Basis vijand ──────────────────────────────────────────────────────────────

class Enemy(RenderObject):
    def __init__(self, health, damage, speed, enemy_type, x, y):
        self.path = f"enemies/{enemy_type}"
        super().__init__(self.path, x, y)
        self.max_health = health
        self.health = health
        self.speed = speed
        self.damage = damage
        self.spotted_player = False
        self.is_los = False
        self.last_player_tile = (1, 1)
        self.target = None
        self._full_path = []
        self._path_timer = 0

    def draw_health_bar(self, sprite_h, draw_x, draw_y):
        health_ratio = max(0, self.health / self.max_health)

        if self.type == "enemies/jan":
            bar_width = WIDTH // 2
            bar_height = 20
            bar_x = WIDTH // 4
            bar_y = 30

            font = pygame.font.Font(SILLY_FONT if Menu_inst.silly_mode else FONT, 28)
            font.set_bold(True)
            label = font.render("Jan Lemeire", True, (255, 220, 0))
            SCREEN.blit(label, (bar_x + bar_width // 2 - label.get_width() // 2, bar_y - 30))

            pygame.draw.rect(SCREEN, (80, 0, 0), (bar_x, bar_y, bar_width, bar_height))

            color = (200, 0, 0) if health_ratio <= 0.25 else (200, 200, 0) if health_ratio <= 0.5 else (0, 200, 0)
            pygame.draw.rect(SCREEN, color, (bar_x, bar_y, int(bar_width * health_ratio), bar_height))
            return

        bar_width = sprite_h
        bar_height = sprite_h * 0.1
        bar_x = draw_x
        bar_y = draw_y - bar_height - 4

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

    def is_in_los(self, pos):
        dx = pos.x - self.pos.x
        dy = pos.y - self.pos.y

        world_angle = atan2(dy, dx)
        dist = hypot(dx, dy)

        if dist > MAX_DEPTH:
            return False, dist

        step = max(4, TILE_SIZE // 4)
        i = step
        while i < dist:
            ray_pos = Vector(self.pos.x + i * cos(world_angle), self.pos.y + i * sin(world_angle))
            if is_in_wall(cord_to_map(ray_pos)):
                return False, dist
            i += step

        return True, dist

    def move_towards(self, pos):
        dx = pos.x - self.pos.x
        dy = pos.y - self.pos.y
        angle = atan2(dy, dx)
        self.pos += Vector(self.speed * cos(angle), self.speed * sin(angle))

    def has_target(self):
        if self.target is not None:
            if abs((self.target - self.pos).norm()) < 10:
                if self._full_path:
                    self.target = self._full_path.pop(0)
                else:
                    self.target = None
                    return False
            return True
        elif self._full_path:
            self.target = self._full_path.pop(0)
            return True
        return False

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
                    path = self.A_star(player)
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

        return None   # basisklasse vuurt nooit een projectiel af

    def is_hit(self, pos):
        return (self.pos - pos).norm() < self.size

    def take_dmg(self, dmg):
        self.health -= dmg

    # Code eerst geschreven door Ruben (zie zijn commit over A*), daarna herwerkt met AI (1 fps probleem)
    def A_star(self, player):
        """
        A* pathfinding. Nodes zijn (col, row) = (x, y) in maptiles.
        MAP[row][col] = MAP[y][x] — let op de volgorde bij maplookups!
        """
        col_start = int(cord_to_map(self.pos.x))
        row_start = int(cord_to_map(self.pos.y))
        col_end   = int(cord_to_map(player.pos.x))
        row_end   = int(cord_to_map(player.pos.y))

        start = (col_start, row_start)
        end   = (col_end,   row_end)

        if start == end:
            return None

        MAP_W = M.width
        MAP_H = M.height

        directions = [(0, 1), (1, 0), (0, -1), (-1, 0)]

        teller = 0
        heap = [(abs(col_start - col_end) + abs(row_start - row_end), teller, start)]

        came_from = {start: None}
        g_score   = {start: 0}

        while heap:
            _, _, node = heapq.heappop(heap)
            if node == end:
                return self._reconstruct_path(came_from, node, start)

            col, row = node
            for dc, dr in directions:
                nc, nr = col + dc, row + dr

                if not (0 <= nc < MAP_W and 0 <= nr < MAP_H):
                    continue
                if M.MAP[nr][nc] == 1:
                    continue

                new_g = g_score[node] + 1
                nb = (nc, nr)
                if nb in g_score and g_score[nb] <= new_g:
                    continue

                g_score[nb]   = new_g
                came_from[nb] = node
                priority = new_g + abs(nc - col_end) + abs(nr - row_end)
                teller += 1
                heapq.heappush(heap, (priority, teller, nb))

        return None

    @staticmethod
    def _reconstruct_path(came_from, end, start):
        path = []
        node = end
        while node != start:
            path.append(node)
            node = came_from[node]
        path.reverse()
        return [map_to_cord(Vector(col + 0.5, row + 0.5)) for col, row in path]


# ── Vijand subklassen ─────────────────────────────────────────────────────────

class Andrei(Enemy):
    def __init__(self, x, y, health=13, damage=3, speed=3):
        super().__init__(health, damage, speed, "andrei", x, y)

class Ahmed(Enemy):
    def __init__(self, x, y, health=6, damage=2, speed=5):
        super().__init__(health, damage, speed, "ahmed", x, y)

class Jan(Enemy):
    def __init__(self, x, y, health=200, damage=6, speed=3):
        super().__init__(health, damage, speed, "jan", x, y)


class Ruben(Enemy):
    """
    Ruben houdt afstand en vuurt projectielen af in plaats van melee aanvallen.

    Aanvalsgedrag:
      - Nadert tot RUBEN_ATTACK_DIST (verder dan de melee ATTACK_DIST).
      - Als de speler in LOS is én de cooldown voorbij is, wordt een
        Fireball aangemaakt en teruggegeven vanuit find_path().
      - Projectielen bewegen rechtdoor en kunnen hun pad niet aanpassen.
      - Inslag op muur of speler speelt proj_hit.mp3 af en verwijdert het projectiel.

    Placeholder bestanden (vervang door echte assets):
      - assets/enemies/projectile.png   ← sprite van het projectiel
      - assets/proj_fire.mp3                 ← geluid bij het afvuren
      - assets/proj_hit.mp3                  ← geluid bij inslag
    """

    RUBEN_ATTACK_DIST = 400   # pixels — Ruben stopt op grotere afstand dan melee vijanden
    FIRE_COOLDOWN     = 100    # frames tussen schoten (~1.5 s bij 60 fps)
    _fire_sound       = None  # class-level cache

    @classmethod
    def _load_fire_sound(cls):
        if cls._fire_sound is None:
            try:
                cls._fire_sound = pygame.mixer.Sound("assets/proj_fire.mp3")
                cls._fire_sound.set_volume(SFX_VOLUME)
            except pygame.error:
                pass  # placeholder nog niet aanwezig

    def __init__(self, x, y, health=19, damage=2, speed=2):
        super().__init__(health, damage, speed, "ruben", x, y)
        self._fire_timer = 0   # telt omlaag; vuren toegestaan als <= 0
        self._load_fire_sound()

    def find_path(self, player, game, deal_damage=True, do_movement=True):
        """
        Overschrijft Enemy.find_path.
        Geeft een Fireball terug als er dit frame gevuurd wordt,
        anders None. De game-loop moet dit opvangen en aan de projectiellijst
        toevoegen, zodat het projectiel elke frame geüpdated en gerenderd wordt.

        Voorbeeld in de game-loop:
            for enemy in enemies:
                result = enemy.find_path(player, game)
                if result is not None:          # Ruben vuurt
                    projectiles.append(result)
        """
        player_pos = player.pos

        self.is_los, dist = self.is_in_los(player_pos)

        if dist > AGGRO_DIST:
            self.spotted_player = False

        if self.is_los:
            self.spotted_player = True
            self._full_path = []
            self.target = None

        # Cooldown aftellen
        if self._fire_timer > 0:
            self._fire_timer -= 1

        if do_movement:
            # Beweeg naar de speler totdat Ruben op aanvalsafstand is
            if self.is_los and dist > self.RUBEN_ATTACK_DIST:
                self.move_towards(player_pos)

            # A* als speler buiten LOS maar eerder gespot
            if self.spotted_player and dist < AGGRO_DIST and not self.is_los:
                self._path_timer -= 1
                if not self.has_target() or self._path_timer <= 0:
                    path = self.A_star(player)
                    if path:
                        self._full_path = path[1:]
                        self.target = path[0]
                    else:
                        self._full_path = []
                        self.target = None
                    self._path_timer = PATHFIND_INTERVAL

            if self.has_target() and not self.is_los:
                self.move_towards(self.target)

        # Vuren: alleen als LOS, op aanvalsafstand, en cooldown voorbij
        if self.is_los and dist <= self.RUBEN_ATTACK_DIST and self._fire_timer <= 0:
            if deal_damage:
                angle = atan2(player_pos.y - self.pos.y, player_pos.x - self.pos.x)
                projectile = Fireball(self.pos.x, self.pos.y, angle)
                self._fire_timer = self.FIRE_COOLDOWN
                if self._fire_sound:
                    self._fire_sound.play()
                return projectile

        return None