"""
game.py - Hoofd game loop en initialisatie
"""

import pygame
from math import pi

from config import SCREEN, WIDTH, HEIGHT, COLOR_BLACK, MAX_DEPTH
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
        """Render alle game elementen met geoptimaliseerde Z-indexing"""
        SCREEN.fill(COLOR_BLACK)

        # 1. Raycasting - muren direct tekenen, afstanden opslaan
        wall_distances = dda(self.player.get_pos(), self.player.get_angle())
        # wall_distances = [dist_ray0, dist_ray1, ..., dist_rayN]

        # 2. Verzamel alleen zichtbare sprites met diepte
        sprites = []  # Lijst van (dist, angle, enemy)

        for enemy in self.enemies:
            dist, angle = enemy.get_render_data(
                self.player.get_pos(),
                self.player.get_angle()
            )
            if dist is not None:  # Alleen toevoegen als zichtbaar
                sprites.append((dist, angle, enemy))

        # 3. Sorteer alleen sprites (meestal < 50 items, vaak < 20)
        # O(n log n) maar met kleine n = snel!
        sprites.sort(key=lambda x: x[0], reverse=True)

        # 4. Merge render: sprites tussen muren in
        # We lopen door de rays van links naar rechts
        # Een sprite moet tussen de huidige muur en de vorige in

        sprite_idx = 0
        num_sprites = len(sprites)

        for ray_num, wall_dist in enumerate(wall_distances):
            # Render alle sprites die VERDER zijn dan deze muur
            # (dus achter deze muur, moeten eerst getekend worden)
            while sprite_idx < num_sprites and sprites[sprite_idx][0] > wall_dist:
                dist, angle, enemy = sprites[sprite_idx]
                enemy.render(dist, angle)
                sprite_idx += 1

            # Deze muur is al getekend door dda(), geen actie nodig

        # 5. Resterende sprites (dichterbij dan de verste muur)
        while sprite_idx < num_sprites:
            dist, angle, enemy = sprites[sprite_idx]
            enemy.render(dist, angle)
            sprite_idx += 1

        # 6. Wapen laatst (altijd voorste laag)
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