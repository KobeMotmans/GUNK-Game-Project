"""
game.py - Hoofd game loop en initialisatie
"""

import pygame
import random
import time
import os
import json
import threading
from math import atan2, cos, sin, tan, pi, hypot

from src.core import config as cfg
from src.core.config import (START_AMMO, MAP_PATH, START_ANGLES, HEALTH_CHANCE, MAX_LEVEL, MAX_DEPTH,
                    set_resolution, ELEVATOR_WAIT_DIST, START_HEALTH, TILE_SIZE, PROJ_DIST, MAX_PLAYERS)
from src.core.paths import resolve_asset, load_font, init_packs
from src.core.theme import theme
from src.core.raycaster import dda
from src.assets.texture_cache import preload as preload_textures, clear as clear_texture_cache
from src.entities.weapons import Pistol, Minigun, Rifle
from src.entities.enemies import NormalEnemy, FastEnemy, TankEnemy, FinalBoss, Fireball
from src.entities.player import Player
from src.ui.Menu import Menu_inst, Bilal
from src.core.map_loader import M, png_to_list_fast
from src.entities.objects import PickupObject, PlayerSprite
from src.assets.skin_manager import SkinManager
from src.core.vector import Vector
from src.network.network import NetworkClient, ServerIO
from src.network.port_map import (discover, find_gateway, PortMappingKeeper)
from src.network.discovery import DiscoveryResponder, DiscoveryListener
from src.core.logger import log as _log, clear_log

# Interpolatie van de andere spelers: de server stuurt 30 snapshots per
# seconde, het scherm tekent 60 keer per seconde.
REMOTE_SNAPSHOT_HZ = 30.0
REMOTE_INTERP_DELAY = 1.0 / REMOTE_SNAPSHOT_HZ  # één snapshot achter renderen
REMOTE_MAX_SAMPLES = 8                        # ruimte voor wat packetverlies



class Game:
    def __init__(self):
        pygame.init()
        pygame.key.set_repeat(400, 50)
        self.clock = pygame.time.Clock()
        self.running = False
        self.state = None
        self.escaped = False

        #Init Bilal/Tutorial
        self.Menu = Menu_inst
        self.bilal = Bilal(self)
        self.bilal.say("Welkom bij GUNK!", 100)
        self.bilal.say("Gebruik je muis om rond te kijken en ZQSD om te bewegen", 200)
        self.bilal.say("Je zit vast op verdieping 5 van het K gebouw. Probeer via de lift te ontsnappen.", 250)
        self.bilal.say("Er moet in n van deze kamers een keycard liggen. Zoek hem!", 200)
        self.bilal.say("Maar pas op, want de andere assistenten zijn gek geworden van het K gebouw!", 200)

        # Init speler
        self.player = Player(M.SPAWNS["player"][0], M.SPAWNS["player"][1], angle=START_ANGLES[0])
        self.global_health = START_HEALTH
        self.global_ammo = START_AMMO

        # Init map reference
        self.map = M.MAP

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
        self.ammo_rays = []
        self.possible_enemies = [NormalEnemy, FastEnemy, TankEnemy]
        self.final_boss = None
        self.final_boss_spotted = False
        self.boss_music = None
        self.boss_music_playing = False

        # Init objects
        self.resolution = "high"

        pygame.mixer.init()

        init_packs()

        self.Menu.draw_loading_screen(0, "Loading sounds...")
        pygame.event.pump()

        self.main_music_intro = None
        self.main_music_loop = None
        self._has_intro = False
        self._intro_duration = 0
        self._intro_start = 0
        self._main_loop_started = False
        self._intro_channel = None
        self.sounds = {}
        self._load_sounds()

        # Preload all textures at startup (loading screen shown)
        self._preload_all()

        self.Menu._fill_bg()
        pygame.display.flip()

        # Multiplayer
        self.multiplayer = False
        self.player_id = 0
        self.player_name = "Player"
        self.skin_id = 0
        self.network_server = None
        self.network_client = None
        self.remote_players = []
        self._remote_tracks = {}
        self.host_pid = -1
        self.lobby_options = {"shared_health": True, "shared_ammo": True}
        self.is_host = False
        self.objects = {}
        self.projectiles = []

        # Zelf hosten (de server draait dan in dit proces mee)
        self.hosted_server = None
        self.hosted_address = None
        self.hosted_port = None
        self.mapping_keeper = None
        self.discovery_responder = None
        self.discovery_listener = None

        # Kijken naar de groep na je eigen dood
        self.spectating = False
        self._spectate_pid = None
        self._spectate_name = ""
        self._spectate_info = {}

        # Elevator
        self.keycard_acquired = False
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_locked = False
        self.elevator_wait_timer = 0
        self.player_near_exit = False
        self.elevator_pending = [0, 0]
        self.exit_pos = None

        # Minimap
        self.minimap_show_enemies = True
        self.minimap_show_objects = True

        self._settings_return = "menu"
        self._paused_frame = None
        self._pending_removes = set()

        # Pos update rate limiting
        self._pos_seq = 0
        self._last_server_packet = 0
        self._last_lobby_ping = 0

        # Delta accumulatoren voor server sync
        self._health_delta = 0
        self._ammo_delta = 0
        self._enemy_damage = []
        self._remove_pickup = []

        # Het levelnummer dat de client zelf daadwerkelijk geladen heeft.
        # Bewust een eigen teller en géén M.map_level: bij zelfhosten deelt
        # de server M met de client en loopt M.map_level vooruit. Zie de
        # teleport in apply_state.
        self._client_loaded_level = None

        self._load_settings()
        self.update_sfx_volume()
        if self.main_music_intro:
            self.main_music_intro.set_volume(self.music_volume)
        if self.main_music_loop:
            self.main_music_loop.set_volume(self.music_volume)
        set_resolution(self.resolution)
        clear_log()
        _log("Game started")
        self.state = "menu"

    def _silence_music(self):
        """Zet alle muziek stil en vergeet dat er een intro onderweg was.

        Nodig omdat pygame.mixer.stop() buiten ons om alle kanalen afsluit,
        maar _maybe_start_main_loop niet vertelt dat de intro gestopt is.
        Die zag daarna een vrij kanaal, concludeerde "de intro is klaar" en
        zette de main loop op. In de lobby is dat precies wat niemand
        wilde horen.

        _main_loop_started gaat bewust op True: er komt niets meer, en dat
        is precies de toestand waarin _maybe_start_main_loop niets hoeft te
        doen. Zo hoeft die functie niet te weten waaróm het stil is.
        """
        if self.main_music_intro:
            self.main_music_intro.stop()
        self.main_music_loop.stop()
        if self.boss_music:
            self.boss_music.stop()
        self.boss_music_playing = False
        self._intro_start = 0
        self._intro_channel = None
        self._main_loop_started = True

    def _play_music(self):
        if self.boss_music_playing:
            self.boss_music_playing = False
            if self.boss_music:
                self.boss_music.stop()
        self.main_music_loop.stop()
        if self.main_music_intro:
            self.main_music_intro.stop()
            self.main_music_intro.set_volume(self.music_volume)
        self.main_music_loop.set_volume(self.music_volume)
        self._intro_start = pygame.time.get_ticks()
        self._main_loop_started = False
        self._intro_channel = None
        if self._has_intro:
            self._intro_channel = self.main_music_intro.play()
        else:
            self._main_loop_started = True
            self.main_music_loop.play(loops=-1)

    def _maybe_start_main_loop(self):
        """Zet de main loop op zodra de intro echt uitgespeeld is.

        Vroeger ging dat op de klok: na _intro_duration milliseconden was
        de loop een feit, hoe de muziek er ook bij stond. Dat loopt
        misverstanden als je in die tijd pauzeert, want de klok loopt
        gewoon door terwijl de audio stilstaat. De intro bleef bevroren
        op zijn kanaal en de loop begon ernaast, dus na het hervatten
        speelden ze over elkaar heen.

        Vandaar dat we het kanaal van de intro vasthouden en pas loslaten
        als dat kanaal niet meer bezet is. Dat klopt ook zonder pauze:
        dan is de intro op dat moment echt klaar.
        """
        if self._main_loop_started or not self._intro_start:
            return
        # Buiten het spel hoort geen muziek. De lobby gebruikt precies
        # dezelfde intro->loop-overgang als het spel, dus zonder deze
        # controle begint de loop daar zodra de intro uit is.
        if self.state not in ("game", "paused", "dead", "spectating"):
            return
        if self._intro_channel is not None and self._intro_channel.get_busy():
            return
        self._main_loop_started = True
        self.main_music_loop.play(loops=-1)

    def _settings_path(self):
        return os.path.join(os.path.dirname(__file__), "settings.json")

    def save_settings(self):
        data = {
            "sfx_volume": self.sfx_volume,
            "music_volume": self.music_volume,
            "resolution": self.resolution,
            "tutorial": self.bilal.flags["general"],
        }
        try:
            with open(self._settings_path(), "w") as f:
                json.dump(data, f)
        except OSError:
            pass

    def _load_settings(self):
        try:
            with open(self._settings_path()) as f:
                data = json.load(f)
            self.sfx_volume = data.get("sfx_volume", self.sfx_volume)
            self.music_volume = data.get("music_volume", self.music_volume)
            self.resolution = data.get("resolution", self.resolution)
            self.bilal.flags["general"] = data.get("tutorial", self.bilal.flags["general"])
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _load_sounds(self):
        if self.main_music_intro:
            self.main_music_intro.stop()
        if self.main_music_loop:
            self.main_music_loop.stop()
        for s in self.sounds.values():
            try: s.stop()
            except: pass

        intro_path = theme.get("sounds.music.main_intro")
        if intro_path:
            self.main_music_intro = pygame.mixer.Sound(resolve_asset(intro_path))
            self._has_intro = True
            self._intro_duration = int(self.main_music_intro.get_length() * 1000)
        else:
            self.main_music_intro = None
            self._has_intro = False
            self._intro_duration = 0

        loop_path = theme.get("sounds.music.main") or theme.get("sounds.music.main_loop", "sounds/music/esKape Main Loop.ogg")
        self.main_music_loop = pygame.mixer.Sound(resolve_asset(loop_path))
        if self.main_music_intro:
            self.main_music_intro.set_volume(self.music_volume)
        self.main_music_loop.set_volume(self.music_volume)
        self._intro_start = 0
        self._main_loop_started = False
        self._intro_channel = None
        self.Menu.draw_loading_screen(0.15, "Loading music...")
        pygame.event.pump()
        self.sounds = {
            "damage": pygame.mixer.Sound(resolve_asset(theme.get("sounds.sfx.damage", "sounds/sfx/damage.ogg"))),
            "ammo":   pygame.mixer.Sound(resolve_asset(theme.get("sounds.sfx.ammo", "sounds/sfx/ammo.ogg"))),
            "key":    pygame.mixer.Sound(resolve_asset(theme.get("sounds.sfx.key", "sounds/sfx/key.ogg"))),
            "drink":  pygame.mixer.Sound(resolve_asset(theme.get("sounds.sfx.drink", "sounds/sfx/drink.ogg"))),
            "elev_ding": pygame.mixer.Sound(resolve_asset(theme.get("sounds.sfx.elevator_ding", "sounds/sfx/elev_ding.ogg"))),
            "victory": pygame.mixer.Sound(resolve_asset(theme.get("sounds.music.victory", "sounds/music/Motivator.ogg"))),
        }
        boss_path = theme.get("sounds.music.boss")
        if boss_path:
            self.boss_music = pygame.mixer.Sound(resolve_asset(boss_path))
            self.boss_music.set_volume(self.music_volume)
        else:
            self.boss_music = None
        self.boss_music_playing = False

        self.Menu.draw_loading_screen(0.40, "Loading sound effects...")
        pygame.event.pump()
        self.update_sfx_volume()

    def _preload_all(self):
        preload_textures(self._get_all_texture_paths(), lambda p, path: self.Menu.draw_loading_screen(p, os.path.basename(path)))

    def reload_all_assets(self):
        self._load_sounds()
        for gun in [self.pistol, self.rifle, self.minigun]:
            gun.reload()
        clear_texture_cache()
        self._preload_all()
        self.Menu._load_bg_texture()
        if hasattr(self, 'objects'):
            for obj_list in self.objects.values():
                if isinstance(obj_list, list):
                    for obj in obj_list:
                        if hasattr(obj, 'reload_texture'):
                            obj.reload_texture()
                elif obj_list is not None and hasattr(obj_list, 'reload_texture'):
                    obj_list.reload_texture()
        if self.current_gun:
            self.current_gun.reload()
        self.update_sfx_volume()

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
        if "final_boss" in M.SPAWNS:
            boss_pos = M.SPAWNS["final_boss"]
            boss = FinalBoss(boss_pos[0], boss_pos[1])
            self.final_boss = boss
            enemies.append(boss)
        return enemies

    def create_objects(self):
        objects = {
            "exit": PickupObject("objects/exit", M.SPAWNS["end_point"][0], M.SPAWNS["end_point"][1]),
            "enemies": self.create_enemies(),
            "ammo": [],
            "keycard": [],
            "health": []
        }
        for ammo_pos in M.SPAWNS["ammo"]:
            objects["ammo"].append(PickupObject("objects/ammo", ammo_pos[0], ammo_pos[1]))
        if M.SPAWNS["keycard"]:
            keycard_pos = M.SPAWNS["keycard"][random.randint(0, len( M.SPAWNS["keycard"])-1)]
            objects["keycard"].append(PickupObject("objects/keycard", keycard_pos[0], keycard_pos[1]))
        
        return objects

    def handle_events(self):
        """Verwerk pygame events"""
        events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                self.running = False

            if event.type == pygame.VIDEORESIZE:
                self.Menu._minimap_bg = None
                cfg.resize_display(event.w, event.h)

            if self.state == "spectating":
                # Naar de volgende of vorige teamgenoot kijken, of stoppen.
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_e:
                        self._cycle_spectate_target(1)
                    elif event.key == pygame.K_q:
                        self._cycle_spectate_target(-1)
                    elif event.key == pygame.K_ESCAPE:
                        self._stop_spectating()

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
                                hit = self.current_gun.shoot(self.player.pos,self.player.angle,self.objects.get("enemies",[]), apply_damage=True)
                                self._store_ammo_ray(hit)
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

        if self.state == "game" and not self.escaped and not self.elevator_locked:
            # === UNIFIED: all players move and auto-fire locally ===
            self.player.rotate(pygame.mouse.get_rel()[0])
            pygame.mouse.set_pos(cfg.WIDTH // 2, cfg.HEIGHT // 2)
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
                        hit = self.current_gun.shoot(self.player.pos, self.player.angle, self.objects.get("enemies", []), apply_damage=True)
                        self._store_ammo_ray(hit)
                        if hit:
                            idx, pos = hit
                            self._enemy_damage.append({"enemy_index": idx, "pos": pos, "damage": self.current_gun.damage})

        # === Client: send position + state to server (rate-limited) ===
        if self.network_client:
            self._send_client_state()

    def _store_ammo_ray(self, hit):
        dx = cos(self.player.angle)
        dy = sin(self.player.angle)
        if hit:
            _, pos = hit
            end = Vector(pos[0], pos[1])
        else:
            end = self.player.pos + Vector(dx * MAX_DEPTH, dy * MAX_DEPTH)
        self.ammo_rays.append({"start": Vector(self.player.pos.x, self.player.pos.y), "end": end, "timer": 6, "is_hit": hit is not None})

    def update(self):
        self.current_gun.update()
        self.player.tick()

    def render(self):   #Render alle game elementen
        bg_texture = theme.get("textures.bg")
        if bg_texture:
            if not hasattr(self, '_bg_img') or self._bg_img_path != bg_texture:
                img = pygame.image.load(resolve_asset(bg_texture)).convert()
                self._bg_img = pygame.transform.scale(img, (cfg.WIDTH, cfg.HEIGHT))
                self._bg_img_path = bg_texture
            cfg.SCREEN.blit(self._bg_img, (0, 0))
        else:
            bg = theme.color("bg", (0, 0, 0))
            cfg.SCREEN.fill(tuple(bg) if bg else 'black')


        player_pos = self.player.get_pos()
        player_angle = self.player.get_angle()

        # 1. Raycasting - muren direct tekenen, afstanden opslaan
        wall_distances = dda(player_pos, player_angle)

        # 2. Verzamel zichtbare sprites
        sprites = []  # (dist, SCREEN_x, enemy)
        for obj in self.objects.keys():
            if obj == "enemies":
                for enemy in list(self.objects[obj]):
                    if enemy.hit_timer > 0:
                        enemy.hit_timer -= 1
                    if enemy.health <= 0:
                        if not self.multiplayer:
                            self.player.score += 1
                            self.objects["enemies"].remove(enemy)
                            if enemy.type == "enemies/final_boss":
                                self.objects["keycard"].append(PickupObject("objects/keycard", enemy.pos.x, enemy.pos.y))
                                self.final_boss = None
                                self.bilal.say("Je hebt het gedaan! Zorg dat je nu zo snel mogelijk buiten staat!")
                                if self.boss_music_playing:
                                    self.boss_music_playing = False
                                    if self.boss_music:
                                        self.boss_music.stop()
                                    self._play_music()
                            else:
                                if random.random() < HEALTH_CHANCE:
                                    self.objects["health"].append(PickupObject("objects/health", enemy.pos.x, enemy.pos.y))
                                    self.bilal.trigger("monster")
                        continue
                    if self.state == "game" and not self.elevator_locked:
                        if self.multiplayer:
                            result = enemy.find_path(self.player, self, True, False)
                            if result is not None:
                                self.projectiles.append(result)
                        else:
                            result = enemy.find_path(self.player, self, True, True)
                            if result is not None:
                                self.projectiles.append(result)
                    dist, SCREEN_x, angle, _ = enemy.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, enemy))
                        self.bilal.trigger("seen_enemy")
                        if enemy.type == "enemies/final_boss":
                            self.final_boss_spotted = True
                            self.bilal.trigger("boss_warning")
                            if self.boss_music and not self.boss_music_playing:
                                self.boss_music_playing = True
                                self.main_music_loop.stop()
                                if self.main_music_intro:
                                    self.main_music_intro.stop()
                                # De baas neemt het over. Zet de
                                # intro-overgang klaar, anders start de
                                # main loop hierna alsnog bovenop de
                                # baasmuziek in plaats van erna.
                                self._main_loop_started = True
                                self._intro_channel = None
                                self.boss_music.play(loops=-1)
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
                                if self.keycard_acquired or self.player.got_keycard:
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
            # Namen door muren renderen voor alle remote players binnen bereik
            for rp in self.remote_players:
                if rp is None or not rp.name:
                    continue
                _dist, _screen_x, _rel_angle = rp.get_screen_pos(player_pos, player_angle)
                if 0 < _dist < 1500 and abs(_rel_angle) <= cfg.FOV / 2:
                    rp.render_name_through_walls(_dist, _screen_x)

        # 3. Sorteer sprites op afstand (verste eerst)
        sprites.sort(key=lambda x: x[0], reverse=True)
        # 4. Render sprites
        for dist, SCREEN_x, enemy in sprites:
            enemy.render_fast(dist, SCREEN_x)

        # Update and render projectiles
        self.projectiles = [p for p in self.projectiles if p.alive]
        frozen = self.elevator_locked
        for p in self.projectiles:
            if not frozen:
                p.update(self.player, self)
            dist, screen_x, _, _ = p.get_render_data_fast(player_pos, player_angle, wall_distances)
            if dist is not None:
                p.render_fast(dist, screen_x)

        if self.player.inv_time > 10:
            cfg.SCREEN.blit(cfg.DAMAGE_FLASH, (0,0))
        if self.flash_time > 0:
            self.flash_time -= 1
            if self.curr_flash == "keycard":
                cfg.SCREEN.blit(cfg.KEYCARD_FLASH, (0, 0))
            elif self.curr_flash == "ammo":
                cfg.SCREEN.blit(cfg.AMMO_FLASH, (0, 0))
            elif self.curr_flash == "health":
                cfg.SCREEN.blit(cfg.HEALTH_FLASH, (0, 0))

        # Draw ammo rays
        for ray in list(self.ammo_rays):
            ray["timer"] -= 1
            delta = ray["end"] - self.player.pos
            dist = delta.norm()
            if dist > 1:
                rel_angle = atan2(delta.y, delta.x) - self.player.angle
                while rel_angle > pi: rel_angle -= 2 * pi
                while rel_angle < -pi: rel_angle += 2 * pi
                if abs(rel_angle) <= pi / 4 and dist <= MAX_DEPTH:
                    screen_x = cfg.WIDTH / 2 + tan(rel_angle) * PROJ_DIST
                    start_y = cfg.HEIGHT - 280
                    end_y = cfg.HEIGHT / 2
                    alpha = int(255 * (ray["timer"] / 6))
                    color = (180, 180, 180)
                    pygame.draw.line(cfg.SCREEN, color,
                                     (cfg.WIDTH / 2, start_y),
                                     (screen_x, end_y), max(1, int(3 * ray["timer"] / 6)))
            if ray["timer"] <= 0:
                self.ammo_rays.remove(ray)

        # Hit dots op exacte raakpositie voor enemies (los van ammo ray timer)
        for enemy in list(self.objects.get("enemies", [])):
            if enemy.hit_timer > 0 and enemy.last_hit_world is not None:
                dx = enemy.last_hit_world.x - player_pos.x
                dy = enemy.last_hit_world.y - player_pos.y
                d = hypot(dx, dy)
                if d > 1:
                    rel_angle = atan2(dy, dx) - player_angle
                    while rel_angle > pi: rel_angle -= 2 * pi
                    while rel_angle < -pi: rel_angle += 2 * pi
                    if abs(rel_angle) <= pi / 4 and d <= MAX_DEPTH:
                        hit_sx = cfg.WIDTH / 2 + tan(rel_angle) * PROJ_DIST
                        ray_num = int((hit_sx / cfg.WIDTH) * cfg.NUM_RAYS)
                        if 0 <= ray_num < cfg.NUM_RAYS and d < wall_distances[ray_num]:
                            pygame.draw.circle(cfg.SCREEN, (255, 200, 100),
                                               (int(hit_sx), int(cfg.HEIGHT / 2)), 4)

        # 5. Wapen laatst
        self.current_gun.draw()

    def _get_all_texture_paths(self):
        paths = []
        for t in ["normal_enemy", "fast_enemy", "tank_enemy", "final_boss", "projectile"]:
            paths.append(resolve_asset(theme.get(f"textures.enemies.{t}", f"textures/enemies/{t}.png")))
        for t in ["ammo", "health", "keycard", "exit"]:
            paths.append(resolve_asset(theme.get(f"textures.objects.{t}", f"textures/objects/{t}.png")))
        weapon_size = theme.get("sizes.weapon.texture", (300, 300))
        for gun in ["pistol", "rifle", "minigun"]:
            for part in ["GUN", "GUN_recoil", "GUN_muzzle"]:
                path = resolve_asset(theme.get(f"textures.weapons.{gun}.{part}", f"textures/weapons/{gun}/{part}.png"))
                paths.append((path, weapon_size))
        return paths

    def reset_game(self):
        self.multiplayer = False
        self.player_id = 0
        self.remote_players = []
        self._remote_tracks = {}
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
        self.map = M.MAP
        self.player = Player(M.SPAWNS["player"][0], M.SPAWNS["player"][1], angle=START_ANGLES[M.map_level])
        pygame.mouse.set_pos(cfg.WIDTH // 2, cfg.HEIGHT // 2)
        pygame.mouse.get_rel()
        self.global_health = START_HEALTH
        self.global_ammo = START_AMMO
        M.start_angle = START_ANGLES[M.map_level]
        self.objects = self.create_objects()
        self.projectiles = []
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_locked = False
        self.elevator_transition = False
        self.elevator_wait_timer = 0
        self.player_near_exit = False
        self.elevator_pending = [0, 0]
        self.exit_pos = None
        self._pos_seq = 0
        self._pending_removes.clear()
        self.final_boss_spotted = False
        self.escaped = False
        self.player.door_pos = 0

        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)

        self._play_music()

    def level_up(self):
        if M.map_level >= MAX_LEVEL:
            return
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
        self.map = M.MAP
        self.player.pos = Vector(M.SPAWNS["player"][0], M.SPAWNS["player"][1])
        self.player.got_keycard = False
        self.player.angle = START_ANGLES[M.map_level]
        pygame.mouse.set_pos(cfg.WIDTH // 2, cfg.HEIGHT // 2)
        pygame.mouse.get_rel()
        self.objects = self.create_objects()
        self.projectiles = []
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_locked = False
        self.elevator_transition = False
        self.elevator_wait_timer = 0
        self.player_near_exit = False
        self.elevator_pending = [0, 0]
        self.exit_pos = None

    #  Multiplayer methods 

    def _toggle_ready(self):
        if self.network_client:
            self.network_client.send({"type": "ready"})

    def _set_lobby_option(self, key, value):
        if self.network_client and self.is_host:
            self.network_client.send({"type": "set_lobby_option", "option_key": key, "option_value": value})

    def _join_active_game(self):
        if self.network_client:
            self.network_client.send({"type": "join_game"})

    def _start_multiplayer_client(self, level=0):
        M.map_level = level
        M.MAP, M.SPAWNS, M.width, M.height = png_to_list_fast(MAP_PATH[level])
        M.start_angle = START_ANGLES[M.map_level]
        # Hier laadt de client zelf een level. Onze eigen teller moet mee,
        # anders denkt apply_state dat level 0 nog nooit geladen is.
        self._client_loaded_level = level
        self.player = Player(M.SPAWNS["player"][0], M.SPAWNS["player"][1], angle=START_ANGLES[level])
        preload_textures(self._get_all_texture_paths())
        pygame.mouse.set_pos(cfg.WIDTH // 2, cfg.HEIGHT // 2)
        pygame.mouse.get_rel()
        self.global_health = START_HEALTH
        self.global_ammo = START_AMMO
        self.player.door_pos = 0
        self.player.got_keycard = False
        self.current_gun = self.pistol
        self.unlocked_guns = [self.pistol]
        if level >= 1:
            self.unlocked_guns.append(self.minigun)
        if level >= 3:
            self.unlocked_guns.append(self.rifle)
        self.remote_players = []
        self._remote_tracks = {}
        self.final_boss = None
        self.final_boss_spotted = False
        self.host_pid = -1
        self.is_host = False
        self.escaped = False
        self.elevator_waiting = False
        self.elevator_ready = False
        self.elevator_locked = False
        self.elevator_transition = False
        self.elevator_wait_timer = 0
        self.elevator_pending = [0, 0]
        self.player_near_exit = False
        self.exit_pos = None
        self._pos_seq = 0
        self._health_delta = 0
        self._ammo_delta = 0
        self._enemy_damage = []
        self._remove_pickup = []
        self._pending_removes.clear()
        # All objects come from server sync — start empty
        self.objects = {"enemies": [], "ammo": [], "keycard": [], "exit": None, "health": []}
        self.projectiles = []
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        self._play_music()
        self.state = "game"

    def _do_connect(self, ip, port, name):
        """Verbind met een server. Geeft terug of het gelukte.

        De returnwaarde is niet cosmetisch: _do_host gebruikt hem om te
        beslissen of hij zijn eigen server mag houden. Zonder return zou
        `not self._do_connect(...)` altijd waar zijn en zou de host zijn
        verse server meteen weer afsluiten.
        """
        self.skin_id = self.Menu.mp_skin_id
        self.network_client = NetworkClient()
        if self.network_client.connect(ip, port, name, self.skin_id):
            self.multiplayer = True
            self.player_id = self.network_client.player_id
            self.player_name = name
            self._last_server_packet = time.time()
            self.state = "waiting_lobby"
            return True
        self.Menu.mp_status = "Verbinding mislukt!"
        if self.network_client:
            self.network_client.disconnect()
            self.network_client = None
        return False

    def _do_host(self, port, name):
        """Start een eigen server en verbind er meteen mee.

        Zo hoeft een host geen tweede venster en geen Python-kennis te hebben:
        de server draait als een achtergronddraadje in hetzelfde proces en
        sluit weer mee zodra de host uit de lobby vertrekt.
        """
        self._stop_host()
        try:
            server = ServerIO(port, max_players=MAX_PLAYERS)
        except OSError as e:
            self.Menu.mp_status = f"Server starten mislukt: {e.strerror or e}"
            return
        server.start()
        self.hosted_server = server

        # Meld jezelf op het eigen netwerk, zodat anderen je vinden zonder
        # dat ze je IP hoeven te weten.
        self.discovery_responder = DiscoveryResponder(
            port, get_info=self._discovery_info)
        self.discovery_responder.start()

        if not self._do_connect("127.0.0.1", port, name):
            self._stop_host()
            return

        # Het zoeken naar je publieke adres duurt enkele seconden en mag het
        # spel niet tegenhouden, dus draait het in een eigen draadje.
        self.hosted_address = None
        threading.Thread(target=self._discover_host_address,
                         args=(port,), daemon=True).start()

    def _discovery_info(self):
        """Wat de aankondiging op het LAN over deze server moet vertellen."""
        server = getattr(self, "hosted_server", None)
        if server is None:
            return {"is_host": False}
        try:
            players = len(server.get_lobby_players())
            maximum = server.max_players
        except Exception:
            players, maximum = 0, MAX_PLAYERS
        return {"players": players, "max_players": maximum, "is_host": True}

    def _discover_host_address(self, port):
        """Zoek uit hoe de gasten je kunnen bereiken (LAN + internet)."""
        try:
            info = discover(port)
            # Een mapping die de router na een uur laat vervallen zou de
            # server stilletjes onbereikbaar maken, dus die houden we vast.
            if info.get("mapped"):
                gw = find_gateway()
                if gw:
                    self.mapping_keeper = PortMappingKeeper(gw, port)
                    self.mapping_keeper.start()
            self.hosted_address = info
            self.hosted_port = info.get("external_port", port)
        except Exception:
            # Adres zoeken mag nooit de server om zeep helpen: een
            # campusnetwerk zonder router geeft een fout, en dan is het
            # LAN-adres alsnog het enige dat telt.
            pass

    def _stop_host(self):
        """Sluit de eigen server af en geef de poort weer vrij."""
        server = getattr(self, "hosted_server", None)
        if server is None:
            return
        responder = getattr(self, "discovery_responder", None)
        if responder:
            responder.stop()
            self.discovery_responder = None
        keeper = getattr(self, "mapping_keeper", None)
        if keeper:
            keeper.stop()
            keeper.release()
            self.mapping_keeper = None
        try:
            server.stop()
        except Exception:
            pass
        self.hosted_server = None
        self.hosted_address = None

    # ── spectaten ────────────────────────────────────────────────

    def spectate_candidates(self):
        """Wie er nog over is om naar te kijken.

        Alleen in multiplayer: in je eentje is er niemand om mee te leven.
        Dode spelers vallen eruit, want je kijkt naar iemand die nog vecht.
        """
        if not self.multiplayer or not self.network_client:
            return []
        out = []
        for pid, info in getattr(self, "_spectate_info", {}).items():
            if pid == self.player_id:
                continue
            if info.get("state") == "dead":
                continue
            out.append((pid, info.get("name", f"Player {pid}")))
        out.sort()
        return out

    def can_spectate(self):
        return bool(self.spectate_candidates())

    def _start_spectating(self):
        candidates = self.spectate_candidates()
        if not candidates:
            self.Menu.mp_status = "Iedereen is dood, er valt niets te kijken"
            return
        self.spectating = True
        self._spectate_pid, self._spectate_name = candidates[0]
        self.state = "spectating"
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)

    def _stop_spectating(self, next_state="dead"):
        if not self.spectating:
            return
        self.spectating = False
        self._spectate_pid = None
        self._spectate_name = ""
        self.state = next_state

    def _cycle_spectate_target(self, step=1):
        candidates = self.spectate_candidates()
        if not candidates:
            return
        pids = [pid for pid, _ in candidates]
        if self._spectate_pid not in pids:
            self._spectate_pid, self._spectate_name = candidates[0]
            return
        index = (pids.index(self._spectate_pid) + step) % len(pids)
        self._spectate_pid, self._spectate_name = candidates[index]

    def _update_spectating(self):
        """Zet de camera op de speler die we volgen.

        De camera gebruikt overal self.player, dus door die op de gekozen
        teamgenoot te zetten werkt de hele raycaster meteen mee en hoeft er
        geen tweede camerakpad te komen.
        """
        if not self.spectating:
            return
        candidates = self.spectate_candidates()
        if not candidates:
            # Iedereen is dood of weggegaan: terug naar het game-overscherm.
            self._stop_spectating()
            return
        if self._spectate_pid not in [pid for pid, _ in candidates]:
            self._spectate_pid, self._spectate_name = candidates[0]
        track = self._remote_tracks.get(self._spectate_pid)
        if track is not None:
            self.player.pos = track["sprite"].pos
        info = getattr(self, "_spectate_info", {}).get(self._spectate_pid, {})
        self.player.angle = info.get("angle", self.player.angle)

    def _disconnect(self, next_state="menu"):
        if self.network_client:
            for _ in range(3):
                self.network_client.send({"type": "disconnect"})
            time.sleep(0.05)
            self.network_client.disconnect()
            self.network_client = None
        self._stop_host()
        self.multiplayer = False
        self.player_id = 0
        self.remote_players = []
        self._remote_tracks = {}
        self._pending_removes.clear()
        self._stop_spectating()
        self.state = next_state
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)

    def _create_enemy_from_type(self, type_str, pos):
        mapping = {
            "enemies/normal_enemy": NormalEnemy,
            "enemies/fast_enemy": FastEnemy,
            "enemies/tank_enemy": TankEnemy,
            "enemies/final_boss": FinalBoss,
        }
        cls = mapping.get(type_str, NormalEnemy)
        return cls(pos[0], pos[1])

    def _send_client_state(self):
        """Send deltas to the server. Rate-limited to every 2 frames."""
        if self.state == "dead":
            self.network_client.send_input({"state": "dead"})
            return
        if self.state not in ("game", "paused"):
            return
        self._pos_seq += 1
        if self._pos_seq % 2 != 0:
            return
        packet = {
            "seq": self._pos_seq,
            "pos": (self.player.pos.x, self.player.pos.y),
            # De server negeert de positie als dit nummer niet klopt met wat
            # hij zegt. Zo kan een pakket dat onderweg was toen de lift
            # vertrok niet de nieuwe spawn wegschrijven. Zie process_input.
            "level": M.map_level,
            "health_delta": self._health_delta,
            "ammo_delta": self._ammo_delta,
            "enemy_damage": self._enemy_damage,
            "remove_pickup": self._remove_pickup,
            "got_keycard": self.player.got_keycard,
            "door_closed": self.player.door_pos > cfg.WIDTH // 2,
            "elevator_waiting": self.elevator_waiting,
            "state": self.state,
        }
        self._health_delta = 0
        self._ammo_delta = 0
        self._enemy_damage = []
        self._remove_pickup = []
        self.network_client.send_input(packet)

    def update_remote_positions(self):
        """Render de andere spelers één snapshot achter.

        De server stuurt posities 30 keer per seconde terwijl het scherm 60 keer
        per seconde tekent. Zonder interpolatie maakt elke teamgenoot dus 30
        sprongen per seconde. Eén snapshot achter renderen en de tussenliggende
        posities uitvullen geeft vloeiende beweging, en omdat de speler
        client-authoritative is levert het geen extra vertraging op.
        """
        if not self._remote_tracks:
            return
        target = time.perf_counter() - REMOTE_INTERP_DELAY
        for track in self._remote_tracks.values():
            sprite = track["sprite"]
            samples = track["samples"]
            if not samples:
                continue
            if len(samples) == 1 or target <= samples[0][0] or target >= samples[-1][0]:
                _, x, y = samples[0] if target <= samples[0][0] else samples[-1]
                sprite.pos = Vector(x, y)
                continue
            pos = Vector(samples[-1][1], samples[-1][2])
            for i in range(len(samples) - 1):
                t0, x0, y0 = samples[i]
                t1, x1, y1 = samples[i + 1]
                if t0 <= target <= t1:
                    span = t1 - t0
                    frac = 0.0 if span <= 0 else (target - t0) / span
                    pos = Vector(x0 + (x1 - x0) * frac, y0 + (y1 - y0) * frac)
                    break
            sprite.pos = pos

    def apply_state(self, state):
        if not state:
            return

        # 0. Lobby options (from server state during game)
        opts = state.get("lobby_options")
        if opts:
            self.lobby_options = opts

        # 1. Overwrite shared resources from server (absolute values)
        players_data = state.get("players", [])
        if self.lobby_options.get("shared_health", True):
            self.global_health = state.get("global_health", self.global_health)
        else:
            for pdata in players_data:
                if pdata.get("id") == self.player_id:
                    self.global_health = pdata.get("health", self.global_health)
                    break
        if self.lobby_options.get("shared_ammo", True):
            self.global_ammo = state.get("global_ammo", self.global_ammo)
        else:
            for pdata in players_data:
                if pdata.get("id") == self.player_id:
                    self.global_ammo = pdata.get("ammo", self.global_ammo)
                    break
        self.keycard_acquired = state.get("keycard_acquired", False)
        self.player.got_keycard = state.get("keycard_acquired", self.player.got_keycard)

        # 2. Players — sync own state flags from server (not pos/angle — client-authoritative movement)
        for pdata in players_data:
            if pdata.get("id") == self.player_id:
                self.player.score = pdata.get("score", self.player.score)
                if state.get("elevator_transition") and self.player.door_pos == 0:
                    self.player.door_pos = 1
        other_players = [p for p in players_data if p.get("id") != self.player_id]
        seen_pids = set()
        self._spectate_info = {}
        for pdata in players_data:
            pid = pdata["id"]
            # Toestand en kijkrichting per speler bewaren: nodig zodra je
            # zelf dood bent en meeleeft met wie er over zijn.
            self._spectate_info[pid] = {
                "name": pdata.get("name", f"Player {pid}"),
                "state": pdata.get("state", "game"),
                "angle": pdata.get("angle", 0.0),
            }
        for pdata in other_players:
            pid = pdata["id"]
            seen_pids.add(pid)
            track = self._remote_tracks.get(pid)
            if track is None:
                track = {"sprite": PlayerSprite(""), "samples": []}
                self._remote_tracks[pid] = track
            sprite = track["sprite"]
            samples = track["samples"]
            samples.append((time.perf_counter(), pdata["pos"][0], pdata["pos"][1]))
            if len(samples) > REMOTE_MAX_SAMPLES:
                del samples[:-REMOTE_MAX_SAMPLES]
            sprite.name = pdata.get("name", f"Player {pid}")
            skin_id = pdata.get("skin_id", 0)
            if hasattr(sprite, 'set_skin'):
                sprite.set_skin(skin_id)
        for stale_pid in [p for p in self._remote_tracks if p not in seen_pids]:
            del self._remote_tracks[stale_pid]
        self.remote_players = [self._remote_tracks[p["id"]]["sprite"]
                               for p in other_players]

        # 3. Enemies — full sync from server (ALL clients)
        enemies_data = state.get("enemies", [])
        while len(self.objects["enemies"]) < len(enemies_data):
            edata = enemies_data[len(self.objects["enemies"])]
            self.objects["enemies"].append(self._create_enemy_from_type(edata["type"], edata["pos"]))
        while len(self.objects["enemies"]) > len(enemies_data):
            self.objects["enemies"].pop()
        self.final_boss = None
        for i, edata in enumerate(enemies_data):
            new_type = edata.get("type", "")
            if self.objects["enemies"][i].type != new_type:
                self.objects["enemies"][i] = self._create_enemy_from_type(new_type, edata["pos"])
            self.objects["enemies"][i].pos = Vector(edata["pos"][0], edata["pos"][1])
            self.objects["enemies"][i].health = edata.get("health", 10)
            if new_type == "enemies/final_boss":
                self.final_boss = self.objects["enemies"][i]

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
        # Een levelnummer buiten de kaarten zou MAP_PATH[index] laten
        # klappen. Negeren is beter dan een IndexError in het midden van het
        # spel: de speler blijft gewoon op de kaart die hij al had.
        if not (0 <= new_level < len(MAP_PATH)):
            new_level = M.map_level
        if new_level != M.map_level:
            if self.boss_music_playing:
                self.boss_music_playing = False
                if self.boss_music:
                    self.boss_music.stop()
            M.map_level = new_level
            M.MAP, M.SPAWNS, M.width, M.height = png_to_list_fast(MAP_PATH[new_level])
            self.map = M.MAP
            M.start_angle = START_ANGLES[new_level]
            # NIET hier de speler neerzetten. De hele levelovergang komt in
            # een eigen blok hieronder, dat niet op M.map_level steunt.
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
            self.elevator_pending = [0, 0]
            self.player_near_exit = False
            self.player.got_keycard = False
            self.keycard_acquired = False
            self.projectiles = []
            self.exit_pos = None

        # Het overzetten op de nieuwe level, los van de vergelijking hierboven.
        #
        # Waarom los: bij zelfhosten draait de server in een draadje in het
        #zelfde proces en deelt hij de module-singleton M. De server zet
        # M.map_level alvast in _setup_level, dus als je de teleport aan
        # `new_level != M.map_level` hing, oversloeg hij die bij een host
        # terwijl hij bij een externe client wel ging. Resultaat: de host
        # bleef op zijn oude positie, wat op de nieuwe kaart in een muur
        # kan staan. Daarom lezen we het levelnummer uit het pakket zelf en
        # vergelijken we dat met wat wij het laatst daadwerkelijk geladen
        # hebben. Dat kan de server niet vooruitlopen.
        for pdata in players_data:
            if pdata.get("id") != self.player_id:
                continue
            if new_level == self._client_loaded_level:
                break
            self._client_loaded_level = new_level
            self.player.pos = Vector(pdata["pos"][0], pdata["pos"][1])
            self.player.angle = pdata.get("angle", M.start_angle)
            pygame.mouse.get_rel()
            break
        self.state = state.get("state", self.state)
        self.escaped = state.get("escaped", self.escaped)
        self.elevator_waiting = state.get("elevator_waiting", self.elevator_waiting)
        self.elevator_ready = state.get("elevator_ready", self.elevator_ready)
        self.elevator_transition = state.get("elevator_transition", False)
        self.elevator_wait_timer = state.get("elevator_wait_timer", self.elevator_wait_timer)
        pending = state.get("elevator_pending")
        if pending:
            self.elevator_pending = list(pending)

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
        # Alle klaarstaande packets lezen, maar per frame alleen het nieuwste
        # state-pakket toepassen: oudere states overschrijven anders de actuele.
        newest_state = None
        for packet in self.network_client.drain():
            ptype = packet.get("type")
            if ptype == "state":
                newest_state = packet
            elif ptype == "game_start":
                self._start_multiplayer_client(packet.get("level", 0))
                newest_state = None
            elif ptype in ("server_stopped", "disconnect", "server_full"):
                self._disconnect(next_state="multiplayer_menu")
                return
            elif ptype == "skin_manifest_update":
                SkinManager.set_manifest(packet.get("skin_manifest", []))
                SkinManager.start_background_download()
        if newest_state is not None:
            self.apply_state(newest_state)
        if self.global_health <= 0 and self.state in ("game", "paused"):
            self.global_health = 0
            pygame.mouse.set_visible(True)
            self.state = "dead"

    #  Main loop 

    def run(self):
        set_resolution("high")
        self.running = True
        self.state = "menu"
        while self.running:
            events = self.handle_events()
            self.handle_input()
            if self.state == "menu":
                self.Menu.draw_main_menu(events, self)

            elif self.state == "multiplayer_menu":
                self.Menu.draw_multiplayer_menu(events, self)

            elif self.state == "waiting_lobby":
                if self.network_client:
                    for packet in self.network_client.drain():
                        self._last_server_packet = time.time()
                        ptype = packet.get("type")
                        if ptype == "lobby_info":
                            players_raw = packet.get("players", [])
                            self.Menu.client_list = players_raw
                            self.Menu.lobby_game_active = packet.get("game_active", False)
                            cd = packet.get("countdown", 0)
                            if cd != self.Menu.lobby_countdown:
                                self.Menu.lobby_countdown = cd
                                self.Menu._cd_ticks = pygame.time.get_ticks()
                            new_host = packet.get("host_pid", -1)
                            if new_host != self.host_pid:
                                self.host_pid = new_host
                                self.is_host = (self.host_pid == self.player_id)
                                self.Menu.host_pid = new_host
                            opts = packet.get("lobby_options")
                            if opts:
                                self.lobby_options = opts
                                self.Menu.lobby_options = dict(opts)

                        elif ptype == "pong":
                            pass
                        elif ptype == "game_start":
                            self._start_multiplayer_client(packet.get("level", 0))
                        elif ptype == "server_stopped":
                            self._disconnect()
                        elif ptype == "server_full":
                            cap = packet.get("max_players", "?")
                            self.Menu.mp_status = f"Server vol ({cap}/{cap})"
                            self._disconnect(next_state="multiplayer_menu")
                            return
                        elif ptype == "skin_manifest_update":
                            SkinManager.set_manifest(packet.get("skin_manifest", []))
                            SkinManager.start_background_download()
                    now = time.time()
                    if now - self._last_server_packet > 30:
                        self.Menu.mp_status = "Server verbinding verloren"
                        self._disconnect(next_state="multiplayer_menu")
                    elif now - self._last_lobby_ping > 2.0:
                        self.network_client.send({"type": "ping"})
                        self._last_lobby_ping = now
                for ev in events:
                    if ev.type == pygame.KEYDOWN and ev.key == pygame.K_r:
                        self._toggle_ready()
                self.Menu.draw_waiting_lobby(events, self)

            elif self.state == "game":
                self.clock.tick(60)
                if self.multiplayer:
                    self.handle_network()

                if not self.escaped:
                    self.update()
                    if self.multiplayer:
                        self.update_remote_positions()
                    self.render()
                    self.Menu.draw_minimap(self)
                    if self.final_boss is not None and self.final_boss_spotted:
                        self.final_boss.draw_health_bar(None, None, None)
                    if self.bilal.flags["general"]:
                        self.bilal.update()
                        self.bilal.draw()
                self.Menu.draw_UI(events)
                
                if self.player.got_keycard:
                    self.keycard_font = load_font(20, bold=True)
                    kc_surf = self.keycard_font.render("KEYCARD ACQUIRED", True, 'green')
                    cfg.SCREEN.blit(kc_surf, (cfg.WIDTH - kc_surf.get_width() - int(cfg.WIDTH * 0.04), cfg.HEIGHT - int(cfg.HEIGHT * 0.06)))
                    
                if self.escaped:
                    self.Menu.draw_escaped_screen(events, self)
                
                if self.player.door_pos != 0:
                    self.Menu.game = self
                    self.Menu.draw_elevator(events, self.player)

            elif self.state == "spectating":
                self.clock.tick(60)
                self.Menu.game = self
                self.handle_network()
                self.update_remote_positions()
                self._update_spectating()
                if self.spectating:
                    # De wereld loopt gewoon door, alleen zonder jouw muis
                    # en wapens: update() zou de camera wegjagen.
                    self.render()
                    self.Menu.draw_minimap(self)
                    self.Menu.draw_UI(events)
                else:
                    # Iedereen is dood of weggegaan: terug naar de doodsscherm.
                    self.Menu.draw_dead_screen(events, self)

            elif self.state == "paused":
                self.handle_network()
                if self._paused_frame:
                    cfg.SCREEN.blit(self._paused_frame, (0, 0))
                self.Menu.draw_paused_screen(events, self)
            elif self.state == 'dead':
                self.Menu.draw_dead_screen(events, self)
            elif self.state == "credits":
                self.Menu.draw_credits(events, self)
            elif self.state == 'settings':
               self.Menu.draw_settings(events, self)
            elif self.state == 'pack_select':
               self.Menu.draw_pack_select(events, self)

            self._maybe_start_main_loop()

            if self.player.death and self.state == "game":
                pygame.mouse.set_visible(True)
                self.state = "dead"
            if self.state == "game":
                self._paused_frame = cfg.SCREEN.copy()
            pygame.display.flip()

        pygame.quit()


if __name__ == "__main__":
    game = Game()
    game.run()
