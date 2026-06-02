"""
server_game.py - Headless server game logic
Runs enemy AI, maintains world state, processes client deltas.
"""

import random
from math import pi

from ..core.vector import Vector
from ..core.map_loader import M
from ..core.config import (AGGRO_DIST, ATTACK_DIST, TILE_SIZE, PATHFIND_INTERVAL,
                    START_HEALTH, HEALTH_REGEN,
                    START_AMMO, AMMO_CAP, HEALTH_CHANCE, MAP_PATH,
                    START_ANGLES, ELEVATOR_WAIT_DIST,
                    ELEVATOR_WAIT_FRAMES)
from ..entities.enemy_ai import EnemyAI


class ServerEnemy(EnemyAI):
    def __init__(self, type_str, x, y, health, damage, speed):
        self.type = f"enemies/{type_str}"
        self.pos = Vector(x, y)
        self.health = health
        self.max_health = health
        self.damage = damage
        self.speed = speed
        self.spotted_player = False
        self.is_los = False
        self.target = None
        self._full_path = []
        self._path_timer = 0

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
    "normal_enemy": {"health": 13, "damage": 3, "speed": 3},
    "fast_enemy": {"health": 6, "damage": 2, "speed": 5},
    "tank_enemy": {"health": 19, "damage": 2, "speed": 2},
    "final_boss": {"health": 200, "damage": 6, "speed": 3},
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
        self._transition_timeout = 0
        self._post_transition_grace = 0
        self.escaped = False
        self.jan_spotted = False
        self.exit_pos = None
        self.initialized = False
        self._last_player_seq = {}

    def _setup_level(self):
        from ..core.map_loader import png_to_list_fast
        M.map_level = self.level
        M.MAP, M.SPAWNS, M.width, M.height = png_to_list_fast(MAP_PATH[self.level])
        M.start_angle = START_ANGLES[self.level]

        self.enemies = []
        for epos in M.SPAWNS["enemies"]:
            tn = random.choice(["normal_enemy", "fast_enemy", "tank_enemy"])
            t = ENEMY_TYPES[tn]
            self.enemies.append(ServerEnemy(tn, epos[0], epos[1], t["health"], t["damage"], t["speed"]))
        if "final_boss" in M.SPAWNS:
            boss_pos = M.SPAWNS["final_boss"]
            t = ENEMY_TYPES["final_boss"]
            self.enemies.append(ServerEnemy("final_boss", boss_pos[0], boss_pos[1], t["health"], t["damage"], t["speed"]))

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

    def init_world(self):
        self.level = 0
        self._setup_level()
        self.global_health = START_HEALTH
        self.global_ammo = START_AMMO
        self.keycard_acquired = False
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.elevator_transition = False
        self.escaped = False
        self.jan_spotted = False
        for pid in self._last_player_seq:
            self._last_player_seq[pid] = 0
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
        self._transition_timeout = 0
        self.escaped = False
        self.jan_spotted = False
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
        if enemy.type == "enemies/final_boss":
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
            if data["got_keycard"] and self._post_transition_grace <= 0:
                self.keycard_acquired = True
                p["got_keycard"] = True
        if "door_closed" in data:
            p["door_closed"] = data["door_closed"]
        if "state" in data:
            p["state"] = data["state"]
            if data["state"] == "dead":
                self.global_health = 0
        if "elevator_waiting" in data and self._post_transition_grace <= 0:
            self.elevator_waiting = data["elevator_waiting"]
        if "escaped" in data:
            self.escaped = data["escaped"]

        if "enemy_damage" in data:
            for hit in data["enemy_damage"]:
                idx = hit.get("enemy_index", -1)
                if 0 <= idx < len(self.enemies):
                    e = self.enemies[idx]
                    hit_pos = Vector(hit["pos"][0], hit["pos"][1])
                    if (e.pos - hit_pos).norm() < TILE_SIZE:
                        e.health -= hit["damage"]
                        if e.health <= 0:
                            self._handle_enemy_death(idx, pid)
                    continue
                # Index shifted (enemy died) — drop silently

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
                        elif ot == "keycard":
                            if self._post_transition_grace <= 0:
                                self.keycard_acquired = True
                        break

    def process_inputs(self, inputs):
        for pid, data in inputs.items():
            self.process_input(pid, data)

    def tick(self):
        if not self.initialized:
            return

        if self._post_transition_grace > 0:
            self._post_transition_grace -= 1

        if self.elevator_transition:
            self._transition_timeout += 1
            all_done = all(
                pdata["door_closed"]
                for pdata in self.players.values()
                if pdata["state"] != "dead"
            ) or self._transition_timeout > 180
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
        self.level += 1
        if self.level >= 5:
            self.escaped = True
            return
        self._setup_level()
        for pdata in self.players.values():
            pdata["door_closed"] = False
            pdata["got_keycard"] = False
        self.keycard_acquired = False
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.elevator_transition = False
        self._transition_timeout = 0
        self._post_transition_grace = 10

    def get_state(self):
        if not self.initialized:
            return {"type": "state", "players": [], "enemies": [], "objects": self.objects,
                    "global_health": self.global_health, "global_ammo": self.global_ammo,
                    "keycard_acquired": False, "level": self.level, "escaped": self.escaped,
                    "elevator_waiting": self.elevator_waiting, "elevator_ready": self.elevator_ready,
                    "elevator_transition": self.elevator_transition,
                    "elevator_wait_timer": self.elevator_wait_timer,
                    "jan_spotted": self.jan_spotted, "exit_pos": None}
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
            "exit_pos": (self.exit_pos.x, self.exit_pos.y) if self.exit_pos else None,
        }
