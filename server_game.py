"""
server_game.py - Headless server game state manager
Per-player state + world state relay tussen clients.
"""

from config import START_HEALTH, START_AMMO


class ServerGame:
    def __init__(self):
        self.players = {}
        self.enemies = []
        self.objects = {"ammo": [], "keycard": [], "health": [], "exit": None}
        self.level = 0
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.escaped = False
        self.jan_spotted = False
        self.global_paused = False
        self.paused_by = ""
        self.exit_pos = None

    def register_player(self, pid, name):
        self.players[pid] = {
            "health": START_HEALTH,
            "ammo": START_AMMO,
            "pos": (0.0, 0.0),
            "angle": 0.0,
            "name": name,
            "got_keycard": False,
            "door_pos": 0,
            "state": "game",
        }

    def remove_player(self, pid):
        self.players.pop(pid, None)

    def apply_inputs(self, inputs):
        if not inputs:
            return
        primary_data = None
        for pid, data in inputs.items():
            if pid not in self.players:
                continue
            p = self.players[pid]
            if "pos" in data:
                p["pos"] = data["pos"]
            if "angle" in data:
                p["angle"] = data["angle"]
            if "health" in data:
                p["health"] = data["health"]
            if "ammo" in data:
                p["ammo"] = data["ammo"]
            if "got_keycard" in data:
                p["got_keycard"] = data["got_keycard"]
            if "door_pos" in data:
                p["door_pos"] = data["door_pos"]
            if "state" in data:
                p["state"] = data["state"]
            if pid == 0:
                primary_data = data

        if primary_data:
            if "enemies" in primary_data:
                self.enemies = [dict(e) for e in primary_data["enemies"]]
            if "objects" in primary_data:
                self.objects = primary_data["objects"]
            for key in ("level", "elevator_waiting", "elevator_ready",
                        "elevator_wait_timer", "escaped", "jan_spotted",
                        "global_paused", "paused_by", "exit_pos"):
                if key in primary_data:
                    setattr(self, key, primary_data[key])

        enemy_health_lists = []
        for pid, data in inputs.items():
            if "enemies" in data:
                enemy_health_lists.append([e.get("health", 10) for e in data["enemies"]])
        if enemy_health_lists:
            max_len = max(len(eh) for eh in enemy_health_lists)
            for i in range(max_len):
                vals = [eh[i] for eh in enemy_health_lists if i < len(eh)]
                merged_h = min(vals) if vals else 10
                if i < len(self.enemies):
                    self.enemies[i]["health"] = merged_h

    def get_state(self):
        return {
            "type": "state",
            "players": [{"id": pid, **pdata} for pid, pdata in self.players.items()],
            "enemies": self.enemies,
            "objects": self.objects,
            "level": self.level,
            "elevator_waiting": self.elevator_waiting,
            "elevator_ready": self.elevator_ready,
            "elevator_wait_timer": self.elevator_wait_timer,
            "escaped": self.escaped,
            "jan_spotted": self.jan_spotted,
            "global_paused": self.global_paused,
            "paused_by": self.paused_by,
            "exit_pos": self.exit_pos,
        }
