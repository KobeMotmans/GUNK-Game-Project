"""
game.py - Hoofd game loop en initialisatie
"""

import pygame
from math import pi
import random

from config import SCREEN, WIDTH, HEIGHT, MAX_DEPTH, START_AMMO, AMMO_CAP, DAMAGE_FLASH, MIN_DIST, AMMO_FLASH, KEYCARD_FLASH, SCREEN_DEAD, START_HEALTH, ELEV_SPEED, MAX_LEVEL, MAP_PATH, START_ANGLES, HEALTH_FLASH
from raycaster import dda
from weapons import Pistol, Minigun, Rifle
from enemies import Andrei, Ahmed, Ruben
from player import Player
from Menu import Button
from map_loader import M, png_to_list_fast
from objects import PickupObject
from vector import Vector


class Game:
    def __init__(self):
        pygame.init()
        pygame.mixer.init()
        self.music = True
        self.main_music = pygame.mixer.Sound("assets/Soundtrack.mp3")
        self.clock = pygame.time.Clock()
        self.running = False
        self.state = None
        self.escaped = False

        # Init speler
        self.player = Player(M.SPAWNS["player"][0], M.SPAWNS["player"][1])


        # Init wapens
        self.pistol = Pistol()
        self.minigun = Minigun()
        self.rifle = Rifle()
        self.current_gun = self.pistol
        self.unlocked_guns = [self.pistol, self.minigun, self.rifle]
        
        self.state = "menu"
        self.curr_flash = ""
        self.flash_time = 0
        self.door_pos = 0
        self.possible_enemies = [Andrei, Ahmed, Ruben]

        # Init objects
        self.objects = self.create_objects()

        

    def create_enemies(self):
        """Maak een lijst van test vijanden"""
        enemies = []
        for enemy_pos in M.SPAWNS["enemies"]:
            randomnumber = random.randint(0,2)
            random_enemy =  self.possible_enemies[randomnumber]
            enemies.append(random_enemy(enemy_pos[0], enemy_pos[1]))
        return enemies

    def create_objects(self):
        objects = {
            "enemies": self.create_enemies(),
            "ammo": [],
            "keycard": PickupObject("objects/keycard", M.SPAWNS["keycard"][0], M.SPAWNS["keycard"][1]),
            "exit": PickupObject("objects/exit", M.SPAWNS["end_point"][0], M.SPAWNS["end_point"][1]),
            "health": []
        }
        for ammo_pos in M.SPAWNS["ammo"]:
            objects["ammo"].append(PickupObject("objects/ammo", ammo_pos[0], ammo_pos[1]))
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
                
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        if self.current_gun.auto == False: #Click to shoot guns
                            if self.player.ammo >= self.current_gun.ammo_weight:
                                self.current_gun.shoot(self.player.pos,self.player.angle,self.objects["enemies"],self.player,self.current_gun)
    
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

        if self.state == "game":
            if keys[pygame.K_ESCAPE]:
                pygame.mouse.set_visible(True)
                pygame.event.set_grab(False)
                self.state = "paused"
                pygame.mixer.pause()

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
                    #print(enemy.is_player_los(player_pos))
                    dist, SCREEN_x, angle, _ = enemy.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, enemy))
                    if enemy.health <= 0:
                        self.player.score += 1
                        self.objects["enemies"].remove(enemy)
                        if random.random() < 1:
                            self.objects["health"].append(PickupObject("objects/health", enemy.pos.x, enemy.pos.y))
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
            else:
                item = self.objects[obj]
                if item is not None:
                    dist, SCREEN_x, angle, is_hit = item.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, item))
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
        M.MAP, M.SPAWNS = png_to_list_fast(MAP_PATH[M.map_level])
        self.player = Player(M.SPAWNS["player"][0], M.SPAWNS["player"][1])
        # Init wapens
        self.pistol = Pistol()
        self.minigun = Minigun()
        self.rifle = Rifle()
        self.current_gun = self.pistol
        self.unlocked_guns = [self.pistol, self.minigun, self.rifle]
        # Init objects
        self.objects = self.create_objects()
        self.state = "game"
        self.player.score = 0
        self.player.level = 0
        M.map_level = 0
        M.MAP, M.SPAWNS = png_to_list_fast(MAP_PATH[M.map_level])
        M.start_angle = START_ANGLES[M.map_level]
        self.player.ammo = START_AMMO
        self.main_music.play() if self.music else None
        self.door_pos = 0
        
    def level_up(self):
        M.map_level += 1
        M.MAP, M.SPAWNS = png_to_list_fast(MAP_PATH[M.map_level])
        self.player.pos = Vector(M.SPAWNS["player"][0], M.SPAWNS["player"][1])
        self.player.got_keycard = False
        self.player.angle = START_ANGLES[M.map_level]
        self.objects = self.create_objects()

    def run(self):
        self.running = True
        self.state = "menu"
        while self.running:
            events = self.handle_events()
            self.handle_input()
            keys = pygame.key.get_pressed()
            if self.state == "menu":
                SCREEN.fill((70,70,70))
                
                SCREEN.blit(pygame.font.SysFont('ocraextended', 300, True).render("GUNK", True, 'white'),(WIDTH/2-360, HEIGHT/2-400))
                
                Start_knop = Button(0, 200, 100, "START", 45, "black", 'white', 'white', 'black', self, "reset", False)
                Start_knop.draw_button(events)

                Settings_button = Button(150, 200, 60, "OPTIONS", 30, "black", 'white', 'white', 'black', self, "settings", True)
                Settings_button.draw_button(events)

                Quit_button = Button(250, 140, 60, "QUIT", 40 ,"black", 'white', 'white', 'black', self, "Stop", False)
                Quit_button.draw_button(events)

            if self.state == "game":
                self.clock.tick(60)
                if (self.door_pos == 0 or self.door_pos > WIDTH/2) and not self.escaped:
                    self.update()
                    self.render()
                    
                SCREEN.blit(pygame.font.SysFont('ocraextended', 20, True).render(f"{round(self.clock.get_fps())}", True, 'green'),(20, 20))
                SCREEN.blit(pygame.font.SysFont('ocraextended', 80, True).render(f"{round(self.player.health)}/{START_HEALTH}", True, 'red'),(WIDTH-300, 20))
                SCREEN.blit(pygame.font.SysFont('ocraextended', 80, True).render(f"{round(self.player.ammo)}/{AMMO_CAP}", True, 'grey'),(20, HEIGHT-150))
                
                if self.player.got_keycard:
                    SCREEN.blit(pygame.font.SysFont('ocraextended', 20, True).render("KEYCARD ACQUIRED", True, 'green'),(WIDTH-210, HEIGHT-60))
                    
                if self.escaped:
                    SCREEN.fill((0,130,200))
                    SCREEN.blit(pygame.font.SysFont('ocraextended', 150, True).render("SUCCESFUL", True, 'white'),(WIDTH/2-370, HEIGHT/2-400))
                    SCREEN.blit(pygame.font.SysFont('ocraextended', 150, True).render("ESCAPE", True, 'white'),(WIDTH/2-280, HEIGHT/2-200))
                    SCREEN.blit(pygame.font.SysFont('ocraextended', 80, True).render(f"Score:{self.player.score}", True, 'black'),(WIDTH/2-160,HEIGHT/2-40))
                    Menu_button = Button(100, 140, 60, "MENU", 35, "black", 'white', 'white', 'black', self, "menu", True)
                    Menu_button.draw_button(events)
                
                if self.player.level%1 != 0:
                    if self.door_pos < WIDTH/2:
                        pygame.draw.rect(SCREEN,(20,20,20),[0,0,self.door_pos,HEIGHT])
                        pygame.draw.rect(SCREEN,(20,20,20),[WIDTH-self.door_pos,0,self.door_pos,HEIGHT])
                    elif self.door_pos <= WIDTH/2 + ELEV_SPEED:
                        SCREEN.fill((20,20,20))
                        if self.player.level < MAX_LEVEL:
                            self.level_up()
                        else:
                            pygame.mixer.stop()
                            self.escaped = True
                            pygame.mouse.set_visible(True)
                            pygame.event.set_grab(True)
                            
                    elif self.door_pos > WIDTH/2 and self.door_pos < WIDTH:
                        pygame.draw.rect(SCREEN,(20,20,20),[0,0,WIDTH-self.door_pos,HEIGHT])
                        pygame.draw.rect(SCREEN,(20,20,20),[self.door_pos,0,WIDTH-self.door_pos,HEIGHT])
                       
                    elif self.door_pos >= WIDTH:
                        self.player.level += 0.5
                        self.door_pos = -ELEV_SPEED
                    self.door_pos += ELEV_SPEED
                    

            if self.state == "paused":
                Restart_knop = Button(0, 200, 100, "Resume", 35, "black", 'white', 'white', 'black', self, "game", False)
                Restart_knop.draw_button(events)

                Menu_button = Button(100, 140, 60, "MENU", 35, "black", 'white', 'white', 'black', self, "menu", True)
                Menu_button.draw_button(events)

            if self.state == 'dead':
                pygame.mixer.stop()
                SCREEN.blit(SCREEN_DEAD, (0,0))
                Menu_button = Button(100, 140, 60, "MENU", 35, "black", 'white', 'white', 'black', self, "menu", True)
                Menu_button.draw_button(events)
                SCREEN.blit(pygame.font.SysFont('ocraextended', 80, True).render(f"Score:{self.player.score}", True, 'black'),(WIDTH/2-160,HEIGHT/2-40))

            if self.state == 'settings':
                SCREEN.fill((70,70,70))
                Menu_button = Button(200, 140, 60, "MENU", 35, "black", 'white', 'white', 'black', self, "menu", True)
                Menu_button.draw_button(events)
                
                Music_button = Button(100, 250, 60, "MUSIC" if self.music == False else "NO MUSIC", 35, "black", 'white', 'white', 'black', self, "settings", True, 0, "music")
                Music_button.draw_button(events)

                    
            if self.player.death and self.state == "game":
                pygame.mouse.set_visible(True)
                self.state = "dead"
            pygame.display.flip()

        if keys[pygame.K_DELETE]:
            self.running = False
            pygame.mixer.stop()
            self.state = None
            pygame.quit()
        pygame.quit()


if __name__ == "__main__":
    game = Game()
    game.run()