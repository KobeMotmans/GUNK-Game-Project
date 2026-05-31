import heapq
from math import atan2, hypot, cos, sin

from ..core.vector import Vector
from ..core.map_loader import map_to_cord, cord_to_map, is_in_wall, will_collide, M
from ..core.config import MAX_DEPTH, TILE_SIZE, PATHFIND_INTERVAL, AGGRO_DIST, ATTACK_DIST


class EnemyAI:
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
        step = Vector(self.speed * cos(angle), self.speed * sin(angle))
        new_pos = self.pos + step
        if not will_collide(new_pos.x, new_pos.y, radius=5):
            self.pos = new_pos
        elif not will_collide(new_pos.x, self.pos.y, radius=5):
            self.pos.x = new_pos.x
        elif not will_collide(self.pos.x, new_pos.y, radius=5):
            self.pos.y = new_pos.y

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

    def A_star(self, target_pos):
        col_start = int(cord_to_map(self.pos.x))
        row_start = int(cord_to_map(self.pos.y))
        col_end = int(cord_to_map(target_pos.x))
        row_end = int(cord_to_map(target_pos.y))
        start = (col_start, row_start)
        end = (col_end, row_end)
        if start == end:
            return None
        MAP_W = M.width
        MAP_H = M.height
        directions = [(0, 1), (1, 0), (0, -1), (-1, 0)]
        teller = 0
        heap = [(abs(col_start - col_end) + abs(row_start - row_end), teller, start)]
        came_from = {start: None}
        g_score = {start: 0}
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
                g_score[nb] = new_g
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
