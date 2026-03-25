"""
game.py - Hoofd game loop en initialisatie
"""

import pygame
from math import pi

from config import SCREEN, WIDTH, HEIGHT, MAX_DEPTH, MAP_PATH, START_AMMO, AMMO_CAP
from raycaster import dda, draw_wall
from weapons import Pistol, Minigun, Rifle
from enemies import Andrei
from player import Player
from Menu import Button
from map_loader import SPAWNS
from objects import PickupObject


class Game:
    def __init__(self):
        pygame.init()
        pygame.mixer.init()
        self.main_music = pygame.mixer.Sound("assets/Soundtrack.mp3")
        self.clock = pygame.time.Clock()
        self.running = False
        self.state = None
        
        # Init speler
        self.player = Player(SPAWNS["player"][0], SPAWNS["player"][1])
        # Init wapens
        self.pistol = Pistol()
        self.minigun = Minigun()
        self.rifle = Rifle()
        self.current_gun = self.pistol
        self.unlocked_guns = [self.pistol, self.minigun, self.rifle]
        # Init objects
        self.objects = self.create_objects()
        self.state = "menu"

    def create_enemies(self):
        """Maak een lijst van test vijanden"""
        enemies = []
        for enemy_pos in SPAWNS["enemies"]:
            enemies.append(Andrei(enemy_pos[0], enemy_pos[1]))
        return enemies

    def create_objects(self):
        objects = {
            "enemies": self.create_enemies(),
            "ammo": [],
            "keycard": PickupObject("objects/keycard", SPAWNS["keycard"][0], SPAWNS["keycard"][1]),
            "exit": PickupObject("objects/exit", SPAWNS["end_point"][0], SPAWNS["end_point"][1])
        }
        for ammo_pos in SPAWNS["ammo"]:
            objects["ammo"].append(PickupObject("objects/ammo", ammo_pos[0], ammo_pos[1]))
        return objects



    def handle_events(self):
        """Verwerk pygame events"""
        events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                self.game_running = False
            if self.state == "game":
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1 :
                        if self.player.ammo >= self.current_gun.ammo_weight:  # Links klik
                            self.current_gun.shoot(self.player.pos, self.player.angle, self.objects["enemies"])
                            self.player.ammo -= self.current_gun.ammo_weight

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_a:
                        if self.current_gun == self.unlocked_guns[-1]:
                            self.current_gun = self.unlocked_guns[0]
                        else:
                            self.current_gun = self.unlocked_guns[self.unlocked_guns.index(self.current_gun) + 1]
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
                    dist, SCREEN_x, angle = enemy.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, enemy))
                    if enemy.health <= 0:
                        self.player.score += 1
                        self.objects["enemies"].remove(enemy)
            elif obj == "ammo":
                for item in self.objects["ammo"]:
                    dist, SCREEN_x, angle = item.get_render_data_fast(
                        player_pos, player_angle, wall_distances
                    )
                    if dist is not None:
                        sprites.append((dist, SCREEN_x, item))
            else:
                item = self.objects[obj]
                dist, SCREEN_x, angle = item.get_render_data_fast(
                    player_pos, player_angle, wall_distances
                )
                if dist is not None:
                    sprites.append((dist, SCREEN_x, item))

        # 3. Sorteer sprites op afstand (verste eerst)
        sprites.sort(key=lambda x: x[0], reverse=True)

        # 4. Render sprites
        for dist, SCREEN_x, enemy in sprites:
            enemy.render_fast(dist, SCREEN_x)

        # 5. Wapen laatst
        self.current_gun.draw()
        pygame.display.flip()
        
    def reset_game(self):
        # Init speler
        self.player = Player(SPAWNS["player"][0], SPAWNS["player"][1])
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
        self.player.ammo = START_AMMO
        
    def run(self):
        self.running = True
        self.state = "menu"
        while self.running:
            events = self.handle_events()
            self.handle_input()
            keys = pygame.key.get_pressed()
            if self.state == "menu":
                SCREEN.fill((70,70,70))
                Start_knop = Button(0, 200, 100, "START", 45, "black", 'white', 'white', 'black', self, "reset", False)
                Start_knop.draw_button(events)
                
                Settings_button = Button(150, 200, 60, "OPTIONS", 30, "black", 'white', 'white', 'black', self, "settings", True)
                Settings_button.draw_button(events)

                Quit_button = Button(250, 140, 60, "QUIT", 40 ,"black", 'white', 'white', 'black', self, "Stop", False)
                Quit_button.draw_button(events)

            if self.state == "game":
                self.clock.tick(100)
                self.handle_events()
                self.update()
                self.render()
                SCREEN.blit(pygame.font.SysFont('ocraextended', 20, True).render(f"{round(self.clock.get_fps())}", True, 'green'),(20, 20))
                SCREEN.blit(pygame.font.SysFont('ocraextended', 80, True).render(f"{round(self.player.health)}/10", True, 'red'),(WIDTH-300, 20))
                SCREEN.blit(pygame.font.SysFont('ocraextended', 80, True).render(f"{round(self.player.ammo)}/{AMMO_CAP}", True, 'grey'),(20, HEIGHT-150))
            if self.state == "paused":
                Restart_knop = Button(0, 200, 100, "Resume", 35, "black", 'white', 'white', 'black', self, "game", False)
                Restart_knop.draw_button(events)

                Menu_button = Button(100, 140, 60, "MENU", 35, "black", 'white', 'white', 'black', self, "menu", True)
                Menu_button.draw_button(events)
               
            if self.state == 'dead':
                SCREEN.fill((255,0,0))
                Menu_button = Button(100, 140, 60, "MENU", 35, "black", 'white', 'white', 'black', self, "menu", True)
                Menu_button.draw_button(events)
                SCREEN.blit(pygame.font.SysFont('ocraextended', 80, True).render(f"Score:{self.player.score}", True, 'black'),(WIDTH/2-160,HEIGHT/2-40))
                            
            if self.state == 'settings':
                SCREEN.fill((70,70,70))
                Menu_button = Button(100, 140, 60, "MENU", 35, "black", 'white', 'white', 'black', self, "menu", True)
                Menu_button.draw_button(events)
                
            if self.player.death and self.state == "game":
                pygame.mouse.set_visible(True)
                self.state = "dead"
            pygame.display.flip()

        if keys[pygame.K_DELETE]:
            self.running = False
            self.state = None
            pygame.quit()
        pygame.quit()


if __name__ == "__main__":
    game = Game()
    game.run()