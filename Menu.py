import pygame
from config import HEIGHT, WIDTH, SCREEN, set_resolution, FONT, BILAL, VICTORY_SCREEN, SCREEN_DEAD, START_HEALTH, AMMO_CAP, ELEV_SPEED, MAX_LEVEL
from collections import deque
class Menu:
    def __init__(self, color, GAME):
        self.bg_color = color
        self.credits_height = HEIGHT
        self.game = GAME
        self.volume_slider = Slider(y_pos=50,width=400,height=12,min_val=0.0,max_val=1.0,initial_val=0.5,label="VOLUME",GAME = self.game)
        
        self.lift_time = 120
        self.credits_height = HEIGHT

        self.credits_height = HEIGHT

        self.title_font = pygame.font.Font(FONT, 300)
        self.title_font.set_bold(True)

        self.text_font = pygame.font.Font(FONT, 40)
   
    def draw_main_menu(self, events):
        SCREEN.fill(self.bg_color)
        
        SCREEN.blit(self.title_font.render("GUNK", True, 'white'),(WIDTH/2-360, HEIGHT/2-350))
        
        Start_knop = Button(0, 200, 100, "START", 45, "black", 'white', 'white', 'black', self.game, "reset", False)
        Start_knop.draw_button(events)

        Settings_button = Button(100, 200, 60, "OPTIONS", 30, "black", 'white', 'white', 'black', self.game, "settings", True)
        Settings_button.draw_button(events)

        Credits_button = Button(180, 200, 60, "CREDITS", 30 ,"black", 'white', 'white', 'black', self.game, "credits", True)
        Credits_button.draw_button(events)

        Quit_button = Button(260, 140, 60, "QUIT", 40 ,"black", 'white', 'white', 'black', self.game, "Stop", False)
        Quit_button.draw_button(events)
    def draw_settings(self, events):
        SCREEN.fill(self.bg_color)
        
        high_label = "[HIGH RES]" if self.game.resolution == "high" else "HIGH RES"
        low_label  = "[LOW RES]"  if self.game.resolution == "low"  else "LOW RES"
        
        Res_high = Button(-70, 200, 60, high_label, 25, "black", "white", "white", "black", self.game, "settings", True, -220, "res_high")
        Res_low = Button(-70, 200, 60, low_label, 25, "black", "white", "white", "black", self.game, "settings", True, 220, "res_low")
        
        tuto_label = "[TUTORIAL]" if self.game.bilal.flags["general"] == True else "TUTORIAL"
        
        Tutorial_button = Button(100, 250, 60, tuto_label, 25, "black", "white", "white", "black", self.game, "settings", True, 0, "tutorial")
        self.volume_slider.draw(events)
        Menu_button = Button(230, 140, 60, "MENU", 35, "black", 'white', 'white', 'black', self.game, "menu", True)
        
        Tutorial_button.draw_button(events)
        Res_high.draw_button(events)
        Res_low.draw_button(events)
        Menu_button.draw_button(events)
        self.volume_slider.draw(events)

    def draw_credits(self, events):
        SCREEN.fill(self.bg_color)

        y = self.credits_height
        x = WIDTH / 4
        white = "white"

        # Titel
        SCREEN.blit(
            self.title_font.render("GUNK", True, white),
            (WIDTH / 2 - 360, y)
        )

        # Credits regels
        lines = [
            ("Developed by:", 280),
            ("Kobe Motmans", 320),
            ("Andreas Meuwissen", 360),
            ("Ruben Verreth", 400),
            ("Music by:", 480),
            ("nog niet wiel", 520),
            ("Special thanks to:", 600),
            ("Andrei", 640),
            ("Ahmed", 680),
            ("Ruben", 720),
            ("Jan", 760),
            ("Bilal", 800),
        ]

        for text, offset in lines:
            SCREEN.blit(
                self.text_font.render(text, False, white),
                (x, y + offset)
            )

        # Scroll
        self.credits_height -= 1
        if self.credits_height < -900:
            self.credits_height = HEIGHT

        # Menu knop
        Menu_button = Button(
            self.credits_height + 540,
            140,
            60,
            "MENU",
            35,
            "black",
            'white',
            'white',
            'black',
            self.game,
            "menu",
            True
        )
        Menu_button.draw_button(events)
    def draw_paused_screen(self, events):
        Restart_knop = Button(0, 200, 100, "Resume", 35, "black", 'white', 'white', 'black', self.game, "game", False)
        Restart_knop.draw_button(events)

        Menu_button = Button(100, 140, 60, "MENU", 35, "black", 'white', 'white', 'black', self.game, "menu", True)
        Menu_button.draw_button(events)
    def draw_dead_screen(self,events):
        SCREEN.blit(SCREEN_DEAD, (0,0))
        Menu_button = Button(100, 140, 60, "MENU", 35, "black", 'white', 'white', 'black', self.game, "menu", True)
        Menu_button.draw_button(events)
        SCREEN.blit(pygame.font.SysFont(FONT, 80, True).render(f"Score:{self.game.player.score}", True, 'black'),(WIDTH/2-160,HEIGHT/2-40))
    def draw_escaped_screen(self,events):
        SCREEN.blit(VICTORY_SCREEN, (0,0))
        SCREEN.blit(pygame.font.SysFont(FONT, 150, True).render("SUCCESFUL", True, 'white'),(WIDTH/2-370, HEIGHT/2-400))
        SCREEN.blit(pygame.font.SysFont(FONT, 150, True).render("ESCAPE", True, 'white'),(WIDTH/2-280, HEIGHT/2-200))
        SCREEN.blit(pygame.font.SysFont(FONT, 80, True).render(f"Score:{self.game.player.score}", True, 'black'),(WIDTH/2-160,HEIGHT/2-40))
        Menu_button = Button(100, 140, 60, "MENU", 35, "black", 'white', 'white', 'black', self.game, "menu", True)
        Menu_button.draw_button(events)
        
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
        self.font = pygame.font.Font(FONT, self.text_size)
        self.font.set_bold(True)
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
                    elif self.function == "res_low":
                        set_resolution("low")
                        self.GAME.resolution = "low"
                    elif self.function == "tutorial":
                        self.GAME.tutorial.flags["general"] = not self.GAME.tutorial.flags["general"]
                    elif self.state_change == "reset":
                        self.GAME.reset_game()
                    elif self.state_change == "Stop":
                        pygame.mixer.stop()
                        self.GAME.running = False
                        self.GAME.state = None
                    elif self.state_change == "game":
                        pygame.mixer.unpause()
                        self.GAME.state = "game"
                    
        color = self.button_hov_color if hovering else self.button_color
        text_color = self.text_hov_color if hovering else self.text_color
        
        pygame.draw.rect(SCREEN,color,[WIDTH/2-self.w/2+self.x_pos,HEIGHT/2-self.h/2+self.y_pos,self.w,self.h])
        SCREEN.blit(self.font.render(self.text, True, text_color),(WIDTH/2-self.w/3+self.x_pos,HEIGHT/2-self.text_size/2+self.y_pos))

# ---- Het grootste deel hiervan is AI code, eerder flavour en tutorial dan functionele game code-----
class Slider:
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

        self.font = pygame.font.Font(FONT, 25)

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

        label_surf = self.font.render(f"{self.label}: {int(self.value * 100)}%", True, 'white')
        SCREEN.blit(label_surf, (self.track_x, self.track_y - 45))

class Tekstballon:
    def __init__(self, text, y_pos, x_pos, max_width=280, padding=10):
        self.text = text
        self.y_pos = y_pos
        self.x_pos = x_pos
        self.max_width = max_width
        self.padding = padding
        self.font = pygame.font.Font(FONT, 20)
    @staticmethod
    def wrap_text(text, font, max_width):
        words = text.split(" ")
        lines = []
        current_line = ""

        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            if font.size(test_line)[0] <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        return lines

    def draw(self):

        # 1. Splits op expliciete nieuwe regels (;)
        raw_lines = []
        for part in self.text.split(";"):
            raw_lines.extend(self.wrap_text(part, self.font, self.max_width))

        line_height = self.font.get_height()
        text_height = line_height * len(raw_lines)
        text_width = max(self.font.size(line)[0] for line in raw_lines) if raw_lines else 0

        box_w = text_width + self.padding * 2
        box_h = text_height + self.padding * 2

        x = self.x_pos
        y = self.y_pos

        # 2. Achtergrond en rand
        pygame.draw.rect(
            SCREEN,
            (0, 0, 0),
            [x - 4, y - 4, box_w + 8, box_h + 8],
            border_radius=8
        )
        pygame.draw.rect(
            SCREEN,
            (255, 255, 255),
            [x, y, box_w, box_h],
            border_radius=8
        )

        # 3. Tekenen van tekst
        for i, line in enumerate(raw_lines):
            SCREEN.blit(
                self.font.render(line, False, (0, 0, 0)),
                (x + self.padding, y + self.padding + i * line_height)
            )

        # 4. “Staart” van de ballon (automatisch gecentreerd)
        tail_x = x + box_w // 2
        tail_y = y + box_h

        pygame.draw.polygon(
            SCREEN,
            (0, 0, 0),
            [(tail_x - 12, tail_y),
             (tail_x + 12, tail_y),
             (tail_x, tail_y + 22)]
        )
        pygame.draw.polygon(
            SCREEN,
            (255, 255, 255),
            [(tail_x - 8, tail_y),
             (tail_x + 8, tail_y),
             (tail_x, tail_y + 18)]
        )


class Bilal:
    def __init__(self):
        # Dialog / speech state
        self.queue = deque()
        self.current = None
        self.timer = 0

        self.interrupt_msg = None
        self.interrupt_timer = 0

        # Tutorial flags
        self.flags = {
            "general": True,
            "monster": False,
            "seen_enemy": False,
            "got_keycard": False,
            "boss_warning": False,
            "floor_3": False,
            "floor_1": False,
            "floor_0": False,
        }

    # ======================
    # SPEECH LOGIC
    # ======================

    def say(self, text, duration=250):
        self.queue.append((text, duration))

    def interrupt(self, text, duration=250):
        self.interrupt_msg = text
        self.interrupt_timer = duration

    def clear(self):
        self.queue.clear()
        self.current = None
        self.timer = 0

    def update(self):
        if self.interrupt_timer > 0:
            self.interrupt_timer -= 1
            if self.interrupt_timer == 0:
                self.interrupt_msg = None
            return

        if self.timer > 0:
            self.timer -= 1
            if self.timer == 0:
                self.current = None
            return

        if self.queue:
            self.current, self.timer = self.queue.popleft()

    def draw(self):
        text = None

        if self.interrupt_msg:
            text = self.interrupt_msg
        elif self.current:
            text = self.current

        if text:
            Tekstballon(text, HEIGHT - 400, 20).draw()
            SCREEN.blit(BILAL, (0, HEIGHT - 300))

    # ======================
    # TUTORIAL / EVENTS
    # ======================

    def trigger(self, event_name):
        if self.flags.get(event_name):
            return

        self.flags[event_name] = True

        if event_name == "seen_enemy":
            self.interrupt(
                "Pas op, de assistenten proberen je ontsnapping tegen te houden! "
                "Je zal ze moeten neerschieten met linker-muisklik!"
            )

        elif event_name == "monster":
            self.interrupt(
                "Door Monster Energy™ te drinken krijg je twee HP terug!", 200
            )

        elif event_name == "keycard":
            self.interrupt(
                "Daar ligt de keycard! Breng hem naar de lift en verdwijn van deze verdieping"
            )

        elif event_name == "boss_warning":
            self.interrupt(
                "Daar is Jan! Dit is je kans om hier een einde aan te maken!"
            )

        elif event_name == "floor_3":
            self.say(
                "We zijn op verdieping 3 geraakt. Je hebt ook een minigun gevonden "
                "op verdieping 4. Duw op A om te wisselen",
                400
            )

        elif event_name == "floor_1":
            self.say(
                "Net wanneer we hier binnenkwamen lag hier een rifle. Zoek hem via A."
            )

        elif event_name == "floor_0":
            self.say(
                "Dit is verdieping 0. Er is wel een probleempje. Jan is hier, en hij heeft de laatste keycard."
            )
            self.say(
                "Je kan hem vinden in de garage. Maar pas op, hij is heel erg sterk!"
            )

