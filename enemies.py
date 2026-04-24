"""
enemies.py - Vijand klassen en rendering
"""

import pygame
from math import atan2, hypot, cos, sin, tan, pi
import queue

from config import SCREEN, WIDTH, HEIGHT, FOV, MAX_DEPTH, PROJ_DIST, SPRITE_SIZE, NUM_RAYS, MIN_DIST, AGGRO_DIST, TILE_SIZE, ASTAR_INTERVAL
from config import SCREEN, WIDTH, HEIGHT, FOV, MAX_DEPTH, PROJ_DIST, SPRITE_SIZE, MIN_DIST, AGGRO_DIST
from vector import Vector
from map_loader import map_to_cord, cord_to_map, is_in_wall, M
from objects import RenderObject


class Enemy(RenderObject):
    def __init__(self, health, damage, speed, enemy_type, x, y):
        super().__init__(f"enemies/{enemy_type}", x, y)
        self.max_health = health
        self.health = health
        self.speed = speed
        self.damage = damage
        self.spotted_player = False
        self.is_los = False
        self.cached_path = []
        self.last_player_tile = None
        self.path_recalc_timer = 0

    def draw_health_bar(self, sprite_h, draw_x, draw_y):
        bar_width = sprite_h
        bar_height = sprite_h * 0.1

        health_ratio = max(0, self.health / self.max_health)

        # Plaats bar net boven de sprite
        bar_x = draw_x
        bar_y = draw_y - bar_height - 4

        # Achtergrond
        bg_rect = pygame.Rect(bar_x, bar_y, bar_width, bar_height)
        pygame.draw.rect(SCREEN, (120, 0, 0), bg_rect)

        # Dynamische kleur
        if health_ratio > 0.5:
            color = (0, 200, 0)
        elif health_ratio > 0.25:
            color = (200, 200, 0)
        else:
            color = (200, 0, 0)

        # Voorgrond
        fg_rect = pygame.Rect(
            bar_x,
            bar_y,
            bar_width * health_ratio,
            bar_height
        )
        pygame.draw.rect(SCREEN, color, fg_rect)

        # Rand
        pygame.draw.rect(SCREEN, (0, 0, 0), bg_rect, 1)

    def is_in_los(self, pos):
        # Vector van enemy naar speler
        dx = pos.x - self.pos.x
        dy = pos.y - self.pos.y

        # Bereken hoek naar player in wereldcoordinaten
        world_angle = atan2(dy, dx)
        # Echte afstand (hypot)
        dist = hypot(dx, dy)

        # Te ver weg
        if dist > MAX_DEPTH:
            return False, dist
        i = 0
        while i<dist:
            i += 2
            ray_pos = Vector(self.pos.x + i*cos(world_angle), self.pos.y + i*sin(world_angle))
            r_pos_m = cord_to_map(ray_pos)
            if is_in_wall(r_pos_m):
                return False, dist
        return True, dist

    def move_towards(self, pos):
        dx = pos.x - self.pos.x
        dy = pos.y - self.pos.y
        angle = atan2(dy, dx)
        self.pos += Vector(self.speed * cos(angle), self.speed * sin(angle))

    def find_path(self, player):
        player_pos = player.pos
        is_los, dist = self.is_in_los(player_pos)
        self.is_los = is_los
    
        # Forget player once too far
        if dist > AGGRO_DIST:
            self.spotted_player = False
    
        # Remember player once seen
        if is_los:
            self.spotted_player = True
    
        # Attack if close
        if dist < MIN_DIST:
            player.take_damage(self.damage)
            return
    
        # Direct movement if visible
        if is_los:
            self.move_towards(player_pos)
            self.cached_path = []  # clear stale path
            self.last_player_tile = None
            return
    
        # A* pathfinding when player is hidden but was spotted
        if self.spotted_player and dist < AGGRO_DIST:
            player_tile = (
                round(cord_to_map(player_pos.x)),
                round(cord_to_map(player_pos.y))
            )
    
            # Only re-run A* if player moved tile or timer expired
            self.path_recalc_timer += 1
            player_moved = player_tile != self.last_player_tile
            timer_expired = self.path_recalc_timer >= ASTAR_INTERVAL
    
            if not self.cached_path or player_moved or timer_expired:
                self.cached_path = self.A_star(player)
                self.last_player_tile = player_tile
                self.path_recalc_timer = 0
    
            # Walk the cached path
            next_tile = self.next_tile_in_path()
            if next_tile:
                self.move_towards(map_to_cord(Vector(next_tile[0], next_tile[1])))
                
    def is_hit(self, pos):
        dist = (self.pos - pos).norm()
        if dist < self.size:
            return True
        return False
    def take_dmg(self,dmg):
        self.health -= dmg
    
    def A_star(self, player):
        x_start = round(cord_to_map(self.pos.x))
        y_start = round(cord_to_map(self.pos.y))
        x_end = round(cord_to_map(player.pos.x))
        y_end = round(cord_to_map(player.pos.y))
    
        if (x_start, y_start) == (x_end, y_end):
            return []
    
        pq = queue.PriorityQueue()
        teller = 0
        directions = [(0, 1), (1, 0), (0, -1), (-1, 0)]
    
        start_state = {'pos': (x_start, y_start), 'parent': None, 'cost': 0}
        start_priority = abs(x_start - x_end) + abs(y_start - y_end)
        pq.put((start_priority, teller, start_state))
    
        visited = set()
        visited.add((x_start, y_start))
    
        while not pq.empty():
            _, _, state = pq.get()
            row, col = state['pos']
            cost = state['cost']
    
            if state['pos'] == (x_end, y_end):
                return self._reconstruct_path(state)
    
            for x_change, y_change in directions:
                new_row = row + x_change
                new_col = col + y_change
                if (0 <= new_row < M.w and 0 <= new_col < M.h
                        and M.MAP[new_row][new_col] != 1
                        and (new_row, new_col) not in visited):
                    new_state = {
                        'pos': (new_row, new_col),
                        'parent': state,
                        'cost': cost + 1
                    }
                    h = abs(new_row - x_end) + abs(new_col - y_end)
                    teller += 1
                    pq.put((cost + 1 + h, teller, new_state))
                    visited.add((new_row, new_col))
    
        return []  # No path found
    
    def _reconstruct_path(self, state):
        """Unpack the parent-chain into a plain list, start → goal."""
        path = []
        current = state
        while current is not None:
            path.append(current['pos'])
            current = current['parent']
        path.reverse()  # now start → goal
        return path

    def next_tile_in_path(self):
        """Return the furthest tile in the cached path that has LOS."""
        best = None
        for tile in self.cached_path:
            is_los, _ = self.is_in_los(map_to_cord(Vector(tile[0], tile[1])))
            if is_los:
                best = tile  # keep going — furthest visible tile is best
        if best:
            # Trim path up to that tile so we don't re-walk it
            idx = self.cached_path.index(best)
            self.cached_path = self.cached_path[idx:]
            return best
        # Fall back to next tile in path
        return self.cached_path[0] if self.cached_path else None

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