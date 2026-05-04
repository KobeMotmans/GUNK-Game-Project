"""
game.py - Hoofd game loop en initialisatie
"""

import pygame
import random

from config import (SCREEN, WIDTH, HEIGHT, START_AMMO, AMMO_CAP, DAMAGE_FLASH, AMMO_FLASH, KEYCARD_FLASH,
                    SCREEN_DEAD, START_HEALTH, ELEV_SPEED, MAX_LEVEL, MAP_PATH, START_ANGLES, HEALTH_FLASH, HEALTH_CHANCE, 
                    set_resolution, FONT, VICTORY_SCREEN, MENU_BG, ELEV_TIME)
from raycaster import dda
from weapons import Pistol, Minigun, Rifle
from enemies import Andrei, Ahmed, Ruben, Jan
from player import Player
from Menu import Menu, Button, Slider, Bilal
from map_loader import M, png_to_list_fast
from objects import PickupObject
from vector import Vector


class Game:
    def __init__(self):
        pygame.init()
        pygame.mixer.init()
        self.main_music = pygame.mixer.Sound("assets/Soundtrack.mp3")
        self.clock = pygame.time.Clock()
        self.running = False
        self.state = None
        self.escaped = False

        #Init Bilal/Tutorial
        self.Menu = Menu((70,70,70), self)
        self.bilal = Bilal()
        self.bilal.say("Welkom bij GUNK!", 100)
        self.bilal.say("Gebruik je muis om rond te kijken en ZQSD om te bewegen", 200)
        self.bilal.say("Je zit vast op verdieping 5 van het K gebouw. Probeer via de lift te ontsnappen.", 250)
        self.bilal.say("Er moet in één van deze kamers een keycard liggen. Zoek hem!", 200)
        self.bilal.say("Maar pas op, want de andere assistenten zijn gek geworden van het K gebouw!", 200)

        # Init speler
        self.player = Player(M.SPAWNS["player"][0], M.SPAWNS["player"][1])


        # Init wapens
        self.pistol = Pistol()
        self.minigun = Minigun()
        self.rifle = Rifle()
        self.current_gun = self.pistol
        self.unlocked_guns = [self.pistol]

        self.state = "menu"
        self.curr_flash = ""
        self.flash_time = 0
        self.possible_enemies = [Andrei, Ahmed, Ruben]
        self.jan = None  # referentie naar Jan voor de boss bar
        self.jan_spotted = False

        # Init objects
        self.resolution = "high"
        self.main_music.set_volume(0.5)  # match initial slider value

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
                        if not self.current_gun.auto: #Click to shoot guns
                            if self.player.ammo >= self.current_gun.ammo_weight:
                                self.current_gun.shoot(self.player.pos,self.player.angle,self.objects["enemies"],self.player,self.current_gun)

            elif self.state == "paused":
                 if event.type == pygame.KEYDOWN: #unpause
                     if event.key == pygame.K_ESCAPE:
                         pygame.mouse.set_visible(False)
                         pygame.event.set_grab(True)
                         self.state = "game"
                         pygame.mixer.unpause()

        if self.state == "game":
            mouse_buttons = pygame.mouse.get_pressed()
            if self.current_gun.auto: #Pressed to shoot
                if mouse_buttons[0] and self.current_gun.weapon_state == 0:
                    if self.player.ammo >= self.current_gun.ammo_weight:
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

    def update(self):   #Update game state
        self.current_gun.update()
        self.player.tick()

    def render(self):   #Render alle game elementen
        SCREEN.fill('black')


        player_pos = self.player.get_pos()
        player_angle = self.player.get_angle()

        # 1. Raycasting - muren direct tekenen, afstanden opslaan
        wall_distances = dda(player_pos, player_angle)

        # 2. Verzamel zichtbare sprites
        sprites = []  # (dist, SCREEN_x, enemy)
        for obj in self.objects.keys():
            if obj == "enemies":
                for enemy in self.objects[obj]:
                    enemy.find_path(self.player)
                    dist, SCREEN_x, angle, _ = enemy.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, enemy))
                        self.bilal.trigger("seen_enemy")
                        if enemy.type == "enemies/jan":
                            self.jan_spotted = True
                            self.bilal.trigger("boss_warning")
                    if enemy.health <= 0:
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
                        item.interact(self.player)
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
                        item.interact(self.player)
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
                        item.interact(self.player)
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
                        interaction = item.interact(self.player)
                        if interaction == "succes":
                            self.objects[obj] = None
                            if obj != 'exit':
                                self.curr_flash = "keycard"
                                self.flash_time = 60

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
        # Init speler
        M.map_level = 0
        # Init objects
        self.state = "game"
        self.current_gun = self.pistol
        self.unlocked_guns = [self.pistol]
        self.player.score = 0
        M.MAP, M.SPAWNS, M.width, M.height  = png_to_list_fast(MAP_PATH[M.map_level])
        self.player = Player(M.SPAWNS["player"][0], M.SPAWNS["player"][1])
        M.start_angle = START_ANGLES[M.map_level]
        self.player.ammo = START_AMMO
        self.objects = self.create_objects()
        self.main_music.play()
        self.player.door_pos = 0
        
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
        pygame.mixer.Sound("assets/elev_ding.mp3").play()
        

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
                self.Menu.draw_main_menu(events)

            elif self.state == "game":
                self.clock.tick(60)
                if (self.player.door_pos == 0 or self.player.door_pos >= WIDTH/2 + ELEV_SPEED) and not self.escaped:
                    self.update()
                    self.render()
                    if self.jan is not None and self.jan_spotted:
                        self.jan.draw_health_bar(None, None, None)
                        
                self.Menu.draw_UI(events)
                
                if self.bilal.flags["general"]:
                    self.bilal.update()
                    self.bilal.draw()
                if self.player.got_keycard:
                    SCREEN.blit(pygame.font.SysFont(FONT, 20, True).render("KEYCARD ACQUIRED", True, 'green'),(WIDTH-210, HEIGHT-60))
                    
                if self.escaped:
                    self.Menu.draw_escaped_screen(events)
                
                if self.player.door_pos != 0:
                    self.Menu.draw_elevator(events, self.player)

            elif self.state == "paused":
                self.Menu.draw_paused_screen(events)
            elif self.state == 'dead':
                self.Menu.draw_dead_screen(events)
            elif self.state == "credits":
                self.Menu.draw_credits(events)
            elif self.state == 'settings':
               self.Menu.draw_settings(events)

            if self.player.death and self.state == "game":
                pygame.mouse.set_visible(True)
                self.state = "dead"
            pygame.display.flip()

        pygame.quit()


if __name__ == "__main__":
    game = Game()
    game.run()