import pygame
from config import HEIGHT, WIDTH, SCREEN, set_resolution, FONT, BILAL, VICTORY_SCREEN, SCREEN_DEAD,SCREEN_DEAD_SILLY, START_HEALTH, AMMO_CAP, ELEV_SPEED, MAX_LEVEL, ELEV_TIME, SILLY_FONT, DEFAULT_PORT, SFX_VOLUME
from collections import deque
from map_loader import M
class Menu:
    def __init__(self, color):
        self.bg_color = color
        self.credits_height = HEIGHT
        self.volume_slider = None
        self.sfx_volume_slider = None
        
        self.lift_time = 120
        self.credits_height = HEIGHT
        self.lift_time = ELEV_TIME
        self.silly_mode = False
        self.loading_progress = 0

        # Multiplayer input fields
        self.mp_name_input = ""
        self.mp_host_port = "5555"
        self.mp_join_ip = "127.0.0.1"
        self.mp_join_port = "5555"
        self.input_focus = None
        self.lobby_status = ""
        self.client_list = [("You (Host)", 0)]
        self.waiting_text = "Verbinden..."
        self.mp_status = ""

    def draw_loading_screen(self):
        SCREEN.fill(self.bg_color)
        loading_font = pygame.font.Font(SILLY_FONT if self.silly_mode else FONT, int(HEIGHT * 0.1))
        loading_font.set_bold(True)
        load_surf = loading_font.render("Loading...", True, 'white')
        SCREEN.blit(load_surf, (WIDTH // 2 - load_surf.get_width() // 2, HEIGHT - int(HEIGHT * 0.29)))

        title_font = pygame.font.Font(SILLY_FONT if self.silly_mode else FONT, int(HEIGHT * 0.29))
        title_font.set_bold(True)
        title_surf = title_font.render("GUNK", True, 'white')
        SCREEN.blit(title_surf, (WIDTH // 2 - title_surf.get_width() // 2, HEIGHT // 2 - title_surf.get_height() // 2))

        bar_width = int(WIDTH * 0.31)
        bar_height = int(HEIGHT * 0.03)
        bar_x = WIDTH // 2 - bar_width // 2
        bar_y = HEIGHT - int(HEIGHT * 0.15)

        pygame.draw.rect(SCREEN, (80, 80, 80), (bar_x, bar_y, bar_width, bar_height))

        progress_width = bar_width * self.loading_progress
        pygame.draw.rect(SCREEN, (0, 200, 0), (bar_x, bar_y, progress_width, bar_height))
        self.loading_progress += 0.2
        pygame.display.flip()

    def _draw_main_button(self, events, text, y_pos, w, action=None, h=55, font_size=34, x=None):
        if x is None:
            x = WIDTH//2 - w//2
        rect = pygame.Rect(x, y_pos, w, h)
        mouse = pygame.mouse.get_pos()
        hover = rect.collidepoint(mouse)
        pygame.draw.rect(SCREEN, (100, 100, 100) if hover else (70, 70, 70), rect, border_radius=8)
        if hover:
            pygame.draw.rect(SCREEN, (180, 180, 180), rect, 2, border_radius=8)
        font = pygame.font.Font(SILLY_FONT if self.silly_mode else FONT, font_size)
        surf = font.render(text, True, 'white')
        SCREEN.blit(surf, (x + w//2 - surf.get_width()//2, y_pos + h//2 - surf.get_height()//2))
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if rect.collidepoint(mouse) and action:
                    action()
                    return True
        return False

    def draw_main_menu(self, events, GAME):
        self.game = GAME
        SCREEN.fill(self.bg_color)
        title_font = pygame.font.Font(SILLY_FONT if self.silly_mode else FONT, int(HEIGHT * 0.29))
        title_font.set_bold(True)
        title_surf = title_font.render("GUNK", True, 'white')
        SCREEN.blit(title_surf, (WIDTH // 2 - title_surf.get_width() // 2, int(HEIGHT * 0.08)))

        c = WIDTH//2
        self._draw_main_button(events, "SOLO", int(HEIGHT * 0.38), int(WIDTH * 0.09), lambda: GAME.reset_game(), font_size=36, x=c-int(WIDTH * 0.1))
        self._draw_main_button(events, "MULTIPLAYER", int(HEIGHT * 0.38), int(WIDTH * 0.11), lambda: setattr(GAME, 'state', 'multiplayer_menu'), font_size=36, x=c+int(WIDTH * 0.01))
        self._draw_main_button(events, "OPTIONS", int(HEIGHT * 0.47), int(WIDTH * 0.11), lambda: setattr(GAME, 'state', 'settings'), font_size=36)
        self._draw_main_button(events, "CREDITS", int(HEIGHT * 0.54), int(WIDTH * 0.11), lambda: setattr(GAME, 'state', 'credits'), font_size=36)
        self._draw_main_button(events, "QUIT", int(HEIGHT * 0.62), int(WIDTH * 0.11), lambda: setattr(GAME, 'running', False), font_size=36)
    # --- Multiplayer UI ----------------------------------------

    def _draw_text_input(self, events, label, current_text, x, y, width, height=35, field_id=None, numeric=False):
        """Draw a text input field. Returns the (possibly updated) text."""
        mouse = pygame.mouse.get_pos()
        rect = pygame.Rect(x, y, width, height)

        label_font = pygame.font.Font(FONT, 22)
        label_surf = label_font.render(label, True, 'white')
        SCREEN.blit(label_surf, (x, y - 25))

        focused = self.input_focus == field_id
        bg_color = (60, 60, 80) if focused else (40, 40, 40)
        pygame.draw.rect(SCREEN, bg_color, rect, border_radius=4)
        pygame.draw.rect(SCREEN, (180, 180, 255) if focused else (100, 100, 100), rect, 2, border_radius=4)

        font = pygame.font.Font(FONT, 22)
        display_text = current_text + ("|" if focused else "")
        text_surf = font.render(display_text, True, 'white')
        SCREEN.blit(text_surf, (x + 6, y + (height - text_surf.get_height()) // 2))

        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if rect.collidepoint(mouse):
                    self.input_focus = field_id
                elif self.input_focus == field_id:
                    self.input_focus = None
            if ev.type == pygame.KEYDOWN and self.input_focus == field_id:
                if ev.key == pygame.K_BACKSPACE:
                    current_text = current_text[:-1]
                elif ev.key == pygame.K_ESCAPE:
                    self.input_focus = None
                elif ev.unicode and len(current_text) < 20:
                    if numeric and ev.unicode in "0123456789":
                        current_text += ev.unicode
                    elif not numeric and ev.unicode.isprintable():
                        current_text += ev.unicode
        return current_text

    def _draw_button_custom(self, events, text, x, y, w, h, action=None):
        """Simple custom button returning True if clicked."""
        mouse = pygame.mouse.get_pos()
        rect = pygame.Rect(x, y, w, h)
        hover = rect.collidepoint(mouse)
        pygame.draw.rect(SCREEN, (100, 100, 100) if hover else (70, 70, 70), rect, border_radius=6)
        if hover:
            pygame.draw.rect(SCREEN, (180, 180, 180), rect, 2, border_radius=6)
        font = pygame.font.Font(FONT, 28)
        surf = font.render(text, True, 'white')
        SCREEN.blit(surf, (x + w//2 - surf.get_width()//2, y + h//2 - surf.get_height()//2))
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if rect.collidepoint(mouse) and action:
                    action()
                    return True
        return False

    def draw_multiplayer_menu(self, events, GAME):
        self.game = GAME
        SCREEN.fill(self.bg_color)

        name_label = pygame.font.Font(FONT, 22).render("JOUW NAAM", True, (200, 200, 200))
        SCREEN.blit(name_label, (WIDTH//2 - name_label.get_width()//2, int(HEIGHT * 0.04)))
        self.mp_name_input = self._draw_text_input(events, "", self.mp_name_input, WIDTH//2 - int(WIDTH * 0.06), int(HEIGHT * 0.07), int(WIDTH * 0.125), field_id="mp_name")

        divider_x = WIDTH // 2
        pygame.draw.line(SCREEN, (100, 100, 100), (divider_x, int(HEIGHT * 0.13)), (divider_x, HEIGHT - int(HEIGHT * 0.04)), 2)

        host_font = pygame.font.Font(FONT, 36)
        host_label = host_font.render("HOST", True, 'white')
        SCREEN.blit(host_label, (divider_x//2 - host_label.get_width()//2, int(HEIGHT * 0.13)))

        host_info = pygame.font.Font(FONT, 18).render(f"Port: {self.mp_host_port}", True, (180, 180, 180))
        SCREEN.blit(host_info, (divider_x//2 - host_info.get_width()//2, int(HEIGHT * 0.17)))

        local_ip = "0.0.0.0"
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except:
            pass
        ip_info = pygame.font.Font(FONT, 16).render(f"IP: {local_ip}", True, (140, 140, 140))
        SCREEN.blit(ip_info, (divider_x//2 - ip_info.get_width()//2, int(HEIGHT * 0.19)))

        self.mp_host_port = self._draw_text_input(events, "Port:", self.mp_host_port, int(WIDTH * 0.02), int(HEIGHT * 0.24), divider_x - int(WIDTH * 0.03), field_id="mp_host_port", numeric=True)

        def start_host():
            try:
                port = int(self.mp_host_port) if self.mp_host_port else DEFAULT_PORT
            except ValueError:
                port = DEFAULT_PORT
            name = self.mp_name_input.strip() or "Host"
            GAME.host_port = port
            GAME.player_name = name
            GAME._start_hosting()
        start_y = int(HEIGHT * 0.31)
        self._draw_button_custom(events, "HOST GAME", int(WIDTH * 0.02), start_y, divider_x - int(WIDTH * 0.03), int(HEIGHT * 0.05), start_host)

        join_label = host_font.render("JOIN", True, 'white')
        SCREEN.blit(join_label, (divider_x + (divider_x//2) - join_label.get_width()//2, int(HEIGHT * 0.13)))

        self.mp_join_ip = self._draw_text_input(events, "IP Address:", self.mp_join_ip, divider_x + int(WIDTH * 0.02), int(HEIGHT * 0.18), divider_x - int(WIDTH * 0.03), field_id="mp_join_ip")
        self.mp_join_port = self._draw_text_input(events, "Port:", self.mp_join_port, divider_x + int(WIDTH * 0.02), int(HEIGHT * 0.24), divider_x - int(WIDTH * 0.03), field_id="mp_join_port", numeric=True)

        def do_connect():
            name = self.mp_name_input.strip() or "Player"
            ip = self.mp_join_ip.strip() or "127.0.0.1"
            try:
                port = int(self.mp_join_port) if self.mp_join_port else DEFAULT_PORT
            except ValueError:
                port = DEFAULT_PORT
            GAME._do_connect(ip, port, name)
        self._draw_button_custom(events, "JOIN GAME", divider_x + int(WIDTH * 0.02), int(HEIGHT * 0.31), divider_x - int(WIDTH * 0.03), int(HEIGHT * 0.05), do_connect)

        if self.mp_status:
            color = (0, 200, 0) if "gelukt" in self.mp_status else (200, 0, 0)
            status = pygame.font.Font(FONT, 22).render(self.mp_status, True, color)
            SCREEN.blit(status, (WIDTH//2 - status.get_width()//2, int(HEIGHT * 0.39)))

        self._draw_button_custom(events, "BACK", WIDTH//2 - int(WIDTH * 0.03), HEIGHT - int(HEIGHT * 0.05), int(WIDTH * 0.06), int(HEIGHT * 0.03), lambda: setattr(GAME, 'state', 'menu'))

    def draw_host_lobby(self, events, GAME):
        self.game = GAME
        SCREEN.fill(self.bg_color)
        title = pygame.font.Font(FONT, 50).render("LOBBY", True, 'white')
        SCREEN.blit(title, (WIDTH//2 - title.get_width()//2, int(HEIGHT * 0.1)))
        port_text = pygame.font.Font(FONT, 25).render(f"Port: {GAME.host_port}", True, (200, 200, 200))
        SCREEN.blit(port_text, (WIDTH//2 - port_text.get_width()//2, int(HEIGHT * 0.16)))
        ip_text = pygame.font.Font(FONT, 20).render("Deel je IP-adres met vrienden", True, (150, 150, 150))
        SCREEN.blit(ip_text, (WIDTH//2 - ip_text.get_width()//2, int(HEIGHT * 0.19)))
        players = GAME.network_server.get_lobby_players() if GAME.network_server else [("You (Host)", 0)]
        y = int(HEIGHT * 0.25)
        for name, pid in players:
            color = (0, 200, 255) if pid == 0 else (255, 255, 255)
            p_text = pygame.font.Font(FONT, 30).render(f"[P{pid}] {name}", True, color)
            SCREEN.blit(p_text, (WIDTH//2 - p_text.get_width()//2, y))
            y += int(HEIGHT * 0.04)
        if y == int(HEIGHT * 0.25):
            wait = pygame.font.Font(FONT, 22).render("Wachten op spelers...", True, (150, 150, 150))
            SCREEN.blit(wait, (WIDTH//2 - wait.get_width()//2, y))
        def start_multi_game():
            GAME._start_multiplayer_game()
        if self.lobby_status:
            status = pygame.font.Font(FONT, 22).render(self.lobby_status, True, (0, 200, 0))
            SCREEN.blit(status, (WIDTH//2 - status.get_width()//2, HEIGHT - int(HEIGHT * 0.12)))
        if players:
            self._draw_button_custom(events, "START GAME", WIDTH//2 - int(WIDTH * 0.05), HEIGHT - int(HEIGHT * 0.09), int(WIDTH * 0.1), int(HEIGHT * 0.05), start_multi_game)
        self._draw_button_custom(events, "QUIT", WIDTH//2 - int(WIDTH * 0.03), HEIGHT - int(HEIGHT * 0.04), int(WIDTH * 0.06), int(HEIGHT * 0.03), lambda: (GAME._stop_hosting(), setattr(GAME, 'state', 'menu')))

    def draw_waiting_lobby(self, events, GAME):
        self.game = GAME
        SCREEN.fill(self.bg_color)
        title = pygame.font.Font(FONT, 50).render("CONNECTED", True, 'green')
        SCREEN.blit(title, (WIDTH//2 - title.get_width()//2, int(HEIGHT * 0.15)))
        info = pygame.font.Font(FONT, 25).render("Wachten op host om te starten...", True, (200, 200, 200))
        SCREEN.blit(info, (WIDTH//2 - info.get_width()//2, int(HEIGHT * 0.21)))
        if self.client_list:
            y = int(HEIGHT * 0.29)
            for name, pid in self.client_list:
                p_text = pygame.font.Font(FONT, 28).render(f"[P{pid}] {name}", True, 'white')
                SCREEN.blit(p_text, (WIDTH//2 - p_text.get_width()//2, y))
                y += int(HEIGHT * 0.04)
        def dc():
            GAME._disconnect()
        self._draw_button_custom(events, "DISCONNECT", WIDTH//2 - int(WIDTH * 0.04), HEIGHT - int(HEIGHT * 0.08), int(WIDTH * 0.08), int(HEIGHT * 0.04), dc)

    #  Settings 

    def draw_settings(self, events, GAME):
        self.game = GAME
        SCREEN.fill(self.bg_color)
        
        high_label = "[HIGH RES]" if self.game.resolution == "high" else "HIGH RES"
        low_label  = "[LOW RES]"  if self.game.resolution == "low"  else "LOW RES"
        
        Res_high = Button(int(-HEIGHT * 0.09), int(WIDTH * 0.1), int(HEIGHT * 0.06), high_label, 25, "black", "white", "white", "black", self.game, "settings", True, int(-WIDTH * 0.11), "res_high")
        Res_low = Button(int(-HEIGHT * 0.09), int(WIDTH * 0.1), int(HEIGHT * 0.06), low_label, 25, "black", "white", "white", "black", self.game, "settings", True, int(WIDTH * 0.11), "res_low")
        
        tuto_label = "[TUTORIAL]" if self.game.bilal.flags["general"] == True else "TUTORIAL"
        
        Tutorial_button = Button(int(HEIGHT * 0.18), int(WIDTH * 0.13), int(HEIGHT * 0.06), tuto_label, 25, "black", "white", "white", "black", self.game, "settings", True, 0, "tutorial")
        silly_label = "[SILLY MODE]" if self.silly_mode else "SILLY MODE"
        Silly_button = Button(int(HEIGHT * 0.25), int(WIDTH * 0.13), int(HEIGHT * 0.06), silly_label, 25, "black", "white", "white", "black", self.game, "settings", True, 0, "silly")
        volume_slider = self.get_volume_slider(self.game)
        volume_slider.draw(events)
        sfx_slider = self.get_sfx_volume_slider(self.game)
        sfx_slider.draw(events)

        back_target = getattr(GAME, '_settings_return', 'menu')
        def go_back():
            GAME.state = back_target
            if back_target == "game":
                pygame.mouse.set_visible(False)
                pygame.event.set_grab(True)
                pygame.mixer.unpause()
            elif back_target == "paused":
                pygame.mouse.set_visible(True)
                pygame.event.set_grab(False)
            else:
                pygame.mouse.set_visible(True)
                pygame.event.set_grab(False)
            GAME._settings_return = "menu"
        self._draw_main_button(events, "BACK", HEIGHT - int(HEIGHT * 0.09), int(WIDTH * 0.11), go_back, font_size=34)
        
        Tutorial_button.draw_button(events)
        Res_high.draw_button(events)
        Res_low.draw_button(events)
        Silly_button.draw_button(events)

    def draw_credits(self, events, GAME):
        self.game = GAME
        SCREEN.fill(self.bg_color)

        y = self.credits_height
        x = WIDTH // 4
        white = "white"

        self.title_font = pygame.font.Font(SILLY_FONT if self.silly_mode else FONT, int(HEIGHT * 0.29))
        self.title_font.set_bold(True)
        title_surf = self.title_font.render("GUNK", True, white)
        SCREEN.blit(title_surf, (WIDTH // 2 - title_surf.get_width() // 2, y))

        self.text_font = pygame.font.Font(SILLY_FONT if self.silly_mode else FONT, int(HEIGHT * 0.04))
        lines = [
            ("Developed by:", int(HEIGHT * 0.27)),
            ("Kobe Motmans", int(HEIGHT * 0.31)),
            ("Andreas Meuwissen", int(HEIGHT * 0.35)),
            ("Ruben Verreth", int(HEIGHT * 0.39)),
            ("Music by:", int(HEIGHT * 0.47)),
            ("Rube van der Wielen", int(HEIGHT * 0.50)),
            ("Special thanks to:", int(HEIGHT * 0.58)),
            ("Andrei", int(HEIGHT * 0.62)),
            ("Ahmed", int(HEIGHT * 0.66)),
            ("Ruben", int(HEIGHT * 0.70)),
            ("Jan", int(HEIGHT * 0.74)),
            ("Bilal", int(HEIGHT * 0.78)),
        ]

        for text, offset in lines:
            SCREEN.blit(
                self.text_font.render(text, False, white),
                (x, y + offset)
            )

        self.credits_height -= 2
        if self.credits_height < -int(HEIGHT * 0.87):
            self.credits_height = HEIGHT

        Menu_button = Button(
            self.credits_height + int(HEIGHT * 0.52),
            int(WIDTH * 0.07),
            int(HEIGHT * 0.06),
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
        
    def draw_UI(self, events):
        self.fps_font = pygame.font.Font(FONT, 20)
        self.fps_font.set_bold(True)
        self.hp_font = pygame.font.Font(FONT, int(HEIGHT * 0.08))
        self.hp_font.set_bold(True)
        SCREEN.blit(self.fps_font.render(f"{round(self.game.clock.get_fps())}", True, 'green'),(int(WIDTH * 0.01), int(HEIGHT * 0.02)))
        SCREEN.blit(self.hp_font.render(f"{round(self.game.player.health)}/{START_HEALTH}", True, 'red'),(WIDTH - int(WIDTH * 0.15), int(HEIGHT * 0.02)))
        SCREEN.blit(self.hp_font.render(f"{round(self.game.player.ammo)}/{AMMO_CAP}", True, 'grey'),(int(WIDTH * 0.01), HEIGHT - int(HEIGHT * 0.1)))
        if getattr(self.game, 'elevator_waiting', False):
            warn_font = pygame.font.Font(FONT, 36)
            elev_ready = getattr(self.game, 'elevator_ready', False)
            wait_timer = getattr(self.game, 'elevator_wait_timer', 0)
            player_near = getattr(self.game, 'player_near_exit', False)
            if elev_ready and wait_timer > 0:
                msg = f"Lift vertrekt in {wait_timer//60 + 1}..."
                color = (255, 200, 0)
            elif not player_near:
                msg = "GA NAAR DE LIFT!"
                color = (255, 80, 80)
            else:
                msg = "Wacht op teamgenoten..."
                color = (200, 200, 80)
            warn_surf = warn_font.render(msg, True, color)
            SCREEN.blit(warn_surf, (WIDTH//2 - warn_surf.get_width()//2, HEIGHT//2 - int(HEIGHT * 0.19)))
        if getattr(self.game, 'global_paused', False):
            s = pygame.Surface((WIDTH, HEIGHT))
            s.set_alpha(120)
            s.fill((200, 200, 200))
            SCREEN.blit(s, (0, 0))
            paused_by = getattr(self.game, 'paused_by', "")
            pause_font = pygame.font.Font(FONT, 44)
            pause_text = f"{paused_by} paused. Waiting..." if paused_by else "Paused. Waiting..."
            pause_surf = pause_font.render(pause_text, True, 'white')
            SCREEN.blit(pause_surf, (WIDTH//2 - pause_surf.get_width()//2, HEIGHT//2 - pause_surf.get_height()//2))
    def draw_paused_screen(self, events, GAME):
        self.game = GAME
        c = WIDTH//2
        def resume():
            pygame.mouse.set_visible(False)
            pygame.event.set_grab(True)
            GAME.state = "game"
            pygame.mixer.unpause()
            if GAME.multiplayer and GAME.is_host:
                GAME.global_paused = False
                GAME.paused_by = ""
        self._draw_main_button(events, "RESUME", HEIGHT//2 - int(HEIGHT * 0.1), int(WIDTH * 0.11), resume, font_size=34)

        def open_settings():
            GAME._settings_return = "paused"
            GAME.state = "settings"
        self._draw_main_button(events, "SETTINGS", HEIGHT//2 - int(HEIGHT * 0.02), int(WIDTH * 0.11), open_settings, font_size=34)

        def go_menu():
            pygame.mixer.stop()
            if GAME.multiplayer:
                if GAME.is_host:
                    GAME._stop_hosting()
                else:
                    GAME._disconnect()
            else:
                GAME.state = "menu"
        self._draw_main_button(events, "MENU", HEIGHT//2 + int(HEIGHT * 0.06), int(WIDTH * 0.11), go_menu, font_size=34)
    def draw_elevator(self, events, player):
        game = getattr(self, 'game', None)
        if game is None:
            return
        is_client = game.multiplayer and not game.is_host
        self.elev_color = "pink" if self.silly_mode else (20,20,20)
        if player.door_pos <= WIDTH/2:
            pygame.draw.rect(SCREEN,self.elev_color,[0,0,player.door_pos,HEIGHT])
            pygame.draw.rect(SCREEN,self.elev_color,[WIDTH-player.door_pos,0,player.door_pos,HEIGHT])
            player.door_pos += ELEV_SPEED

        elif player.door_pos <= WIDTH/2 + ELEV_SPEED:
            if M.map_level < MAX_LEVEL:
                SCREEN.fill(self.elev_color)
                if self.lift_time == 0:
                    if not is_client:
                        game.level_up()
                        game.player.door_pos += ELEV_SPEED
                        s = pygame.mixer.Sound("assets/silly/toot_toot.ogg" if self.silly_mode else "assets/elev_ding.ogg")
                        s.set_volume(SFX_VOLUME)
                        s.play()
                self.lift_time -= 1
            else:
                if not is_client:
                    pygame.mixer.stop()
                    game.player.door_pos += ELEV_SPEED
                    game.escaped = True
                    s = pygame.mixer.Sound("assets/silly/Banjo.ogg" if self.silly_mode else "assets/Motivator.ogg")
                    s.set_volume(SFX_VOLUME)
                    s.play()
                    pygame.mouse.set_visible(True)
                    pygame.event.set_grab(False)
                else:
                    player.door_pos += ELEV_SPEED

        elif WIDTH/2 + ELEV_SPEED <= player.door_pos < WIDTH:
            pygame.draw.rect(SCREEN,self.elev_color,[0,0,WIDTH-player.door_pos,HEIGHT])
            pygame.draw.rect(SCREEN,self.elev_color,[player.door_pos,0,WIDTH-player.door_pos,HEIGHT])
            player.door_pos += ELEV_SPEED

        elif player.door_pos >= WIDTH:
            if not game.escaped:
                player.door_pos = 0
            self.lift_time = ELEV_TIME
    def draw_dead_screen(self,events,GAME):
        self.game = GAME
        self.title_font = pygame.font.Font(SILLY_FONT if self.silly_mode else FONT, int(HEIGHT * 0.19))
        self.title_font.set_bold(True)
        SCREEN.blit(SCREEN_DEAD, (0,0)) if not self.silly_mode else SCREEN.blit(SCREEN_DEAD_SILLY, (0,0))
        self.score_font = pygame.font.Font(SILLY_FONT if self.silly_mode else FONT, int(HEIGHT * 0.08))
        self.score_font.set_bold(True)
        Menu_button = Button(int(HEIGHT * 0.1), int(WIDTH * 0.07), int(HEIGHT * 0.06), "MENU", 35, "black", 'white', 'white', 'black', self.game, "menu", True)
        Menu_button.draw_button(events)
        score_surf = self.score_font.render(f"Score:{self.game.player.score}", True, 'black')
        SCREEN.blit(score_surf, (WIDTH//2 - score_surf.get_width()//2, HEIGHT//2 - int(HEIGHT * 0.04)))
        title_surf = self.title_font.render("GAME OVER", True, 'black')
        SCREEN.blit(title_surf, (WIDTH//2 - title_surf.get_width()//2, HEIGHT//3 - int(HEIGHT * 0.05)))
        
    def draw_escaped_screen(self,events,GAME):
        self.game = GAME
        self.endscreen_font = pygame.font.Font(SILLY_FONT if self.silly_mode else FONT, int(HEIGHT * 0.15))
        self.endscreen_font.set_bold(True)
        self.score_font = pygame.font.Font(SILLY_FONT if self.silly_mode else FONT, int(HEIGHT * 0.08))
        self.score_font.set_bold(True)
        SCREEN.blit(VICTORY_SCREEN, (0,0))
        pygame.mouse.set_visible(True)
        s1 = self.endscreen_font.render("SUCCESFUL", True, 'white')
        s2 = self.endscreen_font.render("ESKAPE", True, 'white')
        score_surf = self.score_font.render(f"Score:{self.game.player.score}", True, 'white')
        SCREEN.blit(s1, (WIDTH//2 - s1.get_width()//2, HEIGHT//2 - int(HEIGHT * 0.45)))
        SCREEN.blit(s2, (WIDTH//2 - s2.get_width()//2, HEIGHT//2 - int(HEIGHT * 0.27)))
        SCREEN.blit(score_surf, (WIDTH//2 - score_surf.get_width()//2, HEIGHT//2 + int(HEIGHT * 0.01)))
        Menu_button = Button(int(HEIGHT * 0.15), int(WIDTH * 0.07), int(HEIGHT * 0.06), "MENU", 35, "black", 'white', 'white', 'black', self.game, "menu", True)
        Menu_button.draw_button(events)
    def get_volume_slider(self, GAME):
        if self.volume_slider is None:
            self.volume_slider = Slider(
                y_pos=int(HEIGHT * 0.03), width=int(WIDTH * 0.21), height=int(HEIGHT * 0.01),
                min_val=0.0, max_val=1.0, initial_val=0.5,
                label="MUSIC VOLUME", GAME=GAME,
                on_change=lambda val: GAME.main_music.set_volume(val)
                )
        return self.volume_slider

    def get_sfx_volume_slider(self, GAME):
        if self.sfx_volume_slider is None:
            def on_sfx_change(val):
                GAME.sfx_volume = val
                GAME.update_sfx_volume()
            self.sfx_volume_slider = Slider(
                y_pos=int(HEIGHT * 0.10), width=int(WIDTH * 0.21), height=int(HEIGHT * 0.01),
                min_val=0.0, max_val=1.0, initial_val=getattr(GAME, 'sfx_volume', 0.3),
                label="SFX VOLUME", GAME=GAME,
                on_change=on_sfx_change
                )
        return self.sfx_volume_slider

Menu_inst = Menu((70,70,70))

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
        self.font = pygame.font.Font(SILLY_FONT if GAME.Menu.silly_mode else FONT,self.text_size) 
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
                        self.GAME.bilal.flags["general"] = not self.GAME.bilal.flags["general"]
                    elif self.function == "silly":
                        self.GAME.Menu.silly_mode = not self.GAME.Menu.silly_mode
                    if self.state_change == "reset":
                        self.GAME.reset_game()
                    elif self.state_change == "Stop":
                        pygame.mixer.stop()
                        self.GAME.running = False
                        self.GAME.state = None
                    elif self.state_change == "game":
                        pygame.mixer.unpause()
                        self.GAME.state = "game"
                    elif self.state_change == "menu":
                        pygame.mixer.stop()
                    
        color = self.button_hov_color if hovering else self.button_color
        text_color = self.text_hov_color if hovering else self.text_color
        
        pygame.draw.rect(SCREEN,color,[WIDTH/2-self.w/2+self.x_pos,HEIGHT/2-self.h/2+self.y_pos,self.w,self.h])
        SCREEN.blit(self.font.render(self.text, True, text_color),(WIDTH/2-self.w/3+self.x_pos,HEIGHT/2-self.text_size/2+self.y_pos))

class Slider:
    def __init__(self, y_pos, width, height, min_val, max_val, initial_val, label, GAME, on_change=None):
        self.y_pos = y_pos
        self.w = width
        self.h = height
        self.min_val = min_val
        self.max_val = max_val
        self.value = initial_val
        self.label = label
        self.GAME = GAME
        self.dragging = False
        self.on_change = on_change

        self.track_x = WIDTH // 2 - width // 2
        self.track_y = HEIGHT // 2 + y_pos
        self.handle_r = height


    def get_handle_x(self):
        ratio = (self.value - self.min_val) / (self.max_val - self.min_val)
        return self.track_x + ratio * self.w

    def draw(self, events):
        self.font = pygame.font.Font(SILLY_FONT if self.GAME.Menu.silly_mode else FONT, int(HEIGHT * 0.02))
        mouse = pygame.mouse.get_pos()
        mouse_buttons = pygame.mouse.get_pressed()

        handle_x = self.get_handle_x()

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
            if self.on_change:
                self.on_change(self.value)

        pygame.draw.rect(SCREEN, 'white', [self.track_x, self.track_y - 4, self.w, 8], border_radius=4)

        filled_w = self.get_handle_x() - self.track_x
        pygame.draw.rect(SCREEN, (0, 200, 255), [self.track_x, self.track_y - 4, filled_w, 8], border_radius=4)

        handle_x = self.get_handle_x()
        pygame.draw.circle(SCREEN, (0, 200, 255) if self.dragging else 'white', (int(handle_x), int(self.track_y)), self.handle_r)

        label_surf = self.font.render(f"{self.label}: {int(self.value * 100)}%", True, 'white')
        SCREEN.blit(label_surf, (self.track_x, self.track_y - int(HEIGHT * 0.04)))


# ---- Het grootste deel hiervan is AI code, eerder flavour en tutorial dan functionele game code-----
class Tekstballon:
    def __init__(self, text, y_pos, x_pos, GAME, max_width=280, padding=10,):
        self.text = text
        self.y_pos = y_pos
        self.x_pos = x_pos
        self.max_width = max_width
        self.padding = padding
        self.font = pygame.font.Font(SILLY_FONT if GAME.Menu.silly_mode else FONT, 20)
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

        for i, line in enumerate(raw_lines):
            SCREEN.blit(
                self.font.render(line, False, (0, 0, 0)),
                (x + self.padding, y + self.padding + i * line_height)
            )

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
    def __init__(self, GAME):
        self.queue = deque()
        self.current = None
        self.timer = 0
        self.Game = GAME

        self.interrupt_msg = None
        self.interrupt_timer = 0

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
            Tekstballon(text, HEIGHT - int(HEIGHT * 0.39), int(WIDTH * 0.01), self.Game).draw()
            SCREEN.blit(BILAL, (0, HEIGHT - int(HEIGHT * 0.29)))

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
                "Door Monster Energy te drinken krijg je twee HP terug!", 200
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
