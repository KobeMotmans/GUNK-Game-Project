"""
game.py - Hoofd game loop en initialisatie
"""

import pygame
from math import pi

from config import SCREEN, WIDTH, HEIGHT, MAX_DEPTH
from raycaster import dda, draw_wall
from weapons import Pistol, Minigun, Bazooka
from enemies import Andrei
from player import Player


class Game:
    def __init__(self):
        pygame.init()
        self.clock = pygame.time.Clock()
        self.running = False

        # Init speler
        self.player = Player(150, 150)

        # Init wapens
        self.pistol = Pistol()
        #self.minigun = Minigun()
        #self.bazooka = Bazooka()
        self.current_gun = self.pistol

        # Init vijanden
        self.enemies = self.create_enemies()

    def create_enemies(self):
        """Maak een lijst van test vijanden"""
        enemies = []
        for i in range(2):
            enemies.append(Andrei(400 + 40 * i, 200))
        return enemies

    def handle_events(self):
        """Verwerk pygame events"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Links klik
                    self.current_gun.shoot()

    def handle_input(self):
        """Verwerk toetsenbord input"""
        keys = pygame.key.get_pressed()

        if keys[pygame.K_DELETE]:
            self.game_running = False

        if keys[pygame.K_ESCAPE]:
            if self.game_running and not self.paused:
                pygame.mouse.set_visible(True)
                pygame.event.set_grab(False)
                self.paused = True
                self.game_running = False
        
            elif self.paused and not self.game_running:
                pygame.mouse.set_visible(False)
                pygame.event.set_grab(True)
                self.paused = False
                self.game_running = True

        
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


    def update(self):
        """Update game state"""
        self.current_gun.update()

    def render(self):
        """Render alle game elementen"""
        SCREEN.fill('black')

        player_pos = self.player.get_pos()
        player_angle = self.player.get_angle()

        # 1. Raycasting - muren direct tekenen, afstanden opslaan
        wall_distances = dda(player_pos, player_angle)

        # 2. Verzamel zichtbare sprites
        sprites = []  # (dist, SCREEN_x, enemy)

        for enemy in self.enemies:
            enemy.find_path(self.player.get_pos())
            #print(enemy.is_player_los(player_pos))
            dist, SCREEN_x, angle = enemy.get_render_data_fast(
                player_pos, player_angle, wall_distances
            )
            if dist is not None:
                sprites.append((dist, SCREEN_x, enemy))

        # 3. Sorteer sprites op afstand (verste eerst)
        sprites.sort(key=lambda x: x[0], reverse=True)

        # 4. Render sprites
        for dist, SCREEN_x, enemy in sprites:
            enemy.render_fast(dist, SCREEN_x)

        # 5. Wapen laatst
        self.current_gun.draw()

        pygame.display.flip()

    def run(self):
        """Hoofd game loop"""
        
        smallfont = pygame.font.SysFont('Corbel', 40, True)
        self.game_running = False
        self.menu_running = True
        self.paused = False
        qw = 140
        qh = 60
        sw = 200
        sh = 100
        button_color = (200, 200, 200)
        button_hover_color = (0, 0, 0)
        
        while self.menu_running or self.game_running or self.paused:
            if self.menu_running:
                text_quit = smallfont.render('Quit' , True , 'black')
                text_start = smallfont.render('PLAY' , True , 'black')
                text_quit_hover = smallfont.render('Quit' , True , 'white')
                text_start_hover = smallfont.render('PLAY' , True , 'white')
                mouse = pygame.mouse.get_pos()
                keys = pygame.key.get_pressed()
                bg_color = (70,70,70)
                SCREEN.fill(bg_color)
                for ev in pygame.event.get():
                    if ev.type == pygame.MOUSEBUTTONDOWN:
                        if (WIDTH/2-qw/2 <= mouse[0] <= WIDTH/2+qw/2 and HEIGHT/2-qh/2+HEIGHT/4 <= mouse[1] <= HEIGHT/2+qh/2+HEIGHT/4):
                            pygame.quit()
                        if (WIDTH/2-sw/2 <= mouse[0] <= WIDTH/2+sw/2 and HEIGHT/2-sh/2 <= mouse[1] <= HEIGHT/2+sh/2):
                            pygame.mouse.set_visible(False)
                            pygame.event.set_grab(True)
                            self.game_running = True
                            self.menu_running = False
                # Quit button builder
                if (WIDTH/2-qw/2 <= mouse[0] <= WIDTH/2+qw/2 and HEIGHT/2-qh/2+HEIGHT/4 <= mouse[1] <= HEIGHT/2+qh/2+HEIGHT/4):
                    pygame.draw.rect(SCREEN,button_hover_color,[WIDTH/2-qw/2,HEIGHT/2-qh/2+HEIGHT/4,qw,qh])
                    SCREEN.blit(text_quit_hover,(WIDTH/2-qw/4,HEIGHT/2+HEIGHT/4-qh/4))
                else:
                    pygame.draw.rect(SCREEN,button_color,[WIDTH/2-qw/2,HEIGHT/2-qh/2+HEIGHT/4,qw,qh])
                    SCREEN.blit(text_quit,(WIDTH/2-qw/4,HEIGHT/2+HEIGHT/4-qh/4))
    
                #Start button builder
                if (WIDTH/2-sw/2 <= mouse[0] <= WIDTH/2+sw/2 and HEIGHT/2-sh/2 <= mouse[1] <= HEIGHT/2+sh/2):
                    pygame.draw.rect(SCREEN,button_hover_color,[WIDTH/2-sw/2,HEIGHT/2-sh/2,sw,sh])
                    SCREEN.blit(text_start_hover,(WIDTH/2-sw/4,HEIGHT/2-sh/4))
                else:
                    pygame.draw.rect(SCREEN,button_color,[WIDTH/2-sw/2,HEIGHT/2-sh/2,sw,sh])
                    SCREEN.blit(text_start,(WIDTH/2-sw/4,HEIGHT/2-sh/4))
                pygame.display.flip()
    
                if keys[pygame.K_DELETE]:
                    self.game_running = False
                    self.menu_running = False
                    self.paused = False
       
            if self.game_running:
                self.clock.tick(60)
                self.handle_events()
                self.handle_input()
                self.update()
                self.render()
        
            if self.paused:
                mouse = pygame.mouse.get_pos()
                keys = pygame.key.get_pressed()
                text_menu = smallfont.render('MENU' , True , 'black')
                text_resume = smallfont.render('Resume' , True , 'black')
                text_menu_hover = smallfont.render('MENU' , True , 'white')
                text_resume_hover = smallfont.render('Resume' , True , 'white')
                for ev in pygame.event.get():
                    if ev.type == pygame.MOUSEBUTTONDOWN:
                        if (WIDTH/2-qw/2 <= mouse[0] <= WIDTH/2+qw/2 and HEIGHT/2-qh/2+HEIGHT/4 <= mouse[1] <= HEIGHT/2+qh/2+HEIGHT/4):
                            self.game_running = False
                            self.menu_running = False
                            self.paused = False
                            self.run()
                        if (WIDTH/2-sw/2 <= mouse[0] <= WIDTH/2+sw/2 and HEIGHT/2-sh/2 <= mouse[1] <= HEIGHT/2+sh/2):
                            pygame.mouse.set_visible(False)
                            pygame.event.set_grab(True)
                            self.game_running = True
                            self.paused = False
                # Menu button builder
                if (WIDTH/2-qw/2 <= mouse[0] <= WIDTH/2+qw/2 and HEIGHT/2-qh/2+HEIGHT/4 <= mouse[1] <= HEIGHT/2+qh/2+HEIGHT/4):
                    pygame.draw.rect(SCREEN,button_hover_color,[WIDTH/2-qw/2,HEIGHT/2-qh/2+HEIGHT/4,qw,qh])
                    SCREEN.blit(text_menu_hover,(WIDTH/2-qw/4,HEIGHT/2+HEIGHT/4-qh/4))
                else:
                    pygame.draw.rect(SCREEN,button_color,[WIDTH/2-qw/2,HEIGHT/2-qh/2+HEIGHT/4,qw,qh])
                    SCREEN.blit(text_menu,(WIDTH/2-qw/4,HEIGHT/2+HEIGHT/4-qh/4))
                #Resume button builder
                if (WIDTH/2-sw/2 <= mouse[0] <= WIDTH/2+sw/2 and HEIGHT/2-sh/2 <= mouse[1] <= HEIGHT/2+sh/2):
                    pygame.draw.rect(SCREEN,button_hover_color,[WIDTH/2-sw/2,HEIGHT/2-sh/2,sw,sh])
                    SCREEN.blit(text_resume_hover,(WIDTH/2-sw/4,HEIGHT/2-sh/4))
                else:
                    pygame.draw.rect(SCREEN,button_color,[WIDTH/2-sw/2,HEIGHT/2-sh/2,sw,sh])
                    SCREEN.blit(text_resume,(WIDTH/2-sw/4,HEIGHT/2-sh/4))
                pygame.display.flip()
                
                if keys[pygame.K_DELETE]:
                    self.game_running = False
                    self.menu_running = False
                    self.paused = False

        pygame.quit()


if __name__ == "__main__":
    game = Game()
    game.run()