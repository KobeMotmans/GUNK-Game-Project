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
        pygame.mixer.init()
        self.main_music = pygame.mixer.Sound("assets/Soundtrack.mp3")
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

        self.game_running = False
        self.menu_running = True

    def create_enemies(self):
        """Maak een lijst van test vijanden"""
        enemies = []
        for i in range(1):
            enemies.append(Andrei(400 + 40 * i, 200))
        return enemies

    def handle_events(self):
        """Verwerk pygame events"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.game_running = False

            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Links klik
                    self.current_gun.shoot(self.player.pos, self.player.angle, self.enemies)

    def handle_input(self):
        """Verwerk toetsenbord input"""
        keys = pygame.key.get_pressed()

        if keys[pygame.K_DELETE]:
            self.game_running = False

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
        self.player.tick()

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
            enemy.find_path(self.player)
            #print(enemy.is_player_los(player_pos))
            dist, SCREEN_x, angle = enemy.get_render_data_fast(
                player_pos, player_angle, wall_distances
            )
            if dist is not None:
                sprites.append((dist, SCREEN_x, enemy))
            if enemy.health <= 0:
                self.enemies.remove(enemy)

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
        while self.menu_running:
            mouse = pygame.mouse.get_pos()
            bg_color = (0,0,0)
            SCREEN.fill(bg_color)
            qw = 140
            qh = 60
            sw = 200
            sh = 100
            smallfont = pygame.font.SysFont('Corbel', 40, True)
            text_quit = smallfont.render('Quit' , True , 'white')
            text_start = smallfont.render('PLAY' , True , 'white')
            keys = pygame.key.get_pressed()
            button_color = (60, 30, 30)
            button_hover_color = (100, 100, 100)
            for ev in pygame.event.get():
                if ev.type == pygame.MOUSEBUTTONDOWN:
                    if (WIDTH/2-qw/2 <= mouse[0] <= WIDTH/2+qw/2 and HEIGHT/2-qh/2+HEIGHT/4 <= mouse[1] <= HEIGHT/2+qh/2+HEIGHT/4):
                        pygame.quit()
                    if (WIDTH/2-sw/2 <= mouse[0] <= WIDTH/2+sw/2 and HEIGHT/2-sh/2 <= mouse[1] <= HEIGHT/2+sh/2):
                        pygame.mouse.set_visible(False)
                        pygame.event.set_grab(True)
                        self.game_running = True
                        self.menu_running = False
                        self.main_music.play()
            # Quit button builder
            if (WIDTH/2-qw/2 <= mouse[0] <= WIDTH/2+qw/2 and HEIGHT/2-qh/2+HEIGHT/4 <= mouse[1] <= HEIGHT/2+qh/2+HEIGHT/4):
                pygame.draw.rect(SCREEN,button_hover_color,[WIDTH/2-qw/2,HEIGHT/2-qh/2+HEIGHT/4,qw,qh])
                SCREEN.blit(text_quit,(WIDTH/2-qw/4,HEIGHT/2+HEIGHT/4-qh/4))
            else:
                pygame.draw.rect(SCREEN,button_color,[WIDTH/2-qw/2,HEIGHT/2-qh/2+HEIGHT/4,qw,qh])
                SCREEN.blit(text_quit,(WIDTH/2-qw/4,HEIGHT/2+HEIGHT/4-qh/4))

            #Start button builder
            if (WIDTH/2-sw/2 <= mouse[0] <= WIDTH/2+sw/2 and HEIGHT/2-sh/2 <= mouse[1] <= HEIGHT/2+sh/2):
                pygame.draw.rect(SCREEN,button_hover_color,[WIDTH/2-sw/2,HEIGHT/2-sh/2,sw,sh])
                SCREEN.blit(text_start,(WIDTH/2-sw/4,HEIGHT/2-sh/4))
            else:
                pygame.draw.rect(SCREEN,button_color,[WIDTH/2-sw/2,HEIGHT/2-sh/2,sw,sh])
                SCREEN.blit(text_start,(WIDTH/2-sw/4,HEIGHT/2-sh/4))
            pygame.display.flip()

            if keys[pygame.K_DELETE]:
                self.game_running = False
                self.menu_running = False

        while self.game_running:
            self.clock.tick(60)
            self.handle_events()
            self.handle_input()
            self.update()
            self.render()
        pygame.quit()


if __name__ == "__main__":
    game = Game()
    game.run()