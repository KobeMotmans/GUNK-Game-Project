"""
game.py - Hoofd game loop en initialisatie
"""

import pygame
import random
import time

from src.core.config import (SCREEN, WIDTH, HEIGHT, START_AMMO, AMMO_CAP, DAMAGE_FLASH, AMMO_FLASH, KEYCARD_FLASH,
                    SCREEN_DEAD, START_HEALTH, ELEV_SPEED, MAX_LEVEL, MAP_PATH, START_ANGLES, HEALTH_FLASH, HEALTH_CHANCE, 
                    set_resolution, VICTORY_SCREEN, MENU_BG, ELEV_TIME, MAX_DEPTH,
                    ELEVATOR_WAIT_DIST, ELEVATOR_WAIT_FRAMES)
from src.core.paths import resolve_asset, load_font
from src.core.theme import theme
from src.core.raycaster import dda
from src.assets.texture_cache import preload as preload_textures, clear as clear_texture_cache
from src.entities.weapons import Pistol, Minigun, Rifle
from src.entities.enemies import Andrei, Ahmed, Ruben, Jan
from src.entities.player import Player
from src.ui.Menu import Menu_inst, Bilal
from src.core.map_loader import M, png_to_list_fast
from src.entities.objects import PickupObject, PlayerSprite
from src.assets.skin_manager import SkinManager
from src.core.vector import Vector
from src.network.network import NetworkClient


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

        self.Menu.draw_loading_screen()

        # Init wapens
        self.pistol = Pistol()
        self.minigun = Minigun()
        self.rifle = Rifle()
        self.current_gun = self.pistol
        self.unlocked_guns = [self.pistol]

        self.sfx_volume = 0.3
        self.music_volume = 0.5
        self.curr_flash = ""
        self.flash_time = 0
        self.possible_enemies = [Andrei, Ahmed, Ruben]
        self.jan = None
        self.jan_spotted = False

        self.Menu.draw_loading_screen()

        # Init objects
        self.resolution = "high"

        pygame.mixer.init()

        self.Menu.draw_loading_screen()

        self.main_music = None
        self.sounds = {}
        self._load_sounds()

        self.Menu.draw_loading_screen()

        # Preload all textures at startup (loading screen shown)
        self._preload_all()

        # Multiplayer
        self.multiplayer = False
        self.player_id = 0
        self.player_name = "Player"
        self.skin_id = 0
        self.network_server = None
        self.network_client = None
        self.remote_players = []

        # Elevator wait (multiplayer)
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_wait_timer = 0
        self.player_near_exit = False
        self.exit_pos = None

        self._settings_return = "menu"
        self._paused_frame = None
        self._pending_removes = set()

        # Pos update rate limiting
        self._pos_seq = 0

        # Delta accumulatoren voor server sync
        self._health_delta = 0
        self._ammo_delta = 0
        self._enemy_damage = []
        self._remove_pickup = []

        self.state = "menu"

    def _load_sounds(self):
        self.main_music = pygame.mixer.Sound(resolve_asset(theme.get("sounds.music.main", "sounds/music/esKape Final.ogg")))
        self.main_music.set_volume(self.music_volume)
        self.sounds = {
            "damage": pygame.mixer.Sound(resolve_asset(theme.get("sounds.sfx.damage", "sounds/sfx/damage.ogg"))),
            "ammo":   pygame.mixer.Sound(resolve_asset(theme.get("sounds.sfx.ammo", "sounds/sfx/ammo.ogg"))),
            "key":    pygame.mixer.Sound(resolve_asset(theme.get("sounds.sfx.key", "sounds/sfx/key.ogg"))),
            "drink":  pygame.mixer.Sound(resolve_asset(theme.get("sounds.sfx.drink", "sounds/sfx/drink.ogg"))),
            "elev_ding": pygame.mixer.Sound(resolve_asset(theme.get("sounds.sfx.elevator_ding", "sounds/sfx/elev_ding.ogg"))),
            "victory": pygame.mixer.Sound(resolve_asset(theme.get("sounds.music.victory", "sounds/music/Motivator.ogg"))),
        }
        self.update_sfx_volume()

    def _preload_all(self):
        self.Menu.loading_progress = 0
        self.Menu.draw_loading_screen(0)
        preload_textures(self._get_all_texture_paths(), lambda p: self.Menu.draw_loading_screen(p))

    def reload_all_assets(self):
        self._load_sounds()
        for gun in [self.pistol, self.rifle, self.minigun]:
            gun.reload()
        clear_texture_cache()
        self._preload_all()
        self.Menu._load_bg_texture()

    def update_sfx_volume(self):
        import src.core.config as cfg
        cfg.SFX_VOLUME = self.sfx_volume
        for gun in [self.pistol, self.minigun, self.rifle]:
            gun.shoot_sound.set_volume(self.sfx_volume)
        for s in self.sounds.values():
            s.set_volume(self.sfx_volume)

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
                        pygame.mouse.set_visible(True)
                        pygame.event.set_grab(False)
                        self.state = "paused"
                        pygame.mixer.pause()

                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        if not self.current_gun.auto and self.current_gun.weapon_state == 0:
                            if self.global_ammo >= self.current_gun.ammo_weight:
                                if not self.multiplayer:
                                    self.global_ammo -= self.current_gun.ammo_weight
                                self._ammo_delta -= self.current_gun.ammo_weight
                                hit = self.current_gun.shoot(self.player.pos,self.player.angle,self.objects.get("enemies",[]),self.player,self.current_gun, apply_damage=True)
                                if hit:
                                    idx, pos = hit
                                    self._enemy_damage.append({"enemy_index": idx, "pos": pos, "damage": self.current_gun.damage})

            elif self.state == "paused":
                 if event.type == pygame.KEYDOWN: #unpause
                       if event.key == pygame.K_ESCAPE:
                           pygame.mouse.set_visible(False)
                           pygame.event.set_grab(True)
                           self.state = "game"
                           pygame.mixer.unpause()

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
                        if not self.multiplayer:
                            self.global_ammo -= self.current_gun.ammo_weight
                        self._ammo_delta -= self.current_gun.ammo_weight
                        hit = self.current_gun.shoot(self.player.pos, self.player.angle, self.objects.get("enemies", []), self.player, self.current_gun, apply_damage=True)
                        if hit:
                            idx, pos = hit
                            self._enemy_damage.append({"enemy_index": idx, "pos": pos, "damage": self.current_gun.damage})

        # === Client: send position + state to server (rate-limited) ===
        if self.network_client:
            self._send_client_state()

    def update(self):
        self.current_gun.update()
        self.player.tick()

    def render(self):   #Render alle game elementen
        bg_texture = theme.get("textures.bg")
        if bg_texture:
            if not hasattr(self, '_bg_img') or self._bg_img_path != bg_texture:
                img = pygame.image.load(resolve_asset(bg_texture)).convert()
                self._bg_img = pygame.transform.scale(img, (WIDTH, HEIGHT))
                self._bg_img_path = bg_texture
            SCREEN.blit(self._bg_img, (0, 0))
        else:
            bg = theme.color("bg", (0, 0, 0))
            SCREEN.fill(tuple(bg) if bg else 'black')


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
                        if not self.multiplayer:
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
                    if self.state == "game":
                        if self.multiplayer:
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
                for item in list(self.objects["ammo"]):
                    dist, SCREEN_x, angle, is_hit = item.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, item))
                    if is_hit:
                        self.curr_flash = "ammo"
                        self.flash_time = 60
                        old = self.global_ammo
                        item.interact(self.player, self)
                        if self.multiplayer:
                            self.global_ammo = old
                            self._remove_pickup.append({"type": "ammo", "pos": (item.pos.x, item.pos.y)})
                            self._pending_removes.add(("ammo", round(item.pos.x, 1), round(item.pos.y, 1)))
                        else:
                            self._ammo_delta += self.global_ammo - old
                        self.objects["ammo"].remove(item)
            elif obj == "health":
                for item in list(self.objects["health"]):
                    dist, SCREEN_x, angle, is_hit = item.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, item))
                    if is_hit:
                        self.curr_flash = "health"
                        self.flash_time = 60
                        old = self.global_health
                        item.interact(self.player, self)
                        if self.multiplayer:
                            self.global_health = old
                            self._remove_pickup.append({"type": "health", "pos": (item.pos.x, item.pos.y)})
                            self._pending_removes.add(("health", round(item.pos.x, 1), round(item.pos.y, 1)))
                        else:
                            self._health_delta += self.global_health - old
                        self.objects["health"].remove(item)
            elif obj == "keycard":
                for item in list(self.objects["keycard"]):
                    dist, SCREEN_x, angle, is_hit = item.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, item))
                    if is_hit:
                        self.curr_flash = "keycard"
                        self.flash_time = 60
                        item.interact(self.player, self)
                        if self.multiplayer:
                            self._remove_pickup.append({"type": "keycard", "pos": (item.pos.x, item.pos.y)})
                            self._pending_removes.add(("keycard", round(item.pos.x, 1), round(item.pos.y, 1)))
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
                                if self.player.got_keycard:
                                    if not self.elevator_waiting and not self.elevator_ready:
                                        self.elevator_waiting = True
                                        self.exit_pos = Vector(item.pos.x, item.pos.y)
                                        self.objects[obj] = None
                                else:
                                    item.interact(self.player, self)  # Renders NO KEYCARD
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

    def _get_all_texture_paths(self):
        paths = []
        for t in ["andrei", "ahmed", "ruben", "jan"]:
            paths.append(resolve_asset(theme.get(f"textures.enemies.{t}", f"textures/enemies/{t}.png")))
        for t in ["ammo", "health", "keycard", "exit"]:
            paths.append(resolve_asset(theme.get(f"textures.objects.{t}", f"textures/objects/{t}.png")))
        weapon_size = theme.get("sizes.weapon.texture", (300, 300))
        for gun in ["pistol", "rifle", "minigun"]:
            for part in ["GUN", "GUN_recoil", "GUN_muzzle"]:
                path = resolve_asset(theme.get(f"textures.weapons.{gun}.{part}", f"textures/weapons/{gun}/{part}.png"))
                paths.append((path, weapon_size))
        return paths

    def _preload_textures(self, target_state):
        self.Menu.loading_progress = 0
        self.Menu.draw_loading_screen(0)
        preload_textures(self._get_all_texture_paths(), lambda p: self.Menu.draw_loading_screen(p))
        self.state = target_state

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
        M.start_angle = START_ANGLES[M.map_level]
        self.objects = self.create_objects()
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_transition = False
        self.elevator_wait_timer = 0
        self.player_near_exit = False
        self.exit_pos = None
        self._pos_seq = 0
        self._pending_removes.clear()
        self.jan_spotted = False
        self.escaped = False
        self.player.door_pos = 0

        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)

        self.main_music.stop()
        self.main_music.set_volume(self.music_volume)
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
        self.elevator_transition = False
        self.elevator_wait_timer = 0
        self.player_near_exit = False
        self.exit_pos = None

    #  Multiplayer methods 

    def _primary_start_game(self):
        """Primary client (player_id=0) sends start_game to server.
        Server broadcasts 'game_start' to ALL clients, including this one."""
        if self.network_client:
            self.network_client.send({"type": "start_game"})

    def _start_multiplayer_client(self, level=0):
        M.map_level = level
        M.MAP, M.SPAWNS, M.width, M.height = png_to_list_fast(MAP_PATH[level])
        M.start_angle = START_ANGLES[M.map_level]
        self.player = Player(M.SPAWNS["player"][0], M.SPAWNS["player"][1])
        self.global_health = START_HEALTH
        self.global_ammo = START_AMMO
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
        self.elevator_transition = False
        self.elevator_wait_timer = 0
        self.exit_pos = None
        self._pos_seq = 0
        self._health_delta = 0
        self._ammo_delta = 0
        self._enemy_damage = []
        self._remove_pickup = []
        self._pending_removes.clear()
        # All objects come from server sync — start empty
        self.objects = {"enemies": [], "ammo": [], "keycard": [], "exit": None, "health": []}
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        self.main_music.stop()
        self.main_music.set_volume(self.music_volume)
        self.main_music.play()
        self.state = "game"

    def _do_connect(self, ip, port, name):
        self.skin_id = self.Menu.mp_skin_id
        self.network_client = NetworkClient()
        if self.network_client.connect(ip, port, name, self.skin_id):
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
        self._pending_removes.clear()
        self.state = "menu"
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)

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
        """Send deltas to the server. Rate-limited to every 2 frames."""
        if self.state not in ("game", "paused"):
            return
        self._pos_seq += 1
        if self._pos_seq % 2 != 0:
            return
        packet = {
            "seq": self._pos_seq,
            "pos": (self.player.pos.x, self.player.pos.y),
            "health_delta": self._health_delta,
            "ammo_delta": self._ammo_delta,
            "enemy_damage": self._enemy_damage,
            "remove_pickup": self._remove_pickup,
            "got_keycard": self.player.got_keycard,
            "door_closed": self.player.door_pos > WIDTH // 2,
            "elevator_waiting": self.elevator_waiting,
            "state": self.state,
        }
        self._health_delta = 0
        self._ammo_delta = 0
        self._enemy_damage = []
        self._remove_pickup = []
        self.network_client.send_input(packet)

    def apply_state(self, state):
        if not state:
            return

        # 1. Overwrite shared resources from server (absolute values)
        self.global_health = state.get("global_health", self.global_health)
        self.global_ammo = state.get("global_ammo", self.global_ammo)
        self.player.got_keycard = state.get("keycard_acquired", self.player.got_keycard)

        # 2. Players — sync own state flags from server (not pos/angle — client-authoritative movement)
        players_data = state.get("players", [])
        for pdata in players_data:
            if pdata.get("id") == self.player_id:
                self.player.score = pdata.get("score", self.player.score)
                if state.get("elevator_transition") and self.player.door_pos == 0:
                    self.player.door_pos = 1
        other_players = [p for p in players_data if p.get("id") != self.player_id]
        while len(self.remote_players) < len(other_players):
            self.remote_players.append(PlayerSprite(""))
        while len(self.remote_players) > len(other_players):
            self.remote_players.pop()
        for i, pdata in enumerate(other_players):
            self.remote_players[i].pos = Vector(pdata["pos"][0], pdata["pos"][1])
            self.remote_players[i].name = pdata.get("name", f"Player {pdata['id']}")
            skin_id = pdata.get("skin_id", 0)
            if hasattr(self.remote_players[i], 'set_skin'):
                self.remote_players[i].set_skin(skin_id)

        # 3. Enemies — full sync from server (ALL clients)
        enemies_data = state.get("enemies", [])
        while len(self.objects["enemies"]) < len(enemies_data):
            edata = enemies_data[len(self.objects["enemies"])]
            self.objects["enemies"].append(self._create_enemy_from_type(edata["type"], edata["pos"]))
        while len(self.objects["enemies"]) > len(enemies_data):
            self.objects["enemies"].pop()
        self.jan = None
        for i, edata in enumerate(enemies_data):
            new_type = edata.get("type", "")
            if self.objects["enemies"][i].type != new_type:
                self.objects["enemies"][i] = self._create_enemy_from_type(new_type, edata["pos"])
            self.objects["enemies"][i].pos = Vector(edata["pos"][0], edata["pos"][1])
            self.objects["enemies"][i].health = edata.get("health", 10)
            if new_type == "enemies/jan":
                self.jan = self.objects["enemies"][i]

        # 4. Objects — full sync from server (ALL clients)
        obj_data = state.get("objects", {})
        for ot in ["ammo", "keycard", "health"]:
            server_raw = obj_data.get(ot, [])
            server_list = [o for o in server_raw
                           if (ot, round(o["pos"][0], 1), round(o["pos"][1], 1)) not in self._pending_removes]
            while len(self.objects[ot]) < len(server_list):
                self.objects[ot].append(PickupObject(f"objects/{ot}", 0, 0))
            while len(self.objects[ot]) > len(server_list):
                self.objects[ot].pop()
            for i, odata in enumerate(server_list):
                self.objects[ot][i].pos = Vector(odata["pos"][0], odata["pos"][1])
            # Clean up pending removes that server has confirmed
            raw_positions = {(round(o["pos"][0], 1), round(o["pos"][1], 1)) for o in server_raw}
            self._pending_removes = {r for r in self._pending_removes
                                     if r[0] != ot or r[1:] in raw_positions}
        exit_data = obj_data.get("exit")
        if exit_data and not self.objects["exit"]:
            self.objects["exit"] = PickupObject("objects/exit", exit_data["pos"][0], exit_data["pos"][1])
        elif exit_data and self.objects["exit"]:
            self.objects["exit"].pos = Vector(exit_data["pos"][0], exit_data["pos"][1])
        elif not exit_data:
            self.objects["exit"] = None

        # 5. World state
        new_level = state.get("level", M.map_level)
        if new_level != M.map_level:
            M.map_level = new_level
            M.MAP, M.SPAWNS, M.width, M.height = png_to_list_fast(MAP_PATH[new_level])
            M.start_angle = START_ANGLES[new_level]
            for pdata in players_data:
                if pdata.get("id") == self.player_id:
                    self.player.pos = Vector(pdata["pos"][0], pdata["pos"][1])
                    self.player.angle = pdata.get("angle", M.start_angle)
                    break
            if M.map_level == 1:
                if self.minigun not in self.unlocked_guns:
                    self.unlocked_guns.append(self.minigun)
                self.bilal.trigger("floor_3")
            elif M.map_level == 3:
                if self.rifle not in self.unlocked_guns:
                    self.unlocked_guns.append(self.rifle)
                self.bilal.trigger("floor_1")
            elif M.map_level == 4:
                self.bilal.trigger("floor_0")
            self.elevator_waiting = False
            self.elevator_ready = False
            self.elevator_transition = False
            self.elevator_wait_timer = 0
            self.player_near_exit = False
            self.player.got_keycard = False
            self.exit_pos = None
        self.state = state.get("state", self.state)
        self.escaped = state.get("escaped", self.escaped)
        self.elevator_waiting = state.get("elevator_waiting", self.elevator_waiting)
        self.elevator_ready = state.get("elevator_ready", self.elevator_ready)
        self.elevator_transition = state.get("elevator_transition", False)
        self.elevator_wait_timer = state.get("elevator_wait_timer", self.elevator_wait_timer)

        # 6. Player proximity to exit (for UI message)
        exit_data = state.get("exit_pos")
        if exit_data:
            self.exit_pos = Vector(exit_data[0], exit_data[1])
        self.player_near_exit = (
            self.elevator_waiting
            and self.exit_pos is not None
            and (self.player.pos - self.exit_pos).norm() < ELEVATOR_WAIT_DIST
        )

    def handle_network(self):
        if not self.network_client:
            return
        packet = self.network_client.try_recv()
        if packet:
            if packet.get("type") == "state":
                self.apply_state(packet)
            elif packet.get("type") == "game_start":
                self._start_multiplayer_client(packet.get("level", 0))
            elif packet.get("type") in ("server_stopped", "disconnect"):
                self._disconnect()
            elif packet.get("type") == "skin_manifest_update":
                SkinManager.set_manifest(packet.get("skin_manifest", []))
                SkinManager.download_all_skins()
        if self.global_health <= 0 and self.state in ("game", "paused"):
            self.global_health = 0
            pygame.mouse.set_visible(True)
            self.state = "dead"

    #  Main loop 

    def run(self):
        set_resolution("high")
        self.running = True
        self.state = "menu"
        self.credits_height = HEIGHT
        while self.running:
            events = self.handle_events()
            self.handle_input()
            if self.state == "menu":
                self.Menu.draw_main_menu(events, self)

            elif self.state == "multiplayer_menu":
                self.Menu.draw_multiplayer_menu(events, self)

            elif self.state == "waiting_lobby":
                if self.network_client:
                    packet = self.network_client.try_recv()
                    if packet:
                        if packet.get("type") == "lobby_info":
                            self.Menu.client_list = packet.get("players", [])
                        elif packet.get("type") == "game_start":
                            self._start_multiplayer_client(packet.get("level", 0))
                        elif packet.get("type") == "server_stopped":
                            self._disconnect()
                        elif packet.get("type") == "skin_manifest_update":
                            SkinManager.set_manifest(packet.get("skin_manifest", []))
                            SkinManager.download_all_skins()
                    now = time.time()
                    if now - getattr(self, '_last_lobby_ping', 0) > 2.0:
                        self.network_client.send({"type": "ping"})
                        self._last_lobby_ping = now
                self.Menu.draw_waiting_lobby(events, self)

            elif self.state == "game":
                self.clock.tick(60)
                if self.multiplayer:
                    self.handle_network()

                if (self.player.door_pos == 0 or self.player.door_pos > WIDTH/2 + ELEV_SPEED) and not self.escaped:
                    self.update()
                    self.render()
                    if self.jan is not None and self.jan_spotted:
                        self.jan.draw_health_bar(None, None, None)
                    if self.bilal.flags["general"]:
                        self.bilal.update()
                        self.bilal.draw()
                self.Menu.draw_UI(events)
                
                if self.player.got_keycard:
                    self.keycard_font = load_font(20, bold=True)
                    kc_surf = self.keycard_font.render("KEYCARD ACQUIRED", True, 'green')
                    SCREEN.blit(kc_surf, (WIDTH - kc_surf.get_width() - int(WIDTH * 0.04), HEIGHT - int(HEIGHT * 0.06)))
                    
                if self.escaped:
                    self.Menu.draw_escaped_screen(events, self)
                
                if self.player.door_pos != 0:
                    self.Menu.game = self
                    self.Menu.draw_elevator(events, self.player)

            elif self.state == "paused":
                self.handle_network()
                if self._paused_frame:
                    SCREEN.blit(self._paused_frame, (0, 0))
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
            if self.state == "game":
                self._paused_frame = SCREEN.copy()
            pygame.display.flip()

        pygame.quit()


if __name__ == "__main__":
    game = Game()
    game.run()