"""
server_game.py - Headless server game logic
Runs enemy AI, maintains world state, processes client deltas.
"""

import random
from math import cos, sin, pi

from ..core.vector import Vector
from ..core.map_loader import M, will_collide as _will_collide
from ..core.config import (AGGRO_DIST, ATTACK_DIST, TILE_SIZE, PATHFIND_INTERVAL,
                    START_HEALTH,
                    START_AMMO, AMMO_CAP, HEALTH_CHANCE, MAP_PATH,
                    START_ANGLES, ELEVATOR_WAIT_DIST, MAX_LEVEL,
                    ELEVATOR_WAIT_FRAMES, ELEVATOR_STUCK_FRAMES,
                    gamemode as gm_cfg, DEFAULT_GAMEMODE, drop as drop_data)
from ..core.logger import log as _log
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
        # Gamemode, uit dezelfde tabel als de client zodat die twee niet
        # uit elkaar kunnen lopen op startwaarden en cap.
        self.gamemode = DEFAULT_GAMEMODE
        self.players = {}
        self.enemies = []
        self.objects = {"ammo": [], "keycard": [], "health": [], "exit": None}
        self.global_health = self.gm("start_health", START_HEALTH)
        self.global_ammo = self.gm("start_ammo", START_AMMO)
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
        self.elevator_missing = []
        self._ammo_dropped = set()
        self._stuck_timer = 0
        # Telter voor weggegooide posities van een client die nog op de
        # vorige level zit. Normaal is dit een handvol per overgang; een
        # groeiend getal betekent dat een client niet meer bijkomt.
        self._stale_pos_rejects = 0

        # Lobby options (shared vs per-player resources)
        self.shared_health = True
        self.shared_ammo = True

    # ── Gamemode-config (zelfde vorm als de client) ──────────────────
    def gm(self, key, default=None):
        """Eén configwaarde van de gamemode waarop de server draait."""
        return gm_cfg(self.gamemode).get(key, default)

    def max_health(self):
        """HP-bovengrens van de actieve gamemode."""
        return self.gm("health_cap", START_HEALTH)

    def max_ammo(self):
        """Ammo-bovengrens van de actieve gamemode."""
        return self.gm("ammo_cap", AMMO_CAP)

    @staticmethod
    def _drop_amount(kind):
        """Hoeveel een verse drop van dit type oplevert.

        Op één plek: de server bewaart per drop `amount` in de dict, maar
        de standaard komt uit dezelfde DROPS-tabel als de client leest.
        """
        return drop_data(f"objects/{kind}").get("amount", 0)

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
            self.objects["ammo"].append({"pos": (apos[0], apos[1]),
                                         "amount": self._drop_amount("ammo")})
        if M.SPAWNS["keycard"]:
            kpos = random.choice(M.SPAWNS["keycard"])
            self.objects["keycard"].append({"pos": (kpos[0], kpos[1])})
        self.objects["exit"] = {"pos": (M.SPAWNS["end_point"][0], M.SPAWNS["end_point"][1])}
        self.exit_pos = Vector(M.SPAWNS["end_point"][0], M.SPAWNS["end_point"][1])

        spawn = M.SPAWNS["player"]
        perp = M.start_angle - pi / 2
        player_count = len(self.players)
        # Hoe meer spelers, hoe ruimer de spreiding anders staan ze bovenop elkaar
        spacing = 15 if player_count <= 4 else 20
        for i, pdata in enumerate(self.players.values()):
            offset = spacing * (i - (player_count - 1) / 2)
            nx = spawn[0] + cos(perp) * offset
            ny = spawn[1] + sin(perp) * offset
            if _will_collide(nx, ny, 10):
                nx, ny = spawn
            pdata["pos"] = Vector(nx, ny)
            pdata["angle"] = M.start_angle

    def init_world(self):
        self.level = 0
        self._setup_level()
        self.global_health = self.gm("start_health", START_HEALTH)
        self.global_ammo = self.gm("start_ammo", START_AMMO)
        self.keycard_acquired = False
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.elevator_transition = False
        self.escaped = False
        self.jan_spotted = False
        for pid in self._last_player_seq:
            self._last_player_seq[pid] = 0
        self._ammo_dropped = set()
        self.initialized = True
        # Reset per-player resources to starting values
        start_hp = self.gm("start_health", START_HEALTH)
        start_ammo = self.gm("start_ammo", START_AMMO)
        for pdata in self.players.values():
            pdata["health"] = start_hp
            pdata["ammo"] = start_ammo
            pdata["at_exit"] = False
        self.elevator_missing = []
        self._stuck_timer = 0

    def set_shared_options(self, options):
        self.shared_health = options.get("shared_health", True)
        self.shared_ammo = options.get("shared_ammo", True)

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
            "ready": False,
            "health": self.gm("start_health", START_HEALTH),
            "ammo": self.gm("start_ammo", START_AMMO),
            "at_exit": False,
        }
        self._last_player_seq[pid] = 0
        self._ammo_dropped.discard(pid)

    def _drop_ammo_on_death(self, pid):
        """Leg de ammo van een dode speler neer, zodat de rest hem kan inpikken.

        Een dode komt niet meer terug, dus dit is het enige wat hij nog kan
        nalaten. Het hoeft geen nieuwe soort pickup te zijn: het is letterlijk
        hetzelfde voorwerp als de ammo die op het level staat, en die kost
        vast 50. Daarom is de regel simpelweg "hele oppakkingen per stuk",
        naar beneden afgerond. Wie minder dan 50 over heeft, laat niets
        achter - dat is de consequentie van die regel, geen ongeluk.

        Twee voorwaarden, en ze zijn allebei nodig:

          * Gedeeld leven: dan stopt de hele run bij de eerste dode en
            ligt er een hoopje ammo waar niemand meer bij kan.
          * Gedeelde ammo: dan is de voorraad van de groep, niet van één
            speler. Die heeft de dode niet verdiend weg te geven en de rest
            zou er alleen voor gestraft worden.
        """
        if self.shared_health or self.shared_ammo:
            return
        if pid in self._ammo_dropped or pid not in self.players:
            return
        self._ammo_dropped.add(pid)

        speler = self.players[pid]
        aantal = speler["ammo"] // self._drop_amount("ammo")
        speler["ammo"] = 0
        if aantal <= 0:
            return

        # Iets uit elkaar leggen, anders liggen ze exact op elkaar en zie je
        # er één. De HELDER ligt binnen de oppakafstand, zodat de groep ze
        # in een keer kan meenemen in plaats van voor elke los te lopen.
        for i in range(aantal):
            hoek = 2 * pi * i / aantal
            self.objects["ammo"].append({
                "pos": (speler["pos"].x + cos(hoek) * 12,
                        speler["pos"].y + sin(hoek) * 12),
                "amount": self._drop_amount("ammo"),
            })
        _log(f"[SERVER] speler {pid} liet {aantal} ammo liggen op "
             f"({speler['pos'].x:.0f}, {speler['pos'].y:.0f})")

    def toggle_ready(self, pid):
        if pid in self.players:
            self.players[pid]["ready"] = not self.players[pid]["ready"]

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
        self.global_health = self.gm("start_health", START_HEALTH)
        self.global_ammo = self.gm("start_ammo", START_AMMO)
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
        self._post_transition_grace = 0
        self.elevator_missing = []
        self._stuck_timer = 0

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
                self.objects["health"].append({"pos": (enemy.pos.x, enemy.pos.y),
                                               "amount": self._drop_amount("health")})
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
            # De speler is client-authoritative, dus de server neemt de
            # positie over. Maar tijdens een lift-overgang gaat er een pakket
            # onderweg dat nog de positie van de VORIGE level draagt. Die
            # kan op de nieuwe kaart midden in een muur staan, en de client
            # teleporteert dan naar dat punt zodra hij de nieuwe level ziet.
            #
            # Dus: vertrouw de positie alleen als de client op dezelfde level
            # zit als wij. Een pakket dat uit de oude level komt draagt
            # per definitie het oude levelnummer, dus dat is geen gok op
            # timing maar een check die altijd klopt. Oude clients die geen
            # level meesturen blijven gewoon werken.
            if "level" not in data or data["level"] == self.level:
                p["pos"] = Vector(data["pos"][0], data["pos"][1])
            else:
                self._stale_pos_rejects += 1
        if "health_delta" in data:
            delta = data["health_delta"]
            if self.shared_health:
                self.global_health += delta
                self.global_health = max(0, self.global_health)
            else:
                p["health"] += delta
                p["health"] = max(0, p["health"])
        if "ammo_delta" in data:
            delta = data["ammo_delta"]
            cap = self.max_ammo()
            if self.shared_ammo:
                self.global_ammo += delta
                self.global_ammo = max(0, min(cap, self.global_ammo))
            else:
                p["ammo"] += delta
                p["ammo"] = max(0, min(cap, p["ammo"]))
        if "got_keycard" in data:
            if data["got_keycard"] and self._post_transition_grace <= 0:
                self.keycard_acquired = True
                p["got_keycard"] = True
        if "door_closed" in data:
            p["door_closed"] = data["door_closed"]
        if "state" in data:
            was_dead = p["state"] == "dead"
            p["state"] = data["state"]
            if data["state"] == "dead" and not was_dead:
                self._drop_ammo_on_death(pid)
            # Eén dode = hele groep dode is alleen waar als het leven
            # gedeeld is. Zonder gedeeld leven leest elke client zijn
            # eigen health, en zou dit de hele pool op nul zetten omdat
            # één iemand weg is.
            if data["state"] == "dead" and self.shared_health:
                self.global_health = 0
        if "elevator_waiting" in data and self._post_transition_grace <= 0:
            # Per speler vastleggen, NIET meteen de globale vlag overschrijven:
            # de vlag is de OR van alle spelers en wordt in tick() berekend.
            # Anders overschreef de laatst verwerkte speler de rest, waardoor
            # alleen die ene speler de lift kon starten.
            p["at_exit"] = bool(data["elevator_waiting"])
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
                        # Het bedrag hoort bij de drop zelf; de fallback is er
                        # voor oudere dicts die nog geen amount meedroegen.
                        bedrag = obj.get("amount", self._drop_amount(ot))
                        self.objects[ot].pop(i)
                        if ot == "ammo":
                            cap = self.max_ammo()
                            if self.shared_ammo:
                                self.global_ammo = min(self.global_ammo + bedrag, cap)
                            else:
                                p["ammo"] = min(p["ammo"] + bedrag, cap)
                        elif ot == "health":
                            cap = self.max_health()
                            if self.shared_health:
                                self.global_health = min(self.global_health + bedrag, cap)
                            else:
                                p["health"] = min(p["health"] + bedrag, cap)
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
                if pdata["state"] not in ("dead", "paused")
            ) or self._transition_timeout > 180
            if all_done:
                self._level_up()
            return

        for enemy in self.enemies:
            target = self.get_nearest_player_pos(enemy)
            if target:
                enemy.update_ai(target)

        # De lift-vlag is de OR van alle levende spelers: zodra ÉÉN van hen op
        # de uitgangstegel staat, weet de hele groep dat het tijd is om te gaan.
        if self._post_transition_grace > 0:
            for pdata in self.players.values():
                pdata["at_exit"] = False
        else:
            self.elevator_waiting = any(
                pdata["at_exit"] for pdata in self.players.values()
                if pdata["state"] not in ("dead", "paused")
            )

        if self.elevator_waiting and not self.elevator_ready and self.exit_pos:
            self.elevator_missing = [
                pid for pid, pdata in self.players.items()
                if pdata["state"] not in ("dead", "paused")
                and (pdata["pos"] - self.exit_pos).norm() >= ELEVATOR_WAIT_DIST
            ]
            if not self.elevator_missing:
                self._stuck_timer = 0
                if self.elevator_wait_timer <= 0:
                    self.elevator_wait_timer = ELEVATOR_WAIT_FRAMES
                self.elevator_wait_timer -= 1
                if self.elevator_wait_timer <= 0:
                    self._depart_elevator()
            else:
                self.elevator_wait_timer = 0
                self._stuck_timer += 1
                if self._stuck_timer == ELEVATOR_STUCK_FRAMES:
                    _log(f"[SERVER] lift wacht op speler(s) {self.elevator_missing} "
                         f"en vertrekt na {ELEVATOR_STUCK_FRAMES} frames toch")
                if self._stuck_timer >= ELEVATOR_STUCK_FRAMES:
                    self._depart_elevator()

    def _depart_elevator(self):
        self.elevator_ready = True
        self.elevator_transition = True
        self._stuck_timer = 0
        for pdata in self.players.values():
            pdata["door_closed"] = False

    def _elevator_progress(self):
        """(spelers bij de lift, spelers die mee moeten) voor de HUD."""
        if not self.initialized or not self.exit_pos:
            return (0, 0)
        active = [p for p in self.players.values()
                  if p["state"] not in ("dead", "paused")]
        near = sum(1 for p in active
                   if (p["pos"] - self.exit_pos).norm() < ELEVATOR_WAIT_DIST)
        return (near, len(active))

    def _level_up(self):
        # Het levelnummer gaat NIET verder dan de laatste kaart. Vroeger stond
        # hier een hardcoded 5 en telde de server door tot 5, terwijl de
        # client dan MAP_PATH[5] probeerde te laden. MAP_PATH heeft vijf
        # kaarten, dus dat is een IndexError. De client zou dan ook blijven
        # hangen op level 4 terwijl de server op 5 staat, en de
        # level-controle in process_input zou zijn posities blijven weigeren.
        # Ontsnappen melden we apart via self.escaped.
        if self.level >= MAX_LEVEL:
            self.escaped = True
            # De vlaggen moeten ook hier weg, anders blijft tick() elke frame
            # _level_up aanroepen en blijft de lift bij de client dicht.
            self.elevator_ready = True
            self.elevator_transition = False
            self.elevator_waiting = False
            self.elevator_wait_timer = 0
            self._transition_timeout = 0
            return
        self.level += 1
        self._setup_level()
        for pdata in self.players.values():
            pdata["door_closed"] = False
            pdata["got_keycard"] = False
            pdata["at_exit"] = False
        self.keycard_acquired = False
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.elevator_transition = False
        self.elevator_missing = []
        self._stuck_timer = 0
        self._transition_timeout = 0
        self._post_transition_grace = 10

    def get_spawn_position(self):
        if not self.initialized:
            return None
        if M.SPAWNS and "player" in M.SPAWNS:
            spawn = M.SPAWNS["player"]
            return Vector(spawn[0], spawn[1])
        return None

    def get_state(self):
        if not self.initialized:
            return {"type": "state", "players": [], "enemies": [], "objects": self.objects,
                    "global_health": self.global_health, "global_ammo": self.global_ammo,
                    "keycard_acquired": False, "level": self.level, "escaped": self.escaped,
                    "elevator_waiting": self.elevator_waiting, "elevator_ready": self.elevator_ready,
                    "elevator_transition": self.elevator_transition,
                    "elevator_wait_timer": self.elevator_wait_timer,
                    "jan_spotted": self.jan_spotted, "exit_pos": None,
                    "elevator_pending": [0, 0]}
        return {
            "type": "state",
            "players": [{"id": pid, "pos": (p["pos"].x, p["pos"].y),
                         "angle": p["angle"], "name": p["name"],
                         "skin_id": p["skin_id"],
                         "got_keycard": p["got_keycard"],
                         "state": p["state"],
                         "score": p["score"],
                         "health": p.get("health", self.gm("start_health", START_HEALTH)),
                         "ammo": p.get("ammo", START_AMMO)}
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
            "elevator_pending": list(self._elevator_progress()),
        }
