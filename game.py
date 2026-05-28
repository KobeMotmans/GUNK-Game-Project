"""
game.py - Hoofd game loop en initialisatie
"""

import pygame
import random

from config import (SCREEN, WIDTH, HEIGHT, START_AMMO, AMMO_CAP, DAMAGE_FLASH, AMMO_FLASH, KEYCARD_FLASH,
                    SCREEN_DEAD, START_HEALTH, ELEV_SPEED, MAX_LEVEL, MAP_PATH, START_ANGLES, HEALTH_FLASH, HEALTH_CHANCE, 
                    set_resolution, FONT, VICTORY_SCREEN, MENU_BG, ELEV_TIME, SILLY_FONT, MAX_DEPTH,
                    ELEVATOR_WAIT_DIST, ELEVATOR_WAIT_FRAMES)
from raycaster import dda
from weapons import Pistol, Minigun, Rifle
from enemies import Andrei, Ahmed, Ruben, Jan
from player import Player
from Menu import Menu_inst, Bilal
from map_loader import M, png_to_list_fast
from objects import PickupObject, PlayerSprite
from vector import Vector
from network import ServerIO, NetworkClient
from config import DEFAULT_PORT, MAX_PLAYERS


class Game:
    def __init__(self):
        pygame.init()
        self.clock = pygame.time.Clock()
        self.running = False
        self.state = None
        self.escaped = False

        #Init Bilal/Tutorial
        self.Menu = Menu_inst
        self.Menu.draw_loading_screen()
        self.bilal = Bilal(self)
        self.bilal.say("Welkom bij GUNK!", 100)
        self.bilal.say("Gebruik je muis om rond te kijken en ZQSD om te bewegen", 200)
        self.bilal.say("Je zit vast op verdieping 5 van het K gebouw. Probeer via de lift te ontsnappen.", 250)
        self.bilal.say("Er moet in n van deze kamers een keycard liggen. Zoek hem!", 200)
        self.bilal.say("Maar pas op, want de andere assistenten zijn gek geworden van het K gebouw!", 200)

        self.Menu.draw_loading_screen()

        # Init speler
        self.player = Player(M.SPAWNS["player"][0], M.SPAWNS["player"][1])
        self.global_health = START_HEALTH
        self.global_ammo = START_AMMO
        self._prev_global_health = START_HEALTH

        self.Menu.draw_loading_screen()

        # Init wapens
        self.pistol = Pistol()
        self.minigun = Minigun()
        self.rifle = Rifle()
        self.current_gun = self.pistol
        self.unlocked_guns = [self.pistol]

        self.sfx_volume = 0.3
        self.curr_flash = ""
        self.flash_time = 0
        self.possible_enemies = [Andrei, Ahmed, Ruben]
        self.jan = None
        self.jan_spotted = False

        self.update_sfx_volume()

        self.Menu.draw_loading_screen()

        # Init objects
        self.resolution = "high"

        pygame.mixer.init()

        self.normal_music = pygame.mixer.Sound("assets/esKape Final.ogg")

        self.Menu.draw_loading_screen()

        self.funny_music = pygame.mixer.Sound("assets/Funny Music.ogg")

        self.Menu.draw_loading_screen()

        if self.Menu.silly_mode:
            self.main_music = self.funny_music
        else:
            self.main_music = self.normal_music
        self.main_music.set_volume(0.5)  # match initial slider value

        self.Menu.draw_loading_screen()

        # Multiplayer
        self.multiplayer = False
        self.player_id = 0
        self.player_name = "Player"
        self.network_server = None
        self.network_client = None
        self.remote_players = []
        self.host_port = DEFAULT_PORT

        # Elevator wait (multiplayer)
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.player_near_exit = False
        self.exit_pos = None

        # Global pause (multiplayer)
        self.global_paused = False
        self.paused_by = ""
        self._settings_return = "menu"

        # Pos update rate limiting
        self._pos_seq = 0

        self.state = "menu"

    def update_sfx_volume(self):
        import config as cfg
        cfg.SFX_VOLUME = self.sfx_volume
        for gun in [self.pistol, self.minigun, self.rifle]:
            gun.shoot_sound.set_volume(self.sfx_volume)
            gun.silly_sound.set_volume(self.sfx_volume)

    def create_enemies(self):
        """Maak een lijst van test vijanden"""
        enemies = []
        for enemy_pos in M.SPAWNS["enemies"]:
            randomnumber = random.randint(0,2)
            random_enemy =  self.possible_enemies[randomnumber]
            enemies.append(random_enemy(enemy_pos[0], enemy_pos[1]))
        if "jan" in M.SPAWNS:
            jan_pos = M.SPAWNS["jan"]
            jan = Jan(jan_pos[0], jan_pos[1])
            self.jan = jan
            enemies.append(jan)
        return enemies

    def create_objects(self):
        objects = {
            "enemies": self.create_enemies(),
            "ammo": [],
            "keycard": [],
            "exit": PickupObject("objects/exit", M.SPAWNS["end_point"][0], M.SPAWNS["end_point"][1]),
            "health": []
        }
        for ammo_pos in M.SPAWNS["ammo"]:
            objects["ammo"].append(PickupObject("objects/ammo", ammo_pos[0], ammo_pos[1]))
        if M.SPAWNS["keycard"]:
            keycard_pos = M.SPAWNS["keycard"][random.randint(0, len( M.SPAWNS["keycard"])-1)]
            objects["keycard"].append(PickupObject("objects/keycard", keycard_pos[0], keycard_pos[1]))
            print("Chosen keycard pos:", keycard_pos)
        
        return objects

    def handle_events(self):
        """Verwerk pygame events"""
        events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                self.running = False
    
            if self.state == "game":
                if event.type == pygame.KEYDOWN: #Switch guns
                    if event.key == pygame.K_a:
                        if self.current_gun == self.unlocked_guns[-1]:
                            self.current_gun = self.unlocked_guns[0]
                        else:
                            self.current_gun = self.unlocked_guns[self.unlocked_guns.index(self.current_gun) + 1]
                    if event.key == pygame.K_ESCAPE:
                        if self.multiplayer:
                            if self.player_id == 0:
                                self.global_paused = not self.global_paused
                                self.paused_by = self.player_name if self.global_paused else ""
                                if self.global_paused:
                                    pygame.mouse.set_visible(True)
                                    pygame.event.set_grab(False)
                                    pygame.mixer.pause()
                                    self.state = "paused"
                                else:
                                    pygame.mouse.set_visible(False)
                                    pygame.event.set_grab(True)
                                    pygame.mixer.unpause()
                                    self.state = "game"
                        else:
                            pygame.mouse.set_visible(True)
                            pygame.event.set_grab(False)
                            self.state = "paused"
                            pygame.mixer.pause()

                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        if not self.current_gun.auto:
                            if self.global_ammo >= self.current_gun.ammo_weight:
                                self.global_ammo -= self.current_gun.ammo_weight
                                self.current_gun.shoot(self.player.pos,self.player.angle,self.objects.get("enemies",[]),self.player,self.current_gun)

            elif self.state == "paused":
                 if event.type == pygame.KEYDOWN: #unpause
                     if event.key == pygame.K_ESCAPE:
                         if self.multiplayer:
                             if self.player_id == 0:
                                 self.global_paused = False
                                 self.paused_by = ""
                                 pygame.mouse.set_visible(False)
                                 pygame.event.set_grab(True)
                                 self.state = "game"
                                 pygame.mixer.unpause()
                         else:
                             pygame.mouse.set_visible(False)
                             pygame.event.set_grab(True)
                             self.state = "game"
                             pygame.mixer.unpause()

        if self.state == "game":
            mouse_buttons = pygame.mouse.get_pressed()
            if self.current_gun.auto: #Pressed to shoot
                if mouse_buttons[0] and self.current_gun.weapon_state == 0:
                    if self.global_ammo >= self.current_gun.ammo_weight:
                        self.global_ammo -= self.current_gun.ammo_weight
                        self.current_gun.shoot(self.player.pos,self.player.angle,self.objects["enemies"],self.player,self.current_gun)
        return events
    
    def handle_input(self):
        """Verwerk toetsenbord input (continuous events)"""
        keys = pygame.key.get_pressed()

        if keys[pygame.K_DELETE]:
            self.running = False
            self.state = None
            pygame.quit()

        if self.state == "game" and not self.escaped:
            # === UNIFIED: all players move and auto-fire locally ===
            if not self.global_paused:
                self.player.rotate(pygame.mouse.get_rel()[0])
                pygame.mouse.set_pos(WIDTH // 2, HEIGHT // 2)
                pygame.mouse.get_rel()
                if keys[pygame.K_UP] or keys[pygame.K_z]:
                    self.player.move("up")
                if keys[pygame.K_DOWN] or keys[pygame.K_s]:
                    self.player.move("down")
                if keys[pygame.K_LEFT] or keys[pygame.K_q]:
                    self.player.move("left")
                if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                    self.player.move("right")

                mouse_buttons = pygame.mouse.get_pressed()
                if self.current_gun.auto and mouse_buttons[0] and self.current_gun.weapon_state == 0:
                    if self.global_ammo >= self.current_gun.ammo_weight:
                        self.global_ammo -= self.current_gun.ammo_weight
                        self.current_gun.shoot(self.player.pos, self.player.angle, self.objects.get("enemies", []), self.player, self.current_gun)

            # === Client: send position + state to server (rate-limited) ===
            if self.network_client:
                self._send_client_state()

    def update(self):   #Update game state
        self.current_gun.update()
        self.player.tick()
        # Elevator wait logic (primary client only)
        if self.multiplayer and self.player_id == 0 and self.elevator_waiting and not self.elevator_ready:
            self.player_near_exit = False
            all_near = True
            if self.exit_pos:
                host_dist = (self.player.pos - self.exit_pos).norm()
                self.player_near_exit = host_dist < ELEVATOR_WAIT_DIST
                all_near = all_near and self.player_near_exit
                for rp in self.remote_players:
                    if rp is None:
                        continue
                    dist = (rp.pos - self.exit_pos).norm()
                    if dist >= ELEVATOR_WAIT_DIST:
                        all_near = False
            if all_near:
                if self.elevator_wait_timer <= 0:
                    self.elevator_wait_timer = ELEVATOR_WAIT_FRAMES
                self.elevator_wait_timer -= 1
                if self.elevator_wait_timer <= 0:
                    self.elevator_ready = True
                    self.player.door_pos = 1
                    self.objects["exit"] = None
            else:
                self.elevator_wait_timer = 0

    def render(self):   #Render alle game elementen
        SCREEN.fill((0, 255, 255) if self.Menu.silly_mode else 'black')


        player_pos = self.player.get_pos()
        player_angle = self.player.get_angle()

        # 1. Raycasting - muren direct tekenen, afstanden opslaan
        wall_distances = dda(player_pos, player_angle)

        # 2. Verzamel zichtbare sprites
        sprites = []  # (dist, SCREEN_x, enemy)
        for obj in self.objects.keys():
            if obj == "enemies":
                for enemy in list(self.objects[obj]):
                    if enemy.health <= 0:
                        if not self.multiplayer or self.player_id == 0:
                            self.player.score += 1
                            self.objects["enemies"].remove(enemy)
                            if enemy.type == "enemies/jan":
                                self.objects["keycard"].append(PickupObject("objects/keycard", enemy.pos.x, enemy.pos.y))
                                self.jan = None
                                self.bilal.say("Je hebt het gedaan! Zorg dat je nu zo snel mogelijk buiten staat!")
                            else:
                                if random.random() < HEALTH_CHANCE:
                                    self.objects["health"].append(PickupObject("objects/health", enemy.pos.x, enemy.pos.y))
                                    self.bilal.trigger("monster")
                        continue
                    if self.state == "game" and not self.global_paused:
                        if self.multiplayer:
                            if self.player_id == 0:
                                nearest = self._get_closest_player(enemy)
                                enemy.find_path(nearest, self, True, True)
                                enemy.is_los, _ = enemy.is_in_los(self.player.pos)
                            else:
                                enemy.find_path(self.player, self, True, False)
                        else:
                            enemy.find_path(self.player, self, True, True)
                    dist, SCREEN_x, angle, _ = enemy.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, enemy))
                        self.bilal.trigger("seen_enemy")
                        if enemy.type == "enemies/jan":
                            self.jan_spotted = True
                            self.bilal.trigger("boss_warning")
            elif obj == "ammo":
                for item in self.objects["ammo"]:
                    dist, SCREEN_x, angle, is_hit = item.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, item))
                    if is_hit:
                        self.curr_flash = "ammo"
                        self.flash_time = 60
                        item.interact(self.player, self)
                        self.objects["ammo"].remove(item)
            elif obj == "health":
                for item in self.objects["health"]:
                    dist, SCREEN_x, angle, is_hit = item.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, item))
                    if is_hit:
                        self.curr_flash = "health"
                        self.flash_time = 60
                        item.interact(self.player, self)
                        self.objects["health"].remove(item)
            elif obj == "keycard":
                for item in self.objects["keycard"]:
                    dist, SCREEN_x, angle, is_hit = item.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, item))
                    if is_hit:
                        self.curr_flash = "keycard"
                        self.flash_time = 60
                        item.interact(self.player, self)
                        self.objects["keycard"].remove(item)
            else:
                item = self.objects[obj]
                if item is not None:
                    dist, SCREEN_x, angle, is_hit = item.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, item))
                        if obj == "keycard":
                            self.bilal.trigger("keycard")
                    if is_hit:
                        if self.multiplayer:
                            if obj == "exit":
                                if self.player.got_keycard and not self.elevator_waiting and not self.elevator_ready:
                                    self.elevator_waiting = True
                                    self.exit_pos = Vector(item.pos.x, item.pos.y)
                                    self.objects[obj] = None
                                else:
                                    pass  # NO KEYCARD handled by server
                            else:
                                interaction = item.interact(self.player, self)
                                if interaction == "succes":
                                    self.objects[obj] = None
                                    if obj != 'exit':
                                        self.curr_flash = "keycard"
                                        self.flash_time = 60
                        else:
                            interaction = item.interact(self.player, self)
                            if interaction == "succes":
                                self.objects[obj] = None
                                if obj != 'exit':
                                    self.curr_flash = "keycard"
                                    self.flash_time = 60

        # 2.5 Remote players as sprites
        if self.multiplayer:
            for rp in self.remote_players:
                if rp is None:
                    continue
                dist, screen_x, angle, _ = rp.get_render_data_fast(
                    player_pos, player_angle, wall_distances
                )
                if dist is not None:
                    sprites.append((dist, screen_x, rp))

        # 3. Sorteer sprites op afstand (verste eerst)
        sprites.sort(key=lambda x: x[0], reverse=True)
        # 4. Render sprites
        for dist, SCREEN_x, enemy in sprites:
            enemy.render_fast(dist, SCREEN_x)

        if self.player.inv_time > 10:
            SCREEN.blit(DAMAGE_FLASH, (0,0))
        if self.flash_time > 0:
            self.flash_time -= 1
            if self.curr_flash == "keycard":
                SCREEN.blit(KEYCARD_FLASH, (0, 0))
            elif self.curr_flash == "ammo":
                SCREEN.blit(AMMO_FLASH, (0, 0))
            elif self.curr_flash == "health":
                SCREEN.blit(HEALTH_FLASH, (0, 0))
        # 5. Wapen laatst
        self.current_gun.draw()

    def reset_game(self):
        self.multiplayer = False
        self.player_id = 0
        self.remote_players = []
        if self.network_server:
            self.network_server.stop()
            self.network_server = None
        if self.network_client:
            self.network_client.disconnect()
            self.network_client = None
        M.map_level = 0
        # Init objects
        self.state = "game"
        self.current_gun = self.pistol
        self.unlocked_guns = [self.pistol]
        self.player.score = 0
        M.MAP, M.SPAWNS, M.width, M.height  = png_to_list_fast(MAP_PATH[M.map_level])
        self.player = Player(M.SPAWNS["player"][0], M.SPAWNS["player"][1])
        self.global_health = START_HEALTH
        self.global_ammo = START_AMMO
        self._prev_global_health = START_HEALTH
        M.start_angle = START_ANGLES[M.map_level]
        self.player.ammo = START_AMMO
        self.objects = self.create_objects()
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.player_near_exit = False
        self.exit_pos = None
        self.global_paused = False
        self.paused_by = ""
        self._pos_seq = 0
        self.jan_spotted = False
        self.escaped = False
        self.player.door_pos = 0

        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)

        if self.Menu.silly_mode:
            self.main_music = self.funny_music
        else:
            self.main_music = self.normal_music
        self.main_music.play()
        
    def level_up(self):
        M.map_level += 1
        if M.map_level == 1:
            self.unlocked_guns.append(self.minigun)
            self.bilal.trigger("floor_3")
        elif M.map_level == 3:
            self.unlocked_guns.append(self.rifle)
            self.bilal.trigger("floor_1")
        elif M.map_level == 4:
            self.bilal.trigger("floor_0")
        M.MAP, M.SPAWNS, M.width, M.height = png_to_list_fast(MAP_PATH[M.map_level])
        self.player.pos = Vector(M.SPAWNS["player"][0], M.SPAWNS["player"][1])
        self.player.got_keycard = False
        self.player.angle = START_ANGLES[M.map_level]
        self.objects = self.create_objects()
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.player_near_exit = False
        self.exit_pos = None
        self.global_paused = False
        self.paused_by = ""

    #  Multiplayer methods 

    def _start_hosting(self):
        self.multiplayer = True
        self.network_server = ServerIO(self.host_port, MAX_PLAYERS)
        self.network_server.set_host_name(self.player_name)
        self.network_server.start()
        self.network_client = NetworkClient()
        if self.network_client.connect("127.0.0.1", self.host_port, self.player_name):
            self.player_id = self.network_client.player_id
            self.state = "host_lobby"

    def _stop_hosting(self):
        if self.network_client:
            self.network_client.send({"type": "disconnect"})
            self.network_client.disconnect()
            self.network_client = None
        if self.network_server:
            self.network_server.stop()
            self.network_server = None
        self.multiplayer = False
        self.player_id = 0
        self.remote_players = []
        self.global_paused = False
        self.paused_by = ""
        self._pos_seq = 0
        self.state = "menu"

    def _primary_start_game(self):
        """Primary client (player_id=0) sends start_game to server.
        Server broadcasts 'game_start' to ALL clients, including this one."""
        if self.network_client:
            self.network_client.send({"type": "start_game"})

    def _start_multiplayer_client(self):
        self.state = "game"
        M.map_level = 0
        M.MAP, M.SPAWNS, M.width, M.height = png_to_list_fast(MAP_PATH[M.map_level])
        M.start_angle = START_ANGLES[M.map_level]
        self.player = Player(M.SPAWNS["player"][0], M.SPAWNS["player"][1])
        self.global_health = START_HEALTH
        self.global_ammo = START_AMMO
        self._prev_global_health = START_HEALTH
        self.player.door_pos = 0
        self.player.got_keycard = False
        self.current_gun = self.pistol
        self.unlocked_guns = [self.pistol]
        self.remote_players = []
        self.jan = None
        self.jan_spotted = False
        self.escaped = False
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.player_near_exit = False
        self.exit_pos = None
        self.global_paused = False
        self.paused_by = ""
        self._pos_seq = 0
        # Primary client creates objects; remote clients get them via state sync
        if self.player_id == 0:
            self.objects = self.create_objects()
        else:
            self.objects = {"enemies": [], "ammo": [], "keycard": [], "exit": None, "health": []}
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        if self.Menu.silly_mode:
            self.main_music = self.funny_music
        else:
            self.main_music = self.normal_music
        self.main_music.play()

    def _do_connect(self, ip, port, name):
        self.network_client = NetworkClient()
        if self.network_client.connect(ip, port, name):
            self.multiplayer = True
            self.player_id = self.network_client.player_id
            self.player_name = name
            self.state = "waiting_lobby"
        else:
            self.Menu.mp_status = "Verbinding mislukt!"
            if self.network_client:
                self.network_client.disconnect()
                self.network_client = None

    def _disconnect(self):
        if self.network_client:
            for _ in range(3):
                self.network_client.send({"type": "disconnect"})
            import time
            time.sleep(0.05)
            self.network_client.disconnect()
            self.network_client = None
        self.multiplayer = False
        self.player_id = 0
        self.remote_players = []
        self.global_paused = False
        self.paused_by = ""
        self.state = "menu"
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)

    def _get_closest_player(self, enemy):
        closest = self.player
        min_dist = (enemy.pos - closest.pos).norm()
        for rp in self.remote_players:
            if rp is None:
                continue
            dist = (enemy.pos - rp.pos).norm()
            if dist < min_dist:
                min_dist = dist
                closest = rp
        return closest

    def _create_enemy_from_type(self, type_str, pos):
        mapping = {
            "enemies/andrei": Andrei,
            "enemies/ahmed": Ahmed,
            "enemies/ruben": Ruben,
            "enemies/jan": Jan,
        }
        cls = mapping.get(type_str, Andrei)
        return cls(pos[0], pos[1])

    def _send_client_state(self):
        """Send our state to the server. Rate-limited to every 2 frames."""
        self._pos_seq += 1
        if self._pos_seq % 2 != 0:
            return
        packet = {
            "pos": (self.player.pos.x, self.player.pos.y),
            "angle": self.player.angle,
            "health": self.global_health,
            "ammo": self.global_ammo,
            "got_keycard": self.player.got_keycard,
            "door_pos": self.player.door_pos,
            "state": self.state,
            "enemies": [{"pos": (e.pos.x, e.pos.y), "health": e.health, "type": e.type}
                        for e in self.objects.get("enemies", [])],
        }
        if self.player_id == 0:
            obj_data = {}
            for ot in ["ammo", "keycard", "health"]:
                obj_data[ot] = [{"pos": (o.pos.x, o.pos.y)} for o in self.objects.get(ot, [])]
            obj_data["exit"] = {"pos": (self.objects["exit"].pos.x, self.objects["exit"].pos.y)} if self.objects.get("exit") else None
            packet.update({
                "objects": obj_data,
                "level": M.map_level,
                "escaped": self.escaped,
                "jan_spotted": self.jan_spotted,
                "elevator_waiting": self.elevator_waiting,
                "elevator_ready": self.elevator_ready,
                "elevator_wait_timer": self.elevator_wait_timer,
                "exit_pos": (self.exit_pos.x, self.exit_pos.y) if self.exit_pos else None,
                "global_paused": self.global_paused,
                "paused_by": self.paused_by,
            })
        self.network_client.send_input(packet)

    def apply_state(self, state):
        if not state:
            return

        # 1. Per-player health/ammo from server (server is relay, each client is authoritative for own)
        for pdata in state.get("players", []):
            if pdata.get("id") == self.player_id:
                new_health = pdata.get("health", self.global_health)
                if new_health < self.global_health:
                    if new_health < self._prev_global_health:
                        self.player.inv_time = 60
                    self.global_health = new_health
                    self._prev_global_health = self.global_health
                new_ammo = pdata.get("ammo", self.global_ammo)
                if new_ammo < self.global_ammo:
                    self.global_ammo = new_ammo
                break

        # 2. Remote player sprites
        other_players = [p for p in state.get("players", []) if p.get("id") != self.player_id]
        while len(self.remote_players) < len(other_players):
            self.remote_players.append(PlayerSprite(""))
        while len(self.remote_players) > len(other_players):
            self.remote_players.pop()
        for i, pdata in enumerate(other_players):
            self.remote_players[i].pos = Vector(pdata["pos"][0], pdata["pos"][1])
            self.remote_players[i].name = pdata.get("name", f"Player {pdata['id']}")

        # 3. Enemies — primary manages list, non-primary syncs from server
        enemies_data = state.get("enemies", [])
        if self.player_id != 0:
            while len(self.objects["enemies"]) < len(enemies_data):
                edata = enemies_data[len(self.objects["enemies"])]
                self.objects["enemies"].append(self._create_enemy_from_type(edata["type"], edata["pos"]))
            while len(self.objects["enemies"]) > len(enemies_data):
                self.objects["enemies"].pop()
            for i, edata in enumerate(enemies_data):
                self.objects["enemies"][i].pos = Vector(edata["pos"][0], edata["pos"][1])
                self.objects["enemies"][i].health = edata.get("health", 10)
        else:
            for i, edata in enumerate(enemies_data):
                if i < len(self.objects["enemies"]):
                    self.objects["enemies"][i].health = edata.get("health", 10)

        # 4. Objects — primary manages, non-primary syncs from server
        if self.player_id != 0:
            obj_data = state.get("objects", {})
            for ot in ["ammo", "keycard", "health"]:
                server_list = obj_data.get(ot, [])
                while len(self.objects[ot]) < len(server_list):
                    self.objects[ot].append(PickupObject(f"objects/{ot}", 0, 0))
                while len(self.objects[ot]) > len(server_list):
                    self.objects[ot].pop()
                for i, odata in enumerate(server_list):
                    self.objects[ot][i].pos = Vector(odata["pos"][0], odata["pos"][1])
            exit_data = obj_data.get("exit")
            if exit_data and not self.objects["exit"]:
                self.objects["exit"] = PickupObject("objects/exit", exit_data["pos"][0], exit_data["pos"][1])
            elif exit_data and self.objects["exit"]:
                self.objects["exit"].pos = Vector(exit_data["pos"][0], exit_data["pos"][1])
            elif not exit_data:
                self.objects["exit"] = None

        # 5. Game flags
        new_level = state.get("level", M.map_level)
        if new_level != M.map_level:
            M.map_level = new_level
            M.MAP, M.SPAWNS, M.width, M.height = png_to_list_fast(MAP_PATH[new_level])
            M.start_angle = START_ANGLES[new_level]
        self.escaped = state.get("escaped", False)
        self.jan_spotted = state.get("jan_spotted", False)
        self.player.got_keycard = state.get("got_keycard", self.player.got_keycard)
        self.elevator_waiting = state.get("elevator_waiting", False)
        self.elevator_ready = state.get("elevator_ready", False)
        self.elevator_wait_timer = state.get("elevator_wait_timer", 0)
        new_state = state.get("state")
        if new_state and new_state != self.state:
            self.state = new_state
            if new_state == "dead":
                self.global_health = 0
                pygame.mouse.set_visible(True)
        self.global_paused = state.get("global_paused", False)
        self.paused_by = state.get("paused_by", "")
        exit_pos_data = state.get("exit_pos")
        if exit_pos_data:
            self.exit_pos = Vector(exit_pos_data[0], exit_pos_data[1])
        if self.elevator_waiting and self.exit_pos:
            dist = (self.player.pos - self.exit_pos).norm()
            self.player_near_exit = dist < ELEVATOR_WAIT_DIST
        else:
            self.player_near_exit = False

    def handle_network(self):
        if not self.network_client:
            return
        packet = self.network_client.try_recv()
        if packet:
            if packet.get("type") == "state":
                self.apply_state(packet)
            elif packet.get("type") == "game_start":
                self._start_multiplayer_client()
            elif packet.get("type") in ("server_stopped", "disconnect"):
                self._disconnect()
        # Death check: runs on ALL clients; server merges global_health via min()
        if self.global_health <= 0 and self.state == "game":
            self.global_health = 0
            pygame.mouse.set_visible(True)
            self.state = "dead"

    #  Main loop 

    def run(self):
        set_resolution("high")
        self.running = True
        set_resolution("high")
        self.state = "menu"
        self.credits_height = HEIGHT
        while self.running:
            events = self.handle_events()
            self.handle_input()
            if self.state == "menu":
                self.Menu.draw_main_menu(events, self)

            elif self.state == "multiplayer_menu":
                self.Menu.draw_multiplayer_menu(events, self)

            elif self.state == "host_lobby":
                if self.network_client:
                    if not self.Menu.client_list:
                        self.network_client.send({"type": "request_lobby"})
                    packet = self.network_client.try_recv()
                    if packet:
                        if packet.get("type") == "lobby_info":
                            self.Menu.client_list = packet.get("players", [])
                        elif packet.get("type") == "game_start":
                            self._start_multiplayer_client()
                        elif packet.get("type") == "server_stopped":
                            self._disconnect()
                self.Menu.draw_host_lobby(events, self)

            elif self.state == "waiting_lobby":
                if self.network_client:
                    packet = self.network_client.try_recv()
                    if packet:
                        if packet.get("type") == "lobby_info":
                            self.Menu.client_list = packet.get("players", [])
                        elif packet.get("type") == "game_start":
                            self._start_multiplayer_client()
                        elif packet.get("type") == "server_stopped":
                            self._disconnect()
                self.Menu.draw_waiting_lobby(events, self)

            elif self.state == "game":
                self.clock.tick(60)
                if self.multiplayer:
                    self.handle_network()
                if not self.global_paused and (self.player.door_pos == 0 or self.player.door_pos > WIDTH/2 + ELEV_SPEED) and not self.escaped:
                    self.update()
                    self.render()
                    if self.jan is not None and self.jan_spotted:
                        self.jan.draw_health_bar(None, None, None)
                elif self.global_paused:
                    self.render()
                self.Menu.draw_UI(events)
                
                if self.bilal.flags["general"]:
                    self.bilal.update()
                    self.bilal.draw()
                if self.player.got_keycard:
                    self.keycard_font = pygame.font.Font(SILLY_FONT if self.Menu.silly_mode else FONT, 20)
                    self.keycard_font.set_bold(True)
                    SCREEN.blit(self.keycard_font.render("KEYCARD ACQUIRED", True, 'green'),(WIDTH - int(WIDTH * 0.11), HEIGHT - int(HEIGHT * 0.06)))
                    
                if self.escaped:
                    self.Menu.draw_escaped_screen(events, self)
                
                if self.player.door_pos != 0:
                    self.Menu.game = self
                    self.Menu.draw_elevator(events, self.player)

            elif self.state == "paused":
                if self.multiplayer:
                    self.handle_network()
                self.render()
                self.Menu.draw_paused_screen(events, self)
            elif self.state == 'dead':
                self.Menu.draw_dead_screen(events, self)
            elif self.state == "credits":
                self.Menu.draw_credits(events, self)
            elif self.state == 'settings':
               self.Menu.draw_settings(events, self)

            if self.player.death and self.state == "game":
                pygame.mouse.set_visible(True)
                self.state = "dead"
            pygame.display.flip()

        pygame.quit()


if __name__ == "__main__":
    game = Game()
    game.run()