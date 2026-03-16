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
        self.running = True

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
        for i in range(20):
            enemies.append(Andrei(100 + 40 * i, 200))
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
            self.running = False

        if keys[pygame.K_LEFT]:
            self.player.rotate(-1)

        if keys[pygame.K_RIGHT]:
            self.player.rotate(1)

        if keys[pygame.K_UP]:
            self.player.move(1)

        if keys[pygame.K_DOWN]:
            self.player.move(-1)

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
        sprites = []  # (dist, screen_x, enemy)

        for enemy in self.enemies:
            dist, screen_x, angle = enemy.get_render_data_fast(
                player_pos, player_angle, wall_distances
            )
            if dist is not None:
                sprites.append((dist, screen_x, enemy))

        # 3. Sorteer sprites op afstand (verste eerst)
        sprites.sort(key=lambda x: x[0], reverse=True)

        # 4. Render sprites
        for dist, screen_x, enemy in sprites:
            enemy.render_fast(dist, screen_x)

        # 5. Wapen laatst
        self.current_gun.draw()

        pygame.display.flip()

    def run(self):
        """Hoofd game loop"""
        self.clock.tick(120)
        while self.running:
            self.handle_events()
            self.handle_input()
            self.update()
            self.render()

        pygame.quit()


if __name__ == "__main__":
    game = Game()
    game.run()