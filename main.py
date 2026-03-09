from dda import *
import pygame
from math import sin, cos
from guns import *
from enemies import *

speed = 2
running = True

#mg = Minigun()
pistol = Pistol()
#bazooka = Bazooka()
current_gun = pistol
andrei = Andrei(230, 240)

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                current_gun.shoot()

    keys = pygame.key.get_pressed()
    if keys[pygame.K_DELETE]:
        pygame.quit()
        exit()
    if keys[pygame.K_LEFT]:
        player_angle -= 0.01
        player_angle %= 2*pi
    if keys[pygame.K_RIGHT]:
        player_angle += 0.01
        player_angle %= 2 * pi

    if keys[pygame.K_UP]:
        px, py = player_pos
        nx = px + cos(player_angle) * speed
        ny = py + sin(player_angle) * speed
        if not will_collide(nx, py):
            px = nx
        if not will_collide(px, ny):
            py = ny
        player_pos = Vector(px, py)

    if keys[pygame.K_DOWN]:
        px, py = player_pos
        nx = px - cos(player_angle) * speed
        ny = py - sin(player_angle) * speed
        if not will_collide(nx, py):
            px = nx
        if not will_collide(px, ny):
            py = ny
        player_pos = Vector(px, py)
    if keys[pygame.K_DOWN]:
        px, py = player_pos
        nx = px - cos(player_angle) * speed
        ny = py - sin(player_angle) * speed
        if not will_collide(nx, py):
            px = nx
        if not will_collide(px, ny):
            py = ny
        player_pos = Vector(px, py)

    screen.fill("black")
    dda(player_pos, player_angle)
    andrei.render(player_pos, player_angle)
    current_gun.shooting()
    pygame.display.flip()