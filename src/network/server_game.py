"""
server_game.py - Headless server game logic
Runs enemy AI, maintains world state, processes client deltas.
"""

import random
import heapq
from math import atan2, pi, sin, cos, hypot
from ..core.vector import Vector
from ..core.map_loader import cord_to_map, map_to_cord, is_in_wall, M
from ..core.config import (MAX_DEPTH, AGGRO_DIST, ATTACK_DIST, TILE_SIZE,
                    PATHFIND_INTERVAL, START_HEALTH, HEALTH_REGEN,
                    START_AMMO, AMMO_CAP, HEALTH_CHANCE, MAP_PATH,
                    START_ANGLES, ELEVATOR_WAIT_DIST,
                    ELEVATOR_WAIT_FRAMES, ELEV_TIME)


class ServerEnemy:
    def __init__(self, type_str, x, y, health, damage, speed):
        self.type = f"enemies/{type_str}"
        self.pos = Vector(x, y)
        self.health = health
        self.max_health = health
        self.damage = damage
        self.speed = speed
        self.spotted_player = False
        self.is_los = False
        self.last_player_tile = (1, 1)
        self.target = None
        self._full_path = []
        self._path_timer = 0

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

    def update_ai(self, target_pos):
        self.is_los, dist = self.is_in_los(target_pos)
        if dist > AGGRO_DIST:
            self.spotted_player = False
        if self.is_los:
            self.spotted_player = True
            self._full_path = []
            self.target = None
        if self.is_los and dist > ATTACK_DIST:
            self.move_towards(target_pos)
        if self.spotted_player and dist < AGGRO_DIST and not self.is_los:
            self._path_timer -= 1
            if not self.has_target() or self._path_timer <= 0:
                path = self.A_star(target_pos)
                if path:
                    self._full_path = path[1:]
                    self.target = path[0]
                else:
                    self._full_path = []
                    self.target = None
                self._path_timer = PATHFIND_INTERVAL
        if self.has_target() and not self.is_los:
            self.move_towards(self.target)


ENEMY_TYPES = {
    "andrei": {"health": 13, "damage": 3, "speed": 3},
    "ahmed": {"health": 6, "damage": 2, "speed": 5},
    "ruben": {"health": 19, "damage": 2, "speed": 2},
    "jan": {"health": 200, "damage": 6, "speed": 3},
}


class ServerGame:
    def __init__(self):
        self.players = {}
        self.enemies = []
        self.objects = {"ammo": [], "keycard": [], "health": [], "exit": None}
        self.global_health = START_HEALTH
        self.global_ammo = START_AMMO
        self.keycard_acquired = False
        self.level = 0
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.elevator_transition = False
        self.elevator_transition_timer = 0
        self.escaped = False
        self.jan_spotted = False
        self.global_paused = False
        self.paused_by = ""
        self._paused_player_id = None
        self.exit_pos = None
        self.initialized = False
        self._last_player_seq = {}

    def init_world(self):
        from ..core.map_loader import png_to_list_fast
        M.map_level = 0
        M.MAP, M.SPAWNS, M.width, M.height = png_to_list_fast(MAP_PATH[0])
        M.start_angle = START_ANGLES[0]

        self.enemies = []
        for epos in M.SPAWNS["enemies"]:
            tn = random.choice(["andrei", "ahmed", "ruben"])
            t = ENEMY_TYPES[tn]
            self.enemies.append(ServerEnemy(tn, epos[0], epos[1], t["health"], t["damage"], t["speed"]))
        if "jan" in M.SPAWNS:
            jpos = M.SPAWNS["jan"]
            t = ENEMY_TYPES["jan"]
            self.enemies.append(ServerEnemy("jan", jpos[0], jpos[1], t["health"], t["damage"], t["speed"]))

        self.objects = {"ammo": [], "keycard": [], "health": [], "exit": None}
        for apos in M.SPAWNS["ammo"]:
            self.objects["ammo"].append({"pos": (apos[0], apos[1])})
        if M.SPAWNS["keycard"]:
            kpos = random.choice(M.SPAWNS["keycard"])
            self.objects["keycard"].append({"pos": (kpos[0], kpos[1])})
        self.objects["exit"] = {"pos": (M.SPAWNS["end_point"][0], M.SPAWNS["end_point"][1])}
        self.exit_pos = Vector(M.SPAWNS["end_point"][0], M.SPAWNS["end_point"][1])

        spawn = M.SPAWNS["player"]
        for pdata in self.players.values():
            pdata["pos"] = Vector(spawn[0], spawn[1])
            pdata["angle"] = M.start_angle

        self.global_health = START_HEALTH
        self.global_ammo = START_AMMO
        self.keycard_acquired = False
        self.level = 0
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.elevator_transition = False
        self.elevator_transition_timer = 0
        self.escaped = False
        self.jan_spotted = False
        self.global_paused = False
        self.paused_by = ""
        self._paused_player_id = None
        self.initialized = True

    def register_player(self, pid, name, skin_id=0):
        self.players[pid] = {
            "pos": Vector(0, 0),
            "angle": 0.0,
            "name": name,
            "skin_id": skin_id,
            "got_keycard": False,
            "door_closed": False,
            "state": "game",
            "score": 0,
        }
        self._last_player_seq[pid] = 0

    def set_skin(self, pid, skin_id):
        if pid in self.players:
            self.players[pid]["skin_id"] = skin_id

    def remove_player(self, pid):
        self.players.pop(pid, None)
        self._last_player_seq.pop(pid, None)

    def reset_to_lobby(self):
        self.players = {}
        self._last_player_seq = {}
        self.enemies = []
        self.objects = {"ammo": [], "keycard": [], "health": [], "exit": None}
        self.global_health = START_HEALTH
        self.global_ammo = START_AMMO
        self.keycard_acquired = False
        self.level = 0
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.elevator_transition = False
        self.elevator_transition_timer = 0
        self.escaped = False
        self.jan_spotted = False
        self.global_paused = False
        self.paused_by = ""
        self._paused_player_id = None
        self.exit_pos = None
        self.initialized = False

    def get_nearest_player_pos(self, enemy):
        nearest = None
        min_dist = float('inf')
        for pdata in self.players.values():
            if pdata["state"] == "dead":
                continue
            dist = (enemy.pos - pdata["pos"]).norm()
            if dist < min_dist:
                min_dist = dist
                nearest = pdata["pos"]
        return nearest

    def _handle_enemy_death(self, idx, killer_pid=None):
        if killer_pid is not None and killer_pid in self.players:
            self.players[killer_pid]["score"] += 1
        enemy = self.enemies[idx]
        if enemy.type == "enemies/jan":
            self.objects["keycard"].append({"pos": (enemy.pos.x, enemy.pos.y)})
        else:
            if random.random() < HEALTH_CHANCE:
                self.objects["health"].append({"pos": (enemy.pos.x, enemy.pos.y)})
        self.enemies.pop(idx)

    def process_input(self, pid, data):
        if pid not in self.players:
            return

        # Out-of-order UDP protection
        if "seq" in data:
            last_seq = self._last_player_seq.get(pid, 0)
            if data["seq"] <= last_seq:
                return
            self._last_player_seq[pid] = data["seq"]

        p = self.players[pid]

        if "pos" in data:
            p["pos"] = Vector(data["pos"][0], data["pos"][1])
        if "health_delta" in data:
            self.global_health += data["health_delta"]
            self.global_health = max(0, self.global_health)
        if "ammo_delta" in data:
            self.global_ammo += data["ammo_delta"]
            self.global_ammo = max(0, min(AMMO_CAP, self.global_ammo))
        if "got_keycard" in data:
            if data["got_keycard"]:
                self.keycard_acquired = True
                p["got_keycard"] = True
        if "door_closed" in data:
            p["door_closed"] = data["door_closed"]
        if "state" in data:
            p["state"] = data["state"]
            if data["state"] == "dead":
                self.global_health = 0
        if "elevator_waiting" in data:
            self.elevator_waiting = data["elevator_waiting"]
        if "paused" in data:
            if data["paused"] and not self.global_paused:
                self.global_paused = True
                self.paused_by = data.get("paused_by", "")
                self._paused_player_id = pid
            elif not data["paused"] and self.global_paused and pid == self._paused_player_id:
                self.global_paused = False
                self.paused_by = ""
                self._paused_player_id = None
        if "escaped" in data:
            self.escaped = data["escaped"]

        if "enemy_damage" in data:
            for hit in data["enemy_damage"]:
                hit_pos = Vector(hit["pos"][0], hit["pos"][1])
                for i, e in enumerate(self.enemies):
                    if (e.pos - hit_pos).norm() < TILE_SIZE:
                        e.health -= hit["damage"]
                        if e.health <= 0:
                            self._handle_enemy_death(i, pid)
                        break

        if "remove_pickup" in data:
            for pickup in data["remove_pickup"]:
                ot = pickup["type"]
                pos = pickup["pos"]
                for i, obj in enumerate(self.objects.get(ot, [])):
                    if abs(obj["pos"][0] - pos[0]) < 2 and abs(obj["pos"][1] - pos[1]) < 2:
                        self.objects[ot].pop(i)
                        if ot == "ammo":
                            self.global_ammo = min(self.global_ammo + 50, AMMO_CAP)
                        elif ot == "health":
                            self.global_health = min(self.global_health + HEALTH_REGEN, START_HEALTH)
                        break

    def process_inputs(self, inputs):
        for pid, data in inputs.items():
            self.process_input(pid, data)

    def tick(self):
        if not self.initialized:
            return

        if self.elevator_transition:
            all_done = all(
                pdata["door_closed"]
                for pdata in self.players.values()
                if pdata["state"] != "dead"
            )
            if all_done:
                self._level_up()
            return

        for enemy in self.enemies:
            target = self.get_nearest_player_pos(enemy)
            if target:
                enemy.update_ai(target)

        if self.elevator_waiting and not self.elevator_ready and self.exit_pos:
            all_near = True
            for pdata in self.players.values():
                if pdata["state"] == "dead":
                    continue
                dist = (pdata["pos"] - self.exit_pos).norm()
                if dist >= ELEVATOR_WAIT_DIST:
                    all_near = False
                    break
            if all_near:
                if self.elevator_wait_timer <= 0:
                    self.elevator_wait_timer = ELEVATOR_WAIT_FRAMES
                self.elevator_wait_timer -= 1
                if self.elevator_wait_timer <= 0:
                    self.elevator_ready = True
                    self.elevator_transition = True
                    for pdata in self.players.values():
                        pdata["door_closed"] = False
            else:
                self.elevator_wait_timer = 0

    def _level_up(self):
        from ..core.map_loader import png_to_list_fast
        self.level += 1
        if self.level >= 5:
            self.escaped = True
            return
        M.MAP, M.SPAWNS, M.width, M.height = png_to_list_fast(MAP_PATH[self.level])
        M.start_angle = START_ANGLES[self.level]
        self.enemies = []
        for epos in M.SPAWNS["enemies"]:
            tn = random.choice(["andrei", "ahmed", "ruben"])
            t = ENEMY_TYPES[tn]
            self.enemies.append(ServerEnemy(tn, epos[0], epos[1], t["health"], t["damage"], t["speed"]))
        if "jan" in M.SPAWNS:
            jpos = M.SPAWNS["jan"]
            t = ENEMY_TYPES["jan"]
            self.enemies.append(ServerEnemy("jan", jpos[0], jpos[1], t["health"], t["damage"], t["speed"]))
        self.objects = {"ammo": [], "keycard": [], "health": [], "exit": None}
        for apos in M.SPAWNS["ammo"]:
            self.objects["ammo"].append({"pos": (apos[0], apos[1])})
        if M.SPAWNS["keycard"]:
            kpos = random.choice(M.SPAWNS["keycard"])
            self.objects["keycard"].append({"pos": (kpos[0], kpos[1])})
        self.objects["exit"] = {"pos": (M.SPAWNS["end_point"][0], M.SPAWNS["end_point"][1])}
        self.exit_pos = Vector(M.SPAWNS["end_point"][0], M.SPAWNS["end_point"][1])
        spawn = M.SPAWNS["player"]
        for pdata in self.players.values():
            pdata["pos"] = Vector(spawn[0], spawn[1])
            pdata["angle"] = M.start_angle
            pdata["door_closed"] = False
            pdata["got_keycard"] = False
        self.keycard_acquired = False
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.elevator_transition = False
        self.elevator_transition_timer = 0

    def get_state(self):
        if not self.initialized:
            return {"type": "state", "players": [], "enemies": [], "objects": self.objects,
                    "global_health": self.global_health, "global_ammo": self.global_ammo,
                    "keycard_acquired": False, "level": self.level, "escaped": self.escaped,
                    "elevator_waiting": self.elevator_waiting, "elevator_ready": self.elevator_ready,
                    "elevator_transition": self.elevator_transition,
                    "elevator_wait_timer": self.elevator_wait_timer,
                    "jan_spotted": self.jan_spotted, "global_paused": self.global_paused,
                    "paused_by": self.paused_by, "exit_pos": None}
        return {
            "type": "state",
            "players": [{"id": pid, "pos": (p["pos"].x, p["pos"].y),
                         "angle": p["angle"], "name": p["name"],
                         "skin_id": p["skin_id"],
                         "got_keycard": p["got_keycard"],
                         "state": p["state"],
                         "score": p["score"]}
                        for pid, p in self.players.items()],
            "enemies": [{"pos": (e.pos.x, e.pos.y), "health": e.health, "type": e.type}
                        for e in self.enemies],
            "objects": self.objects,
            "global_health": self.global_health,
            "global_ammo": self.global_ammo,
            "keycard_acquired": self.keycard_acquired,
            "level": self.level,
            "escaped": self.escaped,
            "elevator_waiting": self.elevator_waiting,
            "elevator_ready": self.elevator_ready,
            "elevator_transition": self.elevator_transition,
            "elevator_wait_timer": self.elevator_wait_timer,
            "jan_spotted": self.jan_spotted,
            "global_paused": self.global_paused,
            "paused_by": self.paused_by,
            "exit_pos": (self.exit_pos.x, self.exit_pos.y) if self.exit_pos else None,
        }
