"""
enemies.py - Vijand klassen en rendering
"""

import pygame
from math import atan2, hypot, cos, sin
import heapq

from config import SCREEN, WIDTH, HEIGHT, FOV, MAX_DEPTH, PROJ_DIST, SPRITE_SIZE, NUM_RAYS, MIN_DIST, AGGRO_DIST, TILE_SIZE
from vector import Vector
from map_loader import map_to_cord, cord_to_map, is_in_wall, M
from objects import RenderObject

# Hoe vaak A* opnieuw berekend wordt (in frames)
PATHFIND_INTERVAL = 20


class Enemy(RenderObject):
    def __init__(self, health, damage, speed, enemy_type, x, y):
        super().__init__(f"enemies/{enemy_type}", x, y)
        self.type = enemy_type
        self.max_health = health
        self.health = health
        self.speed = speed
        self.damage = damage
        self.spotted_player = False
        self.is_los = False
        self.last_player_tile = (1, 1)
        self.target = None
        self._full_path = []    # lijst van waypoint-vectoren
        self._path_timer = 0    # frame-teller voor pathfinding throttle

    def draw_health_bar(self, sprite_h, draw_x, draw_y):
        bar_width = sprite_h
        bar_height = sprite_h * 0.1

        health_ratio = max(0, self.health / self.max_health)

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
                # Huidig waypoint bereikt, pak volgende uit het pad
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

    def find_path(self, player):
        player_pos = player.pos

        # LOS slechts 1x berekenen per frame
        self.is_los, dist = self.is_in_los(player_pos)

        if dist > AGGRO_DIST:
            self.spotted_player = False

        if self.is_los:
            self.spotted_player = True
            # Wis oud pad zodra enemy weer LOS heeft
            self._full_path = []
            self.target = None

        if self.is_los and dist >= MIN_DIST:
            self.move_towards(player_pos)

        if dist < MIN_DIST:
            player.take_damage(self.damage)

        # A* throttlen: herbereken periodiek of als enemy geen target meer heeft
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

    def is_hit(self, pos):
        return (self.pos - pos).norm() < self.size

    def take_dmg(self, dmg):
        self.health -= dmg

    def A_star(self, player):
        """
        A* pathfinding. Nodes zijn (col, row) = (x, y) in maptiles.
        MAP[row][col] = MAP[y][x] — let op de volgorde bij maplookups!
        Gebruikt heapq + set voor O(1) visited checks.
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

                # bounds: MAP[row][col] → MAP[nr][nc]
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
        """
        Reconstrueer volledig pad als lijst van wereld-coördinaten.
        Node = (col, row) = (x, y) in tiles → center van tile in pixels.
        """
        path = []
        node = end
        while node != start:
            path.append(node)
            node = came_from[node]
        path.reverse()
        return [map_to_cord(Vector(col + 0.5, row + 0.5)) for col, row in path]


class Andrei(Enemy):
    def __init__(self, x, y, health=13, damage=3, speed=3):
        super().__init__(health, damage, speed, "andrei", x, y)

class Ahmed(Enemy):
    def __init__(self, x, y, health=6, damage=2, speed=5):
        super().__init__(health, damage, speed, "ahmed", x, y)

class Ruben(Enemy):
    def __init__(self, x, y, health=19, damage=2, speed=2):
        super().__init__(health, damage, speed, "ruben", x, y)

class Jan(Enemy):
    def __init__(self, x, y, health=200, damage=6, speed=3):
        super().__init__(health, damage, speed, "jan", x, y)