import pygame
from config import HEIGHT, WIDTH, SCREEN, set_resolution

class Button:
    def __init__(self, y_pos, width, height, text, text_size, text_color, text_hov_color, button_color, button_h_color, GAME, state_change, mouse_vis, x_pos=0, function = None):
        self.y_pos = y_pos
        self.h = height
        self.w = width
        self.text = text
        self.text_size = text_size
        self.text_color = text_color
        self.text_hov_color = text_hov_color
        self.button_color = button_color
        self.button_hov_color = button_h_color
        self.GAME = GAME
        self.state_change = state_change
        self.mouse_vis = mouse_vis
        self.x_pos = x_pos
        self.function = function
    def draw_button(self, events):
        mouse = pygame.mouse.get_pos()
        hovering = (WIDTH/2-self.w/2+self.x_pos <= mouse[0] <= WIDTH/2+self.w/2+self.x_pos and HEIGHT/2-self.h/2+self.y_pos <= mouse[1] <= HEIGHT/2+self.h/2+self.y_pos)
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if hovering:
                    pygame.mouse.set_visible(self.mouse_vis)
                    pygame.event.set_grab(self.state_change == "game")
                    self.GAME.state = self.state_change
                    if self.function == "res_high":
                        set_resolution("high")
                        self.GAME.resolution = "high"
                    if self.function == "res_low":
                        set_resolution("low")
                        self.GAME.resolution = "low"
                    if self.state_change == "reset":
                        self.GAME.reset_game()
                    if self.state_change == "Stop":
                        pygame.mixer.stop()
                        self.GAME.running = False
                        self.GAME.state = None
                    if self.state_change == "game":
                        pygame.mixer.unpause()
                        self.GAME.state = "game"

        color = self.button_hov_color if hovering else self.button_color
        text_color = self.text_hov_color if hovering else self.text_color
        
        pygame.draw.rect(SCREEN,color,[WIDTH/2-self.w/2+self.x_pos,HEIGHT/2-self.h/2+self.y_pos,self.w,self.h])
        SCREEN.blit(pygame.font.SysFont('ocraextended', self.text_size, True).render(self.text, True, text_color),(WIDTH/2-self.w/3+self.x_pos,HEIGHT/2-self.text_size/2+self.y_pos))

class Slider: #AI code
    def __init__(self, y_pos, width, height, min_val, max_val, initial_val, label, GAME):
        self.y_pos = y_pos
        self.w = width
        self.h = height
        self.min_val = min_val
        self.max_val = max_val
        self.value = initial_val
        self.label = label
        self.GAME = GAME
        self.dragging = False

        self.track_x = WIDTH / 2 - width / 2
        self.track_y = HEIGHT / 2 + y_pos
        self.handle_r = height

    def get_handle_x(self):
        ratio = (self.value - self.min_val) / (self.max_val - self.min_val)
        return self.track_x + ratio * self.w

    def draw(self, events):
        mouse = pygame.mouse.get_pos()
        mouse_buttons = pygame.mouse.get_pressed()

        handle_x = self.get_handle_x()

        # Start / stop dragging
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if abs(mouse[0] - handle_x) <= self.handle_r + 5 and abs(mouse[1] - self.track_y) <= self.handle_r + 5:
                    self.dragging = True
            if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                self.dragging = False

        if self.dragging and mouse_buttons[0]:
            clamped = max(self.track_x, min(mouse[0], self.track_x + self.w))
            ratio = (clamped - self.track_x) / self.w
            self.value = self.min_val + ratio * (self.max_val - self.min_val)
            self.GAME.main_music.set_volume(self.value)

        # Draw track
        pygame.draw.rect(SCREEN, 'white', [self.track_x, self.track_y - 4, self.w, 8], border_radius=4)

        # Draw filled portion
        filled_w = self.get_handle_x() - self.track_x
        pygame.draw.rect(SCREEN, (0, 200, 255), [self.track_x, self.track_y - 4, filled_w, 8], border_radius=4)

        # Draw handle
        handle_x = self.get_handle_x()
        pygame.draw.circle(SCREEN, (0, 200, 255) if self.dragging else 'white', (int(handle_x), int(self.track_y)), self.handle_r)

        # Draw label + value
        font = pygame.font.SysFont('ocraextended', 25, True)
        label_surf = font.render(f"{self.label}: {int(self.value * 100)}%", True, 'white')
        SCREEN.blit(label_surf, (self.track_x, self.track_y - 45))
        
class Tekstballon:
    def __init__(self, text, y_pos, x_pos):
        self.text = text
        self.y_pos = y_pos
        self.x_pos = x_pos
        self.linewidth = 0

    def draw(self):
        self.linewidth = 0
        pygame.draw.rect(SCREEN, (0, 0, 0), [self.x_pos-5, self.y_pos-5, 300, 110])
        pygame.draw.rect(SCREEN, (255, 255, 255), [self.x_pos, self.y_pos, 290, 100])
    
        triangle_points = [
            (self.x_pos + 10, self.y_pos + 100),   # Top-left (bottom of rect)
            (self.x_pos + 10, self.y_pos + 135),   # Tip of the tail
            (self.x_pos + 45, self.y_pos + 100),   # Top-right (bottom of rect)
        ]
        pygame.draw.polygon(SCREEN, (0, 0, 0), triangle_points)
    
        inner_triangle_points = [
            (self.x_pos + 15, self.y_pos + 100),   # Top-left (inset by 2)
            (self.x_pos + 15, self.y_pos + 125),   # Tip (inset, slightly shorter)
            (self.x_pos + 40, self.y_pos + 100),   # Top-right (inset by 2)
        ]
        pygame.draw.polygon(SCREEN, (255, 255, 255), inner_triangle_points)
    
        font = pygame.font.SysFont('ocraextended', 20, False)
        for zin in self.text.split(";"):
            SCREEN.blit(font.render(zin, False, (0, 0, 0)), (self.x_pos + 5, self.y_pos + self.linewidth + 5))
            self.linewidth += 20
            