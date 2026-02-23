import pygame
from math import sin, cos, tan, pi

pygame.init()


# Map
MAP = [
    [1,1,1,1,1,1,1,1,1,1],
    [1,0,0,0,0,0,0,0,0,1],
    [1,0,1,0,1,0,0,0,0,1],
    [1,0,1,0,1,0,0,0,1,1],
    [1,0,0,0,0,1,0,1,0,1],
    [1,0,1,0,0,0,0,0,0,1],
    [1,0,0,0,1,0,0,1,0,1],
    [1,1,1,1,1,1,1,1,1,1],
]

MAP_W = len(MAP[0])
MAP_H = len(MAP)


# Screen
WIDTH, HEIGHT = 1200, 800
screen = pygame.display.set_mode((WIDTH, HEIGHT))
clock = pygame.time.Clock()


# Constants
TILE_SIZE = 100
FOV = pi / 2
NUM_RAYS = 400
MAX_DEPTH = 500
DELTA_ANGLE = FOV / NUM_RAYS
SCALE = WIDTH // NUM_RAYS
PROJ_DIST = (WIDTH/2) / tan(FOV/2)

PLAYER_RADIUS = 10

# Textures
wall_tex = pygame.image.load("assets/muur.jpeg").convert()
wall_tex = pygame.transform.scale(wall_tex, (TILE_SIZE, TILE_SIZE))

floor_tex = pygame.image.load("assets/floor.jpeg").convert()
floor_tex = pygame.transform.scale(floor_tex, (TILE_SIZE, TILE_SIZE))

gun_1_rest = pygame.image.load("assets/Gun_sprite.png").convert_alpha()
gun_1_rest = pygame.transform.scale(gun_1_rest, (300,300))
weapon_rect = gun_1_rest.get_rect()

gun_1_shoot = pygame.image.load("assets/Recoil.png").convert_alpha()
gun_1_shoot = pygame.transform.scale(gun_1_shoot, (300,300))


sign = lambda x : 1 if x >= 0 else -1

# Vector Class
class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def __add__(self, other):
        return Vector(self.x + other.x, self.y + other.y)
    def __sub__(self, other):
        return Vector(self.x - other.x, self.y - other.y)
    def __mul__(self, other):
        try:
            return self.x * other.x + self.y * other.y
        except:
            return Vector(self.x * other, self.y * other)
    def __truediv__(self, a):
        return Vector(self.x / a , self.y / a)
    def __len__(self):
        return int((self.x**2 + self.y**2)**0.5)
    def __str__(self):
        return f"({self.x}, {self.y})"
    def __iter__(self):
        return iter((self.x,self.y))

# Player
player_pos = Vector(150, 150)
player_angle = 0

def gnc(a, sg): #Get Next Cell(cordinate, sign)
    if a % 1==0:
        return a+sg
    if sg == 1:
        return int(a)+1
    else:
        return int(a)


def will_collide(nx, ny):
    check_positions = [
        (nx - PLAYER_RADIUS, ny - PLAYER_RADIUS),
        (nx + PLAYER_RADIUS, ny - PLAYER_RADIUS),
        (nx - PLAYER_RADIUS, ny + PLAYER_RADIUS),
        (nx + PLAYER_RADIUS, ny + PLAYER_RADIUS)
    ]

    for cx, cy in check_positions:
        mx = int(cx // TILE_SIZE)
        my = int(cy // TILE_SIZE)

        # out of bounds = collision
        if mx < 0 or my < 0 or mx >= MAP_W or my >= MAP_H:
            return True

        if MAP[my][mx] == 1:
            return True

    return False



def cord_to_map(cord):
    return cord/TILE_SIZE

def map_to_cord(mapcord):
    return mapcord*TILE_SIZE

def hit_wall(pos):
    if pos.x % 1 == 0:
        x = int(pos.x)
        y = int(pos.y)
        if MAP[y][x-1] == 1 or MAP[y][x] == 1:
            return True
    elif pos.y % 1 == 0:
        x = int(pos.x)
        y = int(pos.y)
        if MAP[y-1][x] == 1 or MAP[y][x] == 1:
            return True
    return False

def draw_wall(p_pos, r_pos, player_angle, angle, ray):
    dist = ((p_pos.x-r_pos.x)**2 + (p_pos.y-r_pos.y)**2)**0.5

    dist *= cos(player_angle-angle)

    wall_height = TILE_SIZE * PROJ_DIST / dist
    y = HEIGHT/2 - wall_height/2
    col_w = WIDTH // NUM_RAYS
    column_x = ray * col_w

    shade = max(0, min(255,255-int(dist*0.7)))
    color = (shade,shade,shade)

    pygame.draw.rect(screen, color, (column_x, y, col_w, wall_height))

def dda(player_pos, player_angle):
    for ray in range(NUM_RAYS):
        angle = player_angle - FOV/2 + (ray + 0.5) * DELTA_ANGLE
        ray_pos = Vector(player_pos.x, player_pos.y)
        sina = sin(angle)
        cosa = cos(angle)
        tana = tan(angle)
        cota = 1/tan(angle)
        s_x = sign(cosa)
        s_y = sign(sina)
        ray_pos = cord_to_map(ray_pos)
        while True:
            x = gnc(ray_pos.x, s_x)
            y = gnc(ray_pos.y,s_y)
            dx = x-ray_pos.x
            dy = y-ray_pos.y
            if cosa !=0 and sina !=0:
                dnx = abs(dx/cosa) #Distance next x (on the grid)
                dny = abs(dy/sina) #Distance next y (on the grid)
                if dnx >= dny:
                    dx = dy*cota
                    x = ray_pos.x+dx
                else:
                    dy = dx*tana
                    y = ray_pos.y+dy
            else:
                if cosa == 0:
                    y = ray_pos.y
                else:
                    x = ray_pos.x
            ray_pos = Vector(x,y)
            if hit_wall(ray_pos):
                ray_pos = map_to_cord(ray_pos)
                draw_wall(player_pos, ray_pos, player_angle, angle, ray)
                break

def draw_weapon(weapon, state):
    if state == 0:
        screen.blit(gun_1_rest, ((WIDTH-weapon_rect[2])//2, HEIGHT-weapon_rect[3]))
    elif state == 1:
        screen.blit(gun_1_shoot, ((WIDTH - weapon_rect[2]) // 2+150, HEIGHT - weapon_rect[3]+50))
