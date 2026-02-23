from dda import *
import pygame
from math import sin, cos

speed = 0.6
running = True

weapon_state = 0
flash_time = 15
recoil_time = 50
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                weapon_state = 1
                temp_flash_time = flash_time
                temp_recoil_time = recoil_time

    keys = pygame.key.get_pressed()
    if keys[pygame.K_DELETE]:
        pygame.quit()
        exit()
    if keys[pygame.K_LEFT]:
        player_angle -= 0.01
    if keys[pygame.K_RIGHT]:
        player_angle += 0.01

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
    if weapon_state != 0:
        if temp_flash_time > 0:
            temp_flash_time -= 1
        elif temp_recoil_time > 0:
            temp_recoil_time -= 1
            weapon_state = 2
        else:
            weapon_state = 0
    draw_weapon(None, weapon_state)
    pygame.display.flip()