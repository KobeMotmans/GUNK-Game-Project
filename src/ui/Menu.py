import pygame
import tkinter as tk
from tkinter import filedialog
from ..core.config import HEIGHT, WIDTH, SCREEN, set_resolution, FONT, BILAL, VICTORY_SCREEN, SCREEN_DEAD, START_HEALTH, AMMO_CAP, ELEV_SPEED, MAX_LEVEL, ELEV_TIME, SILLY_FONT, DEFAULT_PORT, SFX_VOLUME, MENU_BG
from ..core.paths import asset_path, resolve_asset, pack_config, list_packs, set_pack, TEXTURE_PACK
from collections import deque
from ..core.map_loader import M
from ..assets.skin_manager import SkinManager
from ..network.network import NetworkClient
class Menu:
    def __init__(self):
        self.bg_color = MENU_BG
        self.credits_height = HEIGHT
        self.volume_slider = None
        self.sfx_volume_slider = None
        
        self.lift_time = 120
        self.credits_height = HEIGHT
        self.lift_time = ELEV_TIME
        self.loading_progress = 0

        # Multiplayer input fields + disk cache
        cfg = NetworkClient.load_config()
        self.mp_name_input = cfg.get("last_name", "")
        self.mp_host_port = "5555"
        self.mp_join_ip = cfg.get("last_ip", "127.0.0.1")
        self.mp_join_port = cfg.get("last_port", "5555")
        self.mp_skin_id = cfg.get("last_skin_id", 0)
        self.input_focus = None
        self.lobby_status = ""
        self.client_list = []
        self.waiting_text = "Verbinden..."
        self.mp_status = ""
        self._skin_thumbnails = {}
        self._skin_page = 0
        self.mp_skin_search = ""
        self.mp_skin_upload_name = ""
        self._upload_status = None

    def draw_loading_screen(self, progress=None):
        SCREEN.fill(self.bg_color)
        loading_font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(HEIGHT * 0.1))
        loading_font.set_bold(True)
        load_surf = loading_font.render("Loading...", True, 'white')
        SCREEN.blit(load_surf, (WIDTH // 2 - load_surf.get_width() // 2, HEIGHT - int(HEIGHT * 0.29)))

        title_font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(HEIGHT * 0.29))
        title_font.set_bold(True)
        title_surf = title_font.render("GUNK", True, 'white')
        SCREEN.blit(title_surf, (WIDTH // 2 - title_surf.get_width() // 2, HEIGHT // 2 - title_surf.get_height() // 2))

        bar_width = int(WIDTH * 0.31)
        bar_height = int(HEIGHT * 0.03)
        bar_x = WIDTH // 2 - bar_width // 2
        bar_y = HEIGHT - int(HEIGHT * 0.15)

        pygame.draw.rect(SCREEN, (80, 80, 80), (bar_x, bar_y, bar_width, bar_height))

        if progress is not None:
            self.loading_progress = progress
        progress_width = bar_width * self.loading_progress
        pygame.draw.rect(SCREEN, (0, 200, 0), (bar_x, bar_y, progress_width, bar_height))
        if progress is None:
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
        font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), font_size)
        surf = font.render(text, True, 'white')
        SCREEN.blit(surf, (x + w//2 - surf.get_width()//2, y_pos + h//2 - surf.get_height()//2))
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if rect.collidepoint(ev.pos) and action:
                    action()
                    return True
        return False

    def draw_main_menu(self, events, GAME):
        self.game = GAME
        SCREEN.fill(self.bg_color)
        title_font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(HEIGHT * 0.29))
        title_font.set_bold(True)
        title_surf = title_font.render("GUNK", True, 'white')
        SCREEN.blit(title_surf, (WIDTH // 2 - title_surf.get_width() // 2, int(HEIGHT * 0.08)))

        c = WIDTH//2
        btn_w = int(WIDTH * 0.12)
        gap = int(WIDTH * 0.03)
        self._draw_main_button(events, "SOLO", int(HEIGHT * 0.38), btn_w, lambda: GAME.reset_game(), font_size=36, x=c - btn_w - gap//2)
        self._draw_main_button(events, "MULTIPLAYER", int(HEIGHT * 0.38), btn_w, lambda: setattr(GAME, 'state', 'multiplayer_menu'), font_size=36, x=c + gap//2)
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

        join_font = pygame.font.Font(FONT, 36)
        join_label = join_font.render("JOIN SERVER", True, 'white')
        SCREEN.blit(join_label, (WIDTH//2 - join_label.get_width()//2, int(HEIGHT * 0.04)))

        info_text = "Start de server apart: python run_server.py"
        info = pygame.font.Font(FONT, 16).render(info_text, True, (150, 150, 150))
        SCREEN.blit(info, (WIDTH//2 - info.get_width()//2, int(HEIGHT * 0.08)))

        name_label = pygame.font.Font(FONT, 22).render("JOUW NAAM", True, (200, 200, 200))
        SCREEN.blit(name_label, (WIDTH//2 - name_label.get_width()//2, int(HEIGHT * 0.13)))
        self.mp_name_input = self._draw_text_input(events, "", self.mp_name_input, WIDTH//2 - int(WIDTH * 0.06), int(HEIGHT * 0.16), int(WIDTH * 0.125), field_id="mp_name")

        ip_label = pygame.font.Font(FONT, 20).render("SERVER IP", True, (200, 200, 200))
        SCREEN.blit(ip_label, (WIDTH//2 - ip_label.get_width()//2, int(HEIGHT * 0.22)))
        self.mp_join_ip = self._draw_text_input(events, "", self.mp_join_ip, WIDTH//2 - int(WIDTH * 0.06), int(HEIGHT * 0.25), int(WIDTH * 0.125), field_id="mp_join_ip")

        port_label = pygame.font.Font(FONT, 20).render("POORT", True, (200, 200, 200))
        SCREEN.blit(port_label, (WIDTH//2 - port_label.get_width()//2, int(HEIGHT * 0.31)))
        self.mp_join_port = self._draw_text_input(events, "", self.mp_join_port, WIDTH//2 - int(WIDTH * 0.06), int(HEIGHT * 0.34), int(WIDTH * 0.125), field_id="mp_join_port", numeric=True)

        def do_connect():
            name = self.mp_name_input.strip() or "Player"
            ip = self.mp_join_ip.strip() or "127.0.0.1"
            try:
                port = int(self.mp_join_port) if self.mp_join_port else DEFAULT_PORT
            except ValueError:
                port = DEFAULT_PORT
            GAME._do_connect(ip, port, name)
        self._draw_button_custom(events, "JOIN GAME", WIDTH//2 - int(WIDTH * 0.05), int(HEIGHT * 0.40), int(WIDTH * 0.1), int(HEIGHT * 0.05), do_connect)

        if self.mp_status:
            color = (0, 200, 0) if "gelukt" in self.mp_status else (200, 0, 0)
            status = pygame.font.Font(FONT, 22).render(self.mp_status, True, color)
            SCREEN.blit(status, (WIDTH//2 - status.get_width()//2, int(HEIGHT * 0.48)))

        self._draw_button_custom(events, "BACK", WIDTH//2 - int(WIDTH * 0.03), HEIGHT - int(HEIGHT * 0.08), int(WIDTH * 0.06), int(HEIGHT * 0.03), lambda: setattr(GAME, 'state', 'menu'))

    def draw_waiting_lobby(self, events, GAME):
        self.game = GAME
        SCREEN.fill(self.bg_color)
        title = pygame.font.Font(FONT, 50).render("LOBBY", True, 'white')
        SCREEN.blit(title, (WIDTH//2 - title.get_width()//2, int(HEIGHT * 0.08)))

        mouse = pygame.mouse.get_pos()

        # ── Left column: player list ──────────────────────────────
        left_x = int(WIDTH * 0.04)
        left_cx = int(WIDTH * 0.20)
        y_left = int(HEIGHT * 0.15)
        players = self.client_list if self.client_list else []
        thumb_size = 36
        for pd in players:
            pid = pd["pid"] if isinstance(pd, dict) else pd[1]
            name = pd["name"] if isinstance(pd, dict) else pd[0]
            skin_id = pd.get("skin_id", 0) if isinstance(pd, dict) else (pd[2] if len(pd) > 2 else 0)
            color = (0, 200, 255) if pid == GAME.player_id else (255, 255, 255)
            if skin_id not in self._skin_thumbnails or self._skin_thumbnails[skin_id].get_width() != thumb_size:
                self._skin_thumbnails[skin_id] = SkinManager.create_thumbnail(skin_id, (thumb_size, thumb_size))
            SCREEN.blit(self._skin_thumbnails[skin_id], (left_x, y_left - 4))
            p_text = pygame.font.Font(FONT, 26).render(f"[P{pid}] {name}", True, color)
            SCREEN.blit(p_text, (left_x + thumb_size + 10, y_left))
            y_left += int(HEIGHT * 0.045)
        if not players:
            wait = pygame.font.Font(FONT, 22).render("Wachten op spelers...", True, (150, 150, 150))
            SCREEN.blit(wait, (left_cx - wait.get_width()//2, y_left))

        # ── Right column: skin selector ───────────────────────────
        right_cx = int(WIDTH * 0.66)
        y_right = int(HEIGHT * 0.15)

        sel_label = pygame.font.Font(FONT, 22).render("KIEZEN", True, (200, 200, 200))
        SCREEN.blit(sel_label, (right_cx - sel_label.get_width()//2, y_right))
        y_right += 28

        avail = SkinManager.get_available_skins()
        builtin = [s for s in avail if s.get("type") == "builtin"]
        custom = [s for s in avail if s.get("type") == "custom"]
        t_size_b = int(min(WIDTH * 0.04, HEIGHT * 0.055))
        gap_b = int(t_size_b * 0.25)

        # ── Built-in skins row ─────────────────────────────────────
        total_bw = len(builtin) * (t_size_b + gap_b)
        start_bx = right_cx - total_bw//2 + gap_b//2
        self._skin_builtin_rects = []
        for si, info in enumerate(builtin):
            sid = info["id"]
            x = start_bx + si * (t_size_b + gap_b)
            rect = pygame.Rect(x, y_right, t_size_b, t_size_b)
            self._skin_builtin_rects.append((sid, rect))
            if sid not in self._skin_thumbnails or self._skin_thumbnails[sid].get_width() != t_size_b:
                self._skin_thumbnails[sid] = SkinManager.create_thumbnail(sid, (t_size_b, t_size_b))
            SCREEN.blit(self._skin_thumbnails[sid], (x, y_right))
            border_color = (0, 200, 255) if sid == GAME.skin_id else (60, 60, 60)
            pygame.draw.rect(SCREEN, border_color, rect, 3, border_radius=4)
            name_font = pygame.font.Font(FONT, 13)
            name_surf = name_font.render(info.get("name", f"S{sid}"), True, (150, 150, 150))
            SCREEN.blit(name_surf, (x + t_size_b//2 - name_surf.get_width()//2, y_right + t_size_b + 2))
        y_right += t_size_b + 28

        # ── Upload section (always visible) ─────────────────────────
        upload_font = pygame.font.Font(FONT, 16)
        upload_label = upload_font.render("NIEUWE SKIN", True, (200, 200, 200))
        SCREEN.blit(upload_label, (right_cx - upload_label.get_width()//2, y_right))
        y_right += 22
        name_w = int(WIDTH * 0.08)
        name_x = right_cx - name_w - int(WIDTH * 0.02)
        self.mp_skin_upload_name = self._draw_text_input(events, "",
            self.mp_skin_upload_name, name_x, y_right, name_w,
            height=26, field_id="mp_skin_upload_name")
        btn_w = int(WIDTH * 0.08)
        btn_x = right_cx + int(WIDTH * 0.02)
        up_rect = pygame.Rect(btn_x, y_right, btn_w, 26)
        hover = up_rect.collidepoint(mouse)
        pygame.draw.rect(SCREEN, (80, 120, 80) if hover else (60, 90, 60), up_rect, border_radius=4)
        up_surf = upload_font.render("UPLOAD", True, (200, 255, 200))
        SCREEN.blit(up_surf, (btn_x + btn_w//2 - up_surf.get_width()//2, y_right + 5))
        self._skin_upload_rect = up_rect
        y_right += 32

        if self._upload_status:
            col = (0, 200, 0) if "gelukt" in self._upload_status.lower() else (200, 100, 0)
            st = pygame.font.Font(FONT, 15).render(self._upload_status, True, col)
            SCREEN.blit(st, (right_cx - st.get_width()//2, y_right))
            y_right += 20

        # ── Custom skins browser ────────────────────────────────────
        self._skin_custom_rects = []
        self._skin_custom_info = []
        if custom:
            cus_label = pygame.font.Font(FONT, 18).render("CUSTOM", True, (160, 140, 255))
            SCREEN.blit(cus_label, (right_cx - cus_label.get_width()//2, y_right))
            y_right += 24

            search_w = int(WIDTH * 0.12)
            search_x = right_cx - search_w//2
            self.mp_skin_search = self._draw_text_input(events, "",
                getattr(self, 'mp_skin_search', ""), search_x, y_right, search_w,
                height=26, field_id="mp_skin_search")
            y_right += 32

            filter_text = getattr(self, 'mp_skin_search', "").lower()
            filtered = [s for s in custom if filter_text in s.get("name", "").lower()]

            per_page = 4
            total_pages = max(1, (len(filtered) + per_page - 1) // per_page)
            page = getattr(self, '_skin_page', 0)
            if page >= total_pages:
                page = total_pages - 1
            self._skin_page = page

            t_size_c = int(WIDTH * 0.06)
            gap_c = int(t_size_c * 0.25)
            row_start = page * per_page
            row_end = min(row_start + per_page, len(filtered))
            row_items = filtered[row_start:row_end]

            row_w = len(row_items) * (t_size_c + gap_c)
            start_cx = right_cx - row_w//2 + gap_c//2
            for si, info in enumerate(row_items):
                sid = info["id"]
                x = start_cx + si * (t_size_c + gap_c)
                rect = pygame.Rect(x, y_right, t_size_c, t_size_c)
                self._skin_custom_rects.append((sid, rect))
                self._skin_custom_info.append(info)
                if sid not in self._skin_thumbnails or self._skin_thumbnails[sid].get_width() != t_size_c:
                    self._skin_thumbnails[sid] = SkinManager.create_thumbnail(sid, (t_size_c, t_size_c))
                SCREEN.blit(self._skin_thumbnails[sid], (x, y_right))
                border_color = (0, 200, 255) if sid == GAME.skin_id else (40, 40, 50)
                pygame.draw.rect(SCREEN, border_color, rect, 2, border_radius=4)
                name_font = pygame.font.Font(FONT, 12)
                label = info.get("name", f"S{sid}")
                if len(label) > 14:
                    label = label[:13] + "..."
                name_surf = name_font.render(label, True, (160, 160, 160))
                SCREEN.blit(name_surf, (x + t_size_c//2 - name_surf.get_width()//2, y_right + t_size_c + 2))

            y_right += t_size_c + 22

            # Pagination controls
            self._skin_prev_rect = None
            self._skin_next_rect = None
            if total_pages > 1:
                arr_font = pygame.font.Font(FONT, 20)
                prev_surf = arr_font.render("<", True, (200, 200, 200))
                prev_rect = pygame.Rect(right_cx - int(WIDTH * 0.08), y_right - 6,
                                        prev_surf.get_width() + 8, prev_surf.get_height() + 4)
                pygame.draw.rect(SCREEN, (70, 70, 70) if page > 0 else (40, 40, 40), prev_rect, border_radius=4)
                SCREEN.blit(prev_surf, (prev_rect.x + 4, prev_rect.y + 2))
                self._skin_prev_rect = prev_rect
                self._skin_prev_page = page > 0

                page_surf = arr_font.render(f"{page + 1}/{total_pages}", True, (180, 180, 180))
                SCREEN.blit(page_surf, (right_cx - page_surf.get_width()//2, y_right - 4))

                next_surf = arr_font.render(">", True, (200, 200, 200))
                next_rect = pygame.Rect(right_cx + int(WIDTH * 0.06), y_right - 6,
                                        next_surf.get_width() + 8, next_surf.get_height() + 4)
                pygame.draw.rect(SCREEN, (70, 70, 70) if page < total_pages - 1 else (40, 40, 40),
                                 next_rect, border_radius=4)
                SCREEN.blit(next_surf, (next_rect.x + 4, next_rect.y + 2))
                self._skin_next_rect = next_rect
                self._skin_next_page = page < total_pages - 1

        # ── Click handling ─────────────────────────────────────────
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for sid, rect in self._skin_builtin_rects:
                    if rect.collidepoint(mouse):
                        self._select_skin(GAME, sid)

                if getattr(self, '_skin_upload_rect', None) and self._skin_upload_rect.collidepoint(mouse):
                    skin_name = self.mp_skin_upload_name.strip()
                    if not skin_name:
                        self._upload_status = "Vul een naam in"
                    else:
                        root = tk.Tk()
                        root.withdraw()
                        filepath = filedialog.askopenfilename(
                            title="Selecteer een afbeelding",
                            filetypes=[("Afbeeldingen", "*.png *.jpg *.jpeg *.gif *.bmp"), ("Alle bestanden", "*.*")]
                        )
                        root.destroy()
                        if filepath:
                            uploader = GAME.player_name
                            self._upload_status = "Bezig met uploaden..."
                            ok, msg, *rest = GAME.network_client.upload_skin(skin_name, uploader, filepath)
                            self._upload_status = msg
                            if ok:
                                self.mp_skin_upload_name = ""
                                sid = rest[0] if rest else None
                                if sid is not None:
                                    SkinManager.download_skin(sid)
                                    self._select_skin(GAME, sid)

                if custom:
                    for sid, rect in self._skin_custom_rects:
                        if rect.collidepoint(mouse):
                            self._select_skin(GAME, sid)

                    if self._skin_prev_rect and self._skin_prev_rect.collidepoint(mouse) and self._skin_prev_page:
                        self._skin_page -= 1
                    if self._skin_next_rect and self._skin_next_rect.collidepoint(mouse) and self._skin_next_page:
                        self._skin_page += 1

        def dc():
            GAME._disconnect()

        def start_multi_game():
            GAME._primary_start_game()
        if players:
            self._draw_button_custom(events, "START GAME", WIDTH//2 - int(WIDTH * 0.05),
                HEIGHT - int(HEIGHT * 0.13), int(WIDTH * 0.1), int(HEIGHT * 0.05), start_multi_game)
        self._draw_button_custom(events, "DISCONNECT", WIDTH//2 - int(WIDTH * 0.04),
            HEIGHT - int(HEIGHT * 0.07), int(WIDTH * 0.08), int(HEIGHT * 0.03), dc)

    def _select_skin(self, GAME, skin_id):
        GAME.skin_id = skin_id
        self.mp_skin_id = skin_id
        if GAME.network_client and GAME.network_client.connected:
            GAME.network_client.send({"type": "select_skin", "skin_id": skin_id})
            NetworkClient._save_config(GAME.player_name,
                GAME.network_client.server_addr[0],
                GAME.network_client.server_addr[1], skin_id)

    # ── Settings ──────────────────────────────────────────────

    def _draw_section_header(self, text, y, color=(160, 160, 160)):
        font = pygame.font.Font(FONT, 24)
        surf = font.render(text, True, color)
        cx = WIDTH // 2
        left_margin = int(WIDTH * 0.08)
        right_margin = WIDTH - left_margin
        mid_y = y + surf.get_height() // 2
        gap = 14
        lx = cx - surf.get_width() // 2 - gap
        rx = cx + surf.get_width() // 2 + gap
        if lx > left_margin:
            pygame.draw.line(SCREEN, color, (left_margin, mid_y), (lx, mid_y), 2)
        if rx < right_margin:
            pygame.draw.line(SCREEN, color, (rx, mid_y), (right_margin, mid_y), 2)
        SCREEN.blit(surf, (cx - surf.get_width() // 2, y))

    def draw_settings(self, events, GAME):
        self.game = GAME
        SCREEN.fill(self.bg_color)
        c = WIDTH // 2

        # ── Title ─────────────────────────────────────────────
        title_font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(HEIGHT * 0.07))
        title_font.set_bold(True)
        title_surf = title_font.render("SETTINGS", True, 'white')
        SCREEN.blit(title_surf, (c - title_surf.get_width() // 2, int(HEIGHT * 0.04)))

        LABEL_FONT_SIZE = 20
        btn_w = int(WIDTH * 0.09)
        btn_h = int(HEIGHT * 0.05)
        gap = int(WIDTH * 0.02)

        # ── VIDEO ────────────────────────────────────────────
        self._draw_section_header("VIDEO", int(HEIGHT * 0.14))

        hi_active = self.game.resolution == "high"
        lo_active = self.game.resolution == "low"
        res_y = int(HEIGHT * 0.21)
        Res_high = Button(c - btn_w - gap // 2, res_y, btn_w, btn_h, "HIGH RES", 22,
            text_color="white", button_color=(40, 100, 160) if hi_active else (60, 60, 70),
            hover_text_color="white", hover_button_color=(60, 130, 190) if hi_active else (80, 80, 95),
            game=self.game, target_state="settings", function="res_high")
        Res_low = Button(c + gap // 2, res_y, btn_w, btn_h, "LOW RES", 22,
            text_color="white", button_color=(40, 100, 160) if lo_active else (60, 60, 70),
            hover_text_color="white", hover_button_color=(60, 130, 190) if lo_active else (80, 80, 95),
            game=self.game, target_state="settings", function="res_low")
        Res_high.draw_button(events)
        Res_low.draw_button(events)

        # ── AUDIO ────────────────────────────────────────────
        self._draw_section_header("AUDIO", int(HEIGHT * 0.30))

        self.get_volume_slider(GAME).draw(events)
        self.get_sfx_volume_slider(GAME).draw(events)

        # ── GAMEPLAY ─────────────────────────────────────────
        self._draw_section_header("GAMEPLAY", int(HEIGHT * 0.52))

        # Tutorial toggle
        tuto_active = self.game.bilal.flags["general"]
        tuto_btn = Button(c - int(WIDTH * 0.045), int(HEIGHT * 0.59),
            int(WIDTH * 0.09), int(HEIGHT * 0.05), "TUTORIAL", 22,
            text_color="white", button_color=(40, 100, 160) if tuto_active else (60, 60, 70),
            hover_text_color="white", hover_button_color=(60, 130, 190) if tuto_active else (80, 80, 95),
            game=self.game, target_state="settings", function="tutorial")
        tuto_btn.draw_button(events)

        # Texture pack label
        label_font = pygame.font.Font(FONT, LABEL_FONT_SIZE)
        pck_label = label_font.render("TEXTURE PACK", True, (200, 200, 200))
        SCREEN.blit(pck_label, (c - pck_label.get_width() // 2, int(HEIGHT * 0.66)))

        # Texture pack dropdown
        drop_w = int(WIDTH * 0.18)
        drop_h = int(HEIGHT * 0.05)
        packs = list_packs()
        if not hasattr(self, '_pack_dropdown') or self._pack_dropdown is None:
            def _on_pack_select(val):
                from ..assets.texture_cache import preload as preload_tex
                set_pack(val)
                self.game._preload_textures("settings")
            self._pack_dropdown = Dropdown(
                c - drop_w // 2, int(HEIGHT * 0.72), drop_w, drop_h, packs,
                self.game, on_select=_on_pack_select
            )
            self._pack_dropdown.sync_from_pack()
        else:
            self._pack_dropdown.options = packs
        self._pack_dropdown.draw(events)

        # ── Back ──────────────────────────────────────────────
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
        self._draw_main_button(events, "BACK", HEIGHT - int(HEIGHT * 0.08), int(WIDTH * 0.11), go_back, font_size=34)

    def draw_credits(self, events, GAME):
        self.game = GAME
        SCREEN.fill(self.bg_color)

        y = self.credits_height
        x = WIDTH // 4
        white = "white"

        self.title_font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(HEIGHT * 0.29))
        self.title_font.set_bold(True)
        title_surf = self.title_font.render("GUNK", True, white)
        SCREEN.blit(title_surf, (WIDTH // 2 - title_surf.get_width() // 2, y))

        self.text_font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(HEIGHT * 0.04))
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

        btn_w = int(WIDTH * 0.07)
        btn_h = int(HEIGHT * 0.06)
        Menu_button = Button(
            WIDTH // 2 - btn_w // 2,
            self.credits_height + HEIGHT // 2 - int(HEIGHT * 0.03) + int(HEIGHT * 0.52),
            btn_w, btn_h, "MENU", 35,
            text_color="black", button_color="white",
            hover_text_color="white", hover_button_color="black",
            game=self.game, target_state="menu"
        )
        Menu_button.draw_button(events)
        
    def draw_UI(self, events):
        self.fps_font = pygame.font.Font(FONT, 20)
        self.fps_font.set_bold(True)
        self.hp_font = pygame.font.Font(FONT, int(HEIGHT * 0.08))
        self.hp_font.set_bold(True)
        SCREEN.blit(self.fps_font.render(f"{round(self.game.clock.get_fps())}", True, 'green'),(int(WIDTH * 0.01), int(HEIGHT * 0.02)))
        SCREEN.blit(self.hp_font.render(f"{round(self.game.global_health)}/{START_HEALTH}", True, 'red'),(WIDTH - int(WIDTH * 0.15), int(HEIGHT * 0.02)))
        SCREEN.blit(self.hp_font.render(f"{round(self.game.global_ammo)}/{AMMO_CAP}", True, 'grey'),(int(WIDTH * 0.01), HEIGHT - int(HEIGHT * 0.1)))
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
    def draw_paused_screen(self, events, GAME):
        self.game = GAME
        c = WIDTH//2
        def resume():
            pygame.mouse.set_visible(False)
            pygame.event.set_grab(True)
            GAME.state = "game"
            pygame.mixer.unpause()
        self._draw_main_button(events, "RESUME", HEIGHT//2 - int(HEIGHT * 0.1), int(WIDTH * 0.11), resume, font_size=34)

        def open_settings():
            GAME._settings_return = "paused"
            GAME.state = "settings"
        self._draw_main_button(events, "SETTINGS", HEIGHT//2 - int(HEIGHT * 0.02), int(WIDTH * 0.11), open_settings, font_size=34)

        def go_menu():
            pygame.mixer.stop()
            if GAME.multiplayer:
                GAME._disconnect()
            else:
                GAME.state = "menu"
        self._draw_main_button(events, "MENU", HEIGHT//2 + int(HEIGHT * 0.06), int(WIDTH * 0.11), go_menu, font_size=34)
    def draw_elevator(self, events, player):
        game = getattr(self, 'game', None)
        if game is None:
            return
        is_client = game.multiplayer
        elev_color = pack_config("elevator_color")
        self.elev_color = tuple(elev_color) if elev_color else (20,20,20)
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
                        s = pygame.mixer.Sound(resolve_asset("sounds/sfx/elev_ding.ogg"))
                        s.set_volume(SFX_VOLUME)
                        s.play()
                self.lift_time -= 1
                if is_client:
                    player.door_pos += ELEV_SPEED
            else:
                if not is_client:
                    pygame.mixer.stop()
                    game.player.door_pos += ELEV_SPEED
                    game.escaped = True
                    s = pygame.mixer.Sound(resolve_asset("sounds/music/Motivator.ogg"))
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
        self.title_font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(HEIGHT * 0.19))
        self.title_font.set_bold(True)
        SCREEN.blit(SCREEN_DEAD, (0,0))
        self.score_font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(HEIGHT * 0.08))
        self.score_font.set_bold(True)
        btn_w = int(WIDTH * 0.07)
        btn_h = int(HEIGHT * 0.06)
        Menu_button = Button(WIDTH // 2 - btn_w // 2, HEIGHT // 2 - btn_h // 2 + int(HEIGHT * 0.1),
            btn_w, btn_h, "MENU", 35,
            text_color="black", button_color="white",
            hover_text_color="white", hover_button_color="black",
            game=self.game, target_state="menu", function="disconnect")
        Menu_button.draw_button(events)
        score_surf = self.score_font.render(f"Score:{self.game.player.score}", True, 'black')
        SCREEN.blit(score_surf, (WIDTH//2 - score_surf.get_width()//2, HEIGHT//2 - int(HEIGHT * 0.04)))
        title_surf = self.title_font.render("GAME OVER", True, 'black')
        SCREEN.blit(title_surf, (WIDTH//2 - title_surf.get_width()//2, HEIGHT//3 - int(HEIGHT * 0.05)))
        
    def draw_escaped_screen(self,events,GAME):
        self.game = GAME
        self.endscreen_font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(HEIGHT * 0.15))
        self.endscreen_font.set_bold(True)
        self.score_font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(HEIGHT * 0.08))
        self.score_font.set_bold(True)
        SCREEN.blit(VICTORY_SCREEN, (0,0))
        pygame.mouse.set_visible(True)
        s1 = self.endscreen_font.render("SUCCESFUL", True, 'white')
        s2 = self.endscreen_font.render("ESKAPE", True, 'white')
        score_surf = self.score_font.render(f"Score:{self.game.player.score}", True, 'white')
        SCREEN.blit(s1, (WIDTH//2 - s1.get_width()//2, HEIGHT//2 - int(HEIGHT * 0.45)))
        SCREEN.blit(s2, (WIDTH//2 - s2.get_width()//2, HEIGHT//2 - int(HEIGHT * 0.27)))
        SCREEN.blit(score_surf, (WIDTH//2 - score_surf.get_width()//2, HEIGHT//2 + int(HEIGHT * 0.01)))
        btn_w = int(WIDTH * 0.07)
        btn_h = int(HEIGHT * 0.06)
        Menu_button = Button(WIDTH // 2 - btn_w // 2, HEIGHT // 2 - btn_h // 2 + int(HEIGHT * 0.15),
            btn_w, btn_h, "MENU", 35,
            text_color="black", button_color="white",
            hover_text_color="white", hover_button_color="black",
            game=self.game, target_state="menu", function="disconnect")
        Menu_button.draw_button(events)
    def _slider_center_x(self, width):
        return WIDTH // 2 - width // 2

    def get_volume_slider(self, GAME):
        if self.volume_slider is None:
            def on_music_change(val):
                GAME.music_volume = val
                GAME.main_music.set_volume(val)
            self.volume_slider = Slider(
                self._slider_center_x(int(WIDTH * 0.21)), int(HEIGHT * 0.37),
                int(WIDTH * 0.21), int(HEIGHT * 0.01),
                min_val=0.0, max_val=1.0, initial_val=GAME.music_volume,
                label="MUSIC VOLUME", game=GAME,
                on_change=on_music_change
                )
        return self.volume_slider

    def get_sfx_volume_slider(self, GAME):
        if self.sfx_volume_slider is None:
            def on_sfx_change(val):
                GAME.sfx_volume = val
                GAME.update_sfx_volume()
            self.sfx_volume_slider = Slider(
                self._slider_center_x(int(WIDTH * 0.21)), int(HEIGHT * 0.44),
                int(WIDTH * 0.21), int(HEIGHT * 0.01),
                min_val=0.0, max_val=1.0, initial_val=getattr(GAME, 'sfx_volume', 0.3),
                label="SFX VOLUME", game=GAME,
                on_change=on_sfx_change
                )
        return self.sfx_volume_slider

Menu_inst = Menu()

class Button:
    def __init__(self, x, y, width, height, text, text_size=25,
                 text_color="black", button_color="white",
                 hover_text_color="white", hover_button_color="black",
                 game=None, target_state=None, mouse_visible=True,
                 function=None):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = text
        self.text_size = text_size
        self.text_color = text_color
        self.button_color = button_color
        self.hover_text_color = hover_text_color
        self.hover_button_color = hover_button_color
        self.GAME = game
        self.target_state = target_state
        self.mouse_visible = mouse_visible
        self.function = function
        self.font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), text_size)
        self.font.set_bold(True)

    def draw_button(self, events):
        mouse = pygame.mouse.get_pos()
        hovering = self.rect.collidepoint(mouse)
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if hovering:
                    if self.function == "disconnect" and self.GAME and self.GAME.multiplayer:
                        self.GAME._disconnect()
                    if self.mouse_visible is not None:
                        pygame.mouse.set_visible(self.mouse_visible)
                    if self.target_state == "game":
                        pygame.event.set_grab(True)
                    elif self.target_state:
                        pygame.event.set_grab(False)
                    if self.target_state:
                        self.GAME.state = self.target_state
                    if self.function == "res_high":
                        set_resolution("high")
                        self.GAME.resolution = "high"
                    elif self.function == "res_low":
                        set_resolution("low")
                        self.GAME.resolution = "low"
                    elif self.function == "tutorial":
                        self.GAME.bilal.flags["general"] = not self.GAME.bilal.flags["general"]
                    if self.target_state == "reset":
                        self.GAME.reset_game()
                    elif self.target_state == "Stop":
                        pygame.mixer.stop()
                        self.GAME.running = False
                    elif self.target_state == "game":
                        pygame.mixer.unpause()
                    elif self.target_state == "menu":
                        pygame.mixer.stop()

        bg = self.hover_button_color if hovering else self.button_color
        fg = self.hover_text_color if hovering else self.text_color
        pygame.draw.rect(SCREEN, bg, self.rect, border_radius=6)
        text_surf = self.font.render(self.text, True, fg)
        tx = self.rect.x + (self.rect.w - text_surf.get_width()) // 2
        ty = self.rect.y + (self.rect.h - text_surf.get_height()) // 2
        SCREEN.blit(text_surf, (tx, ty))

class Dropdown:
    EXPAND_COLOR = (50, 60, 120)
    OPTION_HOVER = (70, 70, 90)
    OPTION_BG = (50, 50, 60)
    OPTION_SELECTED = (40, 80, 120)
    BORDER = (150, 150, 150)

    def __init__(self, x, y, width, height, options, game, on_select=None):
        self.x = x
        self.y = y
        self.w = width
        self.h = height
        self.options = options
        self.game = game
        self.on_select = on_select
        self.selected_index = 0
        self.expanded = False

    def select(self, index):
        if 0 <= index < len(self.options):
            self.selected_index = index
            self.expanded = False
            val = self.options[index]["value"]
            if self.on_select:
                self.on_select(val)

    def draw(self, events):
        mouse = pygame.mouse.get_pos()
        main_rect = pygame.Rect(self.x, self.y, self.w, self.h)
        hover = main_rect.collidepoint(mouse)
        font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(self.h * 0.5))
        font.set_bold(True)

        # Main box
        bg = Dropdown.EXPAND_COLOR if self.expanded else (60, 60, 70) if hover else (40, 40, 40)
        pygame.draw.rect(SCREEN, bg, main_rect, border_radius=6)
        pygame.draw.rect(SCREEN, Dropdown.BORDER, main_rect, 2, border_radius=6)

        # Selected text
        label = self.options[self.selected_index]["label"]
        text_surf = font.render(label, True, 'white')
        SCREEN.blit(text_surf, (self.x + 10, self.y + (self.h - text_surf.get_height()) // 2))

        # Arrow (drawn triangle to avoid unicode font issues)
        ax = self.x + self.w - 18
        ay = self.y + self.h // 2
        if self.expanded:
            pygame.draw.polygon(SCREEN, 'white', [(ax, ay + 5), (ax - 6, ay - 4), (ax + 6, ay - 4)])
        else:
            pygame.draw.polygon(SCREEN, 'white', [(ax, ay - 5), (ax - 6, ay + 4), (ax + 6, ay + 4)])

        # Expanded options
        if self.expanded:
            opt_y = self.y + self.h + 4
            for i, opt in enumerate(self.options):
                opt_rect = pygame.Rect(self.x, opt_y, self.w, self.h)
                opt_hover = opt_rect.collidepoint(mouse)
                bg2 = Dropdown.OPTION_SELECTED if i == self.selected_index else (Dropdown.OPTION_HOVER if opt_hover else Dropdown.OPTION_BG)
                pygame.draw.rect(SCREEN, bg2, opt_rect, border_radius=4)
                pygame.draw.rect(SCREEN, Dropdown.BORDER, opt_rect, 1, border_radius=4)
                opt_surf = font.render(opt["label"], True, 'white')
                SCREEN.blit(opt_surf, (self.x + 10, opt_y + (self.h - opt_surf.get_height()) // 2))
                opt_y += self.h + 2

        # Event handling
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if main_rect.collidepoint(mouse):
                    self.expanded = not self.expanded
                elif self.expanded:
                    opt_y = self.y + self.h + 4
                    clicked = False
                    for i, opt in enumerate(self.options):
                        opt_rect = pygame.Rect(self.x, opt_y, self.w, self.h)
                        if opt_rect.collidepoint(mouse):
                            self.select(i)
                            clicked = True
                            break
                        opt_y += self.h + 2
                    if not clicked:
                        self.expanded = False

    def sync_from_pack(self):
        for i, opt in enumerate(self.options):
            if opt["value"] == TEXTURE_PACK:
                self.selected_index = i
                break


class Slider:
    def __init__(self, x, y, width, height, min_val, max_val, initial_val, label, game, on_change=None):
        self.track_x = x
        self.track_y = y
        self.w = width
        self.h = height
        self.min_val = min_val
        self.max_val = max_val
        self.value = initial_val
        self.label = label
        self.game = game
        self.dragging = False
        self.on_change = on_change
        self.handle_r = height


    def get_handle_x(self):
        ratio = (self.value - self.min_val) / (self.max_val - self.min_val)
        return self.track_x + ratio * self.w

    def draw(self, events):
        self.font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), int(HEIGHT * 0.02))
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
        self.font = pygame.font.Font(asset_path(f"assets/font/{pack_config('font', 'ocraextended.ttf')}"), 20)
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
            Tekstballon(text, HEIGHT - int(HEIGHT * 0.43), int(WIDTH * 0.01), self.Game).draw()
            SCREEN.blit(BILAL, (0, HEIGHT - int(HEIGHT * 0.33)))

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
