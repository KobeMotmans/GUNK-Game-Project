"""
enemies.py - Vijand klassen en rendering
"""

import pygame
from math import atan2, hypot, cos, sin, tan, pi
import queue

from config import SCREEN, WIDTH, HEIGHT, FOV, MAX_DEPTH, PROJ_DIST, SPRITE_SIZE, NUM_RAYS, MIN_DIST, AGGRO_DIST, TILE_SIZE
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
        self.last_player_tile = (1,1)
        self.target = None

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

    def has_target(self):
        if self.target is not None:
            if abs((self.target - self.pos).norm()) < 10:
                self.target = None
                return False
            else:
                return True
        else:
            return False

    def find_path(self, player):
        player_pos = player.pos
        is_los, dist = self.is_in_los(player_pos)

        # Forget player once too far
        if dist > AGGRO_DIST:
            self.spotted_player = False
        self.is_los, dist = self.is_in_los(player_pos)

        # Remember player once seen
        if self.is_los:
            self.spotted_player = True


        # Direct movement if visible
        if self.is_los and dist >= MIN_DIST:
            self.move_towards(player_pos)


        # Attack if close
        if dist < MIN_DIST:
            player.take_damage(self.damage)

        # Use A* if player was seen
        if self.spotted_player and dist < AGGRO_DIST and not is_los and not self.has_target():
            state = self.A_star(self.pos,player)
            self.target = self.get_next_tile(state)

        if self.has_target() and not is_los:
            self.move_towards(self.target)


    def is_hit(self, pos):
        dist = (self.pos - pos).norm()
        if dist < self.size:
            return True
        return False

    def take_dmg(self,dmg):
        self.health -= dmg

    @staticmethod
    def get_next_tile(state):
        curr_state = state
        last_pos = None
        while curr_state["parent"]["parent"] is not None:
            last_pos = curr_state["pos"]
            curr_state = curr_state["parent"]
        last_pos = map_to_cord(Vector(last_pos[0]+0.5, last_pos[1]+0.5))
        return last_pos


    def A_star(self, pos, player):
        pq = queue.PriorityQueue ()
        x_start = round(cord_to_map(self.pos.x))
        y_start = round(cord_to_map(self.pos.y))
        x_end = round(cord_to_map(player.pos.x))
        y_end = round(cord_to_map(player.pos.y))
        teller = 0
        directions = [(0 ,1) , (1 ,0) , (0 , -1) , ( -1 ,0) ]
        start_priority = abs (x_start - x_end) + abs (y_start - y_end)
        start_state = {'pos':(x_start, y_start),'parent':None,'cost': 0}
        pq.put((start_priority , teller , start_state))
        visited = []
        visited_positions = [(x_start,y_start)]
        while not pq.empty () :
            priority , _ , state = pq . get ()
            row , col = state ['pos']
            cost = state ['cost']
            visited . append ([row,col])
            if state ['pos'] == (x_end,y_end):
                return state

            for x_change , y_change in directions :
                new_row = row + x_change
                new_col = col + y_change

                if 0 <= new_row < M.w and 0 <= new_col < M.h:
                    if M.MAP[new_row][new_col] != 1 and (new_row ,new_col) not in visited_positions :
                        new_state = {'pos':(new_row ,new_col),'parent':state,'cost': cost + 1}
                        distance_to_goal = abs ( new_row - x_end) +abs ( new_col - y_end)
                        new_priority = new_state ['cost'] +distance_to_goal
                        teller += 1
                        pq . put (( new_priority , teller , new_state ))
                        visited_positions . append (( new_row , new_col ))
        return state


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
    def __init__(self, x, y, health=100, damage=6, speed=4):
        super().__init__(health, damage, speed, "jan", x, y)