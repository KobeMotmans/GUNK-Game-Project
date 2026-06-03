import os
import pygame
import tkinter as tk
from tkinter import filedialog
from ..core.config import HEIGHT, WIDTH, SCREEN, set_resolution, TUTORIAL, VICTORY_SCREEN, SCREEN_DEAD, START_HEALTH, AMMO_CAP, ELEV_SPEED, MAX_LEVEL, ELEV_TIME, DEFAULT_PORT, SFX_VOLUME
from ..core.paths import list_packs, set_packs, save_active_packs, load_active_packs, TEXTURE_PACKS, load_font, load_numeric_font, resolve_asset
from ..core.theme import theme
from collections import deque
from ..core.map_loader import M
from ..assets.skin_manager import SkinManager
from ..network.network import NetworkClient

def _draw_arrow(screen, rect, direction, color):
    cx = rect.x + rect.w // 2
    cy = rect.y + rect.h // 2
    s = min(rect.w, rect.h) // 3
    if direction == 'right':
        pts = [(cx - s, cy - s), (cx - s, cy + s), (cx + s, cy)]
    elif direction == 'left':
        pts = [(cx + s, cy - s), (cx + s, cy + s), (cx - s, cy)]
    elif direction == 'up':
        pts = [(cx - s, cy + s), (cx + s, cy + s), (cx, cy - s)]
    elif direction == 'down':
        pts = [(cx - s, cy - s), (cx + s, cy - s), (cx, cy + s)]
    else:
        return
    pygame.draw.polygon(screen, color, pts)

class Menu:
    def __init__(self):
        self.bg_color = theme.color("menu.bg", (70, 70, 70))
        self._bg_img = None
        self._load_bg_texture()
        self.credits_height = HEIGHT
        self.volume_slider = None
        self.sfx_volume_slider = None
        
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
        self.lobby_countdown = 0
        self.lobby_game_active = False
        self.waiting_text = theme.string("multiplayer.connecting", "Verbinden...")
        self.mp_status = ""
        self._skin_thumbnails = {}
        self._skin_page = 0
        self.mp_skin_search = ""
        self.mp_skin_upload_name = ""
        self._upload_status = None
        self._cd_ticks = 0

        # Pack select state
        self._working_packs = []
        self._pack_sel_avail_idx = 0
        self._pack_sel_active_idx = 0
        self._pack_sel_avail_scroll = 0
        self._pack_sel_active_scroll = 0

    def _load_bg_texture(self):
        path = theme.get("textures.menu_bg")
        if path:
            try:
                img = pygame.image.load(resolve_asset(path)).convert()
                self._bg_img = pygame.transform.scale(img, (WIDTH, HEIGHT))
            except Exception:
                self._bg_img = None
        else:
            self._bg_img = None
        self.bg_color = theme.color("menu.bg", (70, 70, 70))

    def _fill_bg(self):
        if self._bg_img:
            SCREEN.blit(self._bg_img, (0, 0))
        else:
            SCREEN.fill(self.bg_color)

    def draw_loading_screen(self, progress=None, label=None):
        self._fill_bg()
        loading_font = load_font(theme.size("loading.text_font", int(HEIGHT * 0.1)), bold=True)
        load_surf = loading_font.render(theme.string("loading.text", "Loading..."), True, theme.color("text.title", 'white'))
        SCREEN.blit(load_surf, (WIDTH // 2 - load_surf.get_width() // 2, HEIGHT - int(HEIGHT * theme.pos("loading.text_y", 0.29))))

        title_font = load_font(theme.size("menu.title_font", int(HEIGHT * 0.29)), bold=True)
        title_surf = title_font.render(theme.string("menu.title", "GUNK"), True, theme.color("text.title", 'white'))
        SCREEN.blit(title_surf, (WIDTH // 2 - title_surf.get_width() // 2, HEIGHT // 2 - title_surf.get_height() // 2))

        bar_width = theme.size("loading.bar_width", int(WIDTH * 0.31))
        bar_height = theme.size("loading.bar_height", int(HEIGHT * 0.03))
        bar_x = WIDTH // 2 - bar_width // 2
        bar_y = HEIGHT - int(HEIGHT * theme.pos("loading.bar_y", 0.15))

        pygame.draw.rect(SCREEN, theme.color("loading.bar_bg", (80, 80, 80)), (bar_x, bar_y, bar_width, bar_height))

        if progress is not None:
            self.loading_progress = progress
        progress_width = bar_width * self.loading_progress
        pygame.draw.rect(SCREEN, theme.color("loading.bar_fill", (0, 200, 0)), (bar_x, bar_y, progress_width, bar_height))
        if progress is None:
            self.loading_progress += 0.2

        if label:
            label_font = load_font(theme.size("loading.label_font", 16))
            label_surf = label_font.render(label, True, theme.color("text.subtitle", (150, 150, 150)))
            SCREEN.blit(label_surf, (WIDTH // 2 - label_surf.get_width() // 2, bar_y + bar_height + 6))

        pygame.display.flip()

    def _draw_main_button(self, events, text, y_pos, w, action=None, h=None, font_size=None, x=None):
        if x is None:
            x = WIDTH//2 - w//2
        if h is None:
            h = theme.size("menu.btn_h", int(HEIGHT * 0.04))
        rect = pygame.Rect(x, y_pos, w, h)
        mouse = pygame.mouse.get_pos()
        hover = rect.collidepoint(mouse)
        br = theme.size("button.border_radius", 8)
        pygame.draw.rect(SCREEN, theme.color("button.hover_bg", (100, 100, 100)) if hover else theme.color("button.bg", (70, 70, 70)), rect, border_radius=br)
        if hover:
            pygame.draw.rect(SCREEN, theme.color("button.border", (180, 180, 180)), rect, 2, border_radius=br)
        font = load_font(font_size)
        tc = theme.color("button.hover_text", 'white') if hover else theme.color("button.text", 'white')
        surf = font.render(text, True, tc)
        SCREEN.blit(surf, (x + w//2 - surf.get_width()//2, y_pos + h//2 - surf.get_height()//2))
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if rect.collidepoint(ev.pos) and action:
                    action()
                    return True
        return False

    def draw_main_menu(self, events, GAME):
        self.game = GAME
        self._fill_bg()
        title_font = load_font(theme.size("menu.title_font", int(HEIGHT * 0.29)), bold=True)
        title_surf = title_font.render(theme.string("menu.title", "GUNK"), True, theme.color("text.title", 'white'))
        SCREEN.blit(title_surf, (WIDTH // 2 - title_surf.get_width() // 2, int(HEIGHT * theme.pos("menu.title_y", 0.08))))

        c = WIDTH//2
        btn_w = theme.size("menu.btn_wide", int(WIDTH * 0.16))
        gap = theme.size("menu.btn_gap", int(WIDTH * 0.03))
        self._draw_main_button(events, theme.string("menu.solo", "SOLO"), int(HEIGHT * theme.pos("menu.solo_mp_y", 0.38)), btn_w, lambda: GAME.reset_game(), font_size=36, x=c - btn_w - gap//2)
        self._draw_main_button(events, theme.string("menu.multiplayer", "MULTIPLAYER"), int(HEIGHT * theme.pos("menu.solo_mp_y", 0.38)), btn_w, lambda: setattr(GAME, 'state', 'multiplayer_menu'), font_size=36, x=c + gap//2)
        self._draw_main_button(events, theme.string("menu.options", "OPTIONS"), int(HEIGHT * theme.pos("menu.options_y", 0.47)), int(WIDTH * 0.11), lambda: setattr(GAME, 'state', 'settings'), font_size=36)
        self._draw_main_button(events, theme.string("menu.credits", "CREDITS"), int(HEIGHT * theme.pos("menu.credits_y", 0.54)), int(WIDTH * 0.11), lambda: setattr(GAME, 'state', 'credits'), font_size=36)
        self._draw_main_button(events, theme.string("menu.quit", "QUIT"), int(HEIGHT * theme.pos("menu.quit_y", 0.62)), int(WIDTH * 0.11), lambda: setattr(GAME, 'running', False), font_size=36)
    # --- Multiplayer UI ----------------------------------------

    def _draw_text_input(self, events, label, current_text, x, y, width, height=None, field_id=None, numeric=False):
        """Draw a text input field. Returns the (possibly updated) text."""
        if height is None:
            height = theme.size("input.height", 30)
        mouse = pygame.mouse.get_pos()
        rect = pygame.Rect(x, y, width, height)

        label_font = load_font(theme.size("input.label_font", 22))
        label_surf = label_font.render(label, True, theme.color("text.title", 'white'))
        SCREEN.blit(label_surf, (x, y - theme.size("input.label_offset", 25)))

        focused = self.input_focus == field_id
        bg_color = theme.color("input.focus_bg", (60, 60, 80)) if focused else theme.color("input.bg", (40, 40, 40))
        pygame.draw.rect(SCREEN, bg_color, rect, border_radius=4)
        pygame.draw.rect(SCREEN, theme.color("input.focus_border", (180, 180, 255)) if focused else theme.color("input.border", (100, 100, 100)), rect, 2, border_radius=4)

        font = load_numeric_font(theme.size("input.text_font", 22))
        display_text = current_text + ("|" if focused else "")
        text_surf = font.render(display_text, True, theme.color("text.title", 'white'))
        SCREEN.blit(text_surf, (x + theme.size("input.text_inset_x", 6), y + (height - text_surf.get_height()) // 2))

        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if rect.collidepoint(mouse):
                    self.input_focus = field_id
                elif self.input_focus == field_id:
                    self.input_focus = None
            if ev.type == pygame.KEYDOWN and self.input_focus == field_id:
                if ev.key == pygame.K_v and pygame.key.get_mods() & pygame.KMOD_CTRL:
                    root = tk.Tk()
                    root.withdraw()
                    try:
                        pasted = root.clipboard_get()
                        for ch in pasted:
                            if numeric and ch in "0123456789":
                                current_text += ch
                            elif not numeric and ch.isprintable():
                                current_text += ch
                    except:
                        pass
                    root.destroy()
                elif ev.key == pygame.K_BACKSPACE:
                    current_text = current_text[:-1]
                elif ev.key == pygame.K_ESCAPE:
                    self.input_focus = None
                elif ev.unicode:
                    if numeric and ev.unicode in "0123456789":
                        current_text += ev.unicode
                    elif not numeric and ev.unicode.isprintable():
                        current_text += ev.unicode
        return current_text

    def _draw_button_custom(self, events, text, x, y, w, h, action=None):
        """Simple custom button returning True if clicked."""
        mouse = pygame.mouse.get_pos()
        rect = pygame.Rect(x, y, w, h)
        enabled = action is not None
        hover = rect.collidepoint(mouse) and enabled
        br = theme.size("button.border_radius", 6)
        bg = theme.color("button.hover_bg", (100, 100, 100)) if hover else (theme.color("button.disabled_bg", (40, 40, 40)) if not enabled else theme.color("button.bg", (70, 70, 70)))
        pygame.draw.rect(SCREEN, bg, rect, border_radius=br)
        if hover:
            pygame.draw.rect(SCREEN, theme.color("button.border", (180, 180, 180)), rect, 2, border_radius=br)
        font = load_font(theme.size("button.custom_font", 28))
        tc = theme.color("button.hover_text", 'white') if hover else theme.color("button.text", 'white')
        surf = font.render(text, True, tc)
        SCREEN.blit(surf, (x + w//2 - surf.get_width()//2, y + h//2 - surf.get_height()//2))
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if rect.collidepoint(mouse) and enabled:
                    print(f"[DEBUG] button clicked: '{text}'")
                    action()
                    return True
        return False

    def draw_multiplayer_menu(self, events, GAME):
        self.game = GAME
        self._fill_bg()

        join_font = load_font(36)
        join_label = join_font.render(theme.string("multiplayer.title", "JOIN SERVER"), True, theme.color("text.title", 'white'))
        SCREEN.blit(join_label, (WIDTH//2 - join_label.get_width()//2, int(HEIGHT * theme.pos("mp.title_y", 0.04))))

        info_text = theme.string("multiplayer.info", "Start de server apart: python run_server.py")
        info = load_font(16).render(info_text, True, theme.color("text.info", (150, 150, 150)))
        SCREEN.blit(info, (WIDTH//2 - info.get_width()//2, int(HEIGHT * theme.pos("menu.title_y", 0.08))))

        name_label = load_font(22).render(theme.string("multiplayer.name_label", "JOUW NAAM"), True, theme.color("text.subtitle", (200, 200, 200)))
        SCREEN.blit(name_label, (WIDTH//2 - name_label.get_width()//2, int(HEIGHT * theme.pos("mp.name_label_y", 0.13))))
        self.mp_name_input = self._draw_text_input(events, "", self.mp_name_input, WIDTH//2 - int(WIDTH * 0.09), int(HEIGHT * theme.pos("mp.name_input_y", 0.16)), int(WIDTH * 0.18), field_id="mp_name")

        ip_label = load_font(20).render(theme.string("multiplayer.ip_label", "SERVER IP"), True, theme.color("text.subtitle", (200, 200, 200)))
        SCREEN.blit(ip_label, (WIDTH//2 - ip_label.get_width()//2, int(HEIGHT * theme.pos("mp.ip_label_y", 0.22))))
        self.mp_join_ip = self._draw_text_input(events, "", self.mp_join_ip, WIDTH//2 - int(WIDTH * 0.09), int(HEIGHT * theme.pos("mp.ip_input_y", 0.25)), int(WIDTH * 0.18), field_id="mp_join_ip")

        port_label = load_font(20).render(theme.string("multiplayer.port_label", "POORT"), True, theme.color("text.subtitle", (200, 200, 200)))
        SCREEN.blit(port_label, (WIDTH//2 - port_label.get_width()//2, int(HEIGHT * theme.pos("mp.port_label_y", 0.31))))
        self.mp_join_port = self._draw_text_input(events, "", self.mp_join_port, WIDTH//2 - int(WIDTH * 0.09), int(HEIGHT * theme.pos("mp.port_input_y", 0.34)), int(WIDTH * 0.18), field_id="mp_join_port", numeric=True)

        def do_connect():
            name = self.mp_name_input.strip() or theme.string("multiplayer.default_name", "Player")
            ip = self.mp_join_ip.strip() or "127.0.0.1"
            try:
                port = int(self.mp_join_port) if self.mp_join_port else DEFAULT_PORT
            except ValueError:
                port = DEFAULT_PORT
            GAME._do_connect(ip, port, name)
        self._draw_button_custom(events, theme.string("multiplayer.join", "JOIN GAME"), WIDTH//2 - int(WIDTH * 0.06), int(HEIGHT * theme.pos("mp.join_btn_y", 0.40)), int(WIDTH * 0.12), int(HEIGHT * 0.05), do_connect)

        if self.mp_status:
            color = theme.color("text.success", (0, 200, 0)) if "gelukt" in self.mp_status else theme.color("text.fail", (200, 0, 0))
            status = load_font(22).render(self.mp_status, True, color)
            SCREEN.blit(status, (WIDTH//2 - status.get_width()//2, int(HEIGHT * theme.pos("mp.status_y", 0.48))))

        self._draw_button_custom(events, theme.string("button.back", "BACK"), WIDTH//2 - int(WIDTH * 0.04), HEIGHT - int(HEIGHT * theme.pos("menu.title_y", 0.08)), int(WIDTH * 0.08), int(HEIGHT * 0.04), lambda: setattr(GAME, 'state', 'menu'))

    def draw_waiting_lobby(self, events, GAME):
        self.game = GAME
        self._fill_bg()

        for sid in SkinManager.get_completed_downloads():
            self._skin_thumbnails.pop(sid, None)
        SkinManager.clear_completed_downloads()

        title = load_font(50).render(theme.string("lobby.title", "LOBBY"), True, theme.color("text.title", 'white'))
        SCREEN.blit(title, (WIDTH//2 - title.get_width()//2, int(HEIGHT * theme.pos("menu.title_y", 0.08))))

        if SkinManager.is_downloading():
            prog = SkinManager.get_download_progress()
            dl_label = "%s %d/%d" % (theme.string("lobby.downloading", "Skins downloaden..."), prog["done"], prog["total"])
            dl_text = load_font(16).render(dl_label, True, theme.color("text.info", (150, 150, 150)))
            SCREEN.blit(dl_text, (WIDTH//2 - dl_text.get_width()//2, int(HEIGHT * theme.pos("menu.title_y", 0.08)) + 30))

        mouse = pygame.mouse.get_pos()

        # ── Left column: player list ──────────────────────────────
        left_x = int(WIDTH * 0.04)
        left_cx = int(WIDTH * 0.20)
        y_left = int(HEIGHT * theme.pos("lobby.left_start_y", 0.15))
        players = self.client_list if self.client_list else []
        thumb_size = theme.size("lobby.thumb_size", 36)
        all_ready = True
        for pd in players:
            pid = pd["pid"] if isinstance(pd, dict) else pd[1]
            name = pd["name"] if isinstance(pd, dict) else pd[0]
            skin_id = pd.get("skin_id", 0) if isinstance(pd, dict) else (pd[2] if len(pd) > 2 else 0)
            ready = pd.get("ready", False) if isinstance(pd, dict) else False
            if not ready:
                all_ready = False
            color = theme.color("player.highlight", (0, 200, 255)) if pid == GAME.player_id else theme.color("text.title", (255, 255, 255))
            if skin_id not in self._skin_thumbnails or self._skin_thumbnails[skin_id].get_width() != thumb_size:
                self._skin_thumbnails[skin_id] = SkinManager.create_thumbnail(skin_id, (thumb_size, thumb_size))
            SCREEN.blit(self._skin_thumbnails[skin_id], (left_x, y_left - 4))
            ready_text = theme.string("lobby.ready", "READY") if ready else theme.string("lobby.not_ready", "NOT READY")
            ready_color = theme.color("lobby.ready", (0, 200, 0)) if ready else theme.color("lobby.not_ready", (200, 80, 80))
            ready_surf = load_font(16).render(ready_text, True, ready_color)
            p_text = load_numeric_font(26).render(f"[P{pid}] {name}", True, color)
            SCREEN.blit(p_text, (left_x + thumb_size + 10, y_left))
            SCREEN.blit(ready_surf, (left_x + thumb_size + 10, y_left + 28))
            y_left += theme.size("lobby.player_row_gap", int(HEIGHT * 0.055))
        if not players:
            all_ready = False
            wait = load_font(22).render(theme.string("lobby.waiting", "Wachten op spelers..."), True, theme.color("text.info", (150, 150, 150)))
            SCREEN.blit(wait, (left_cx - wait.get_width()//2, y_left))

        # ── Right column: skin selector ───────────────────────────
        right_cx = int(WIDTH * 0.66)
        y_right = int(HEIGHT * theme.pos("lobby.right_start_y", 0.15))

        sel_label = load_font(22).render(theme.string("lobby.skin_choose", "KIEZEN"), True, theme.color("text.subtitle", (200, 200, 200)))
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
            border_color = theme.color("skin.selected", (0, 200, 255)) if sid == GAME.skin_id else theme.color("skin.border", (60, 60, 60))
            pygame.draw.rect(SCREEN, border_color, rect, 3, border_radius=4)
            name_font = load_numeric_font(13)
            name_surf = name_font.render(info.get("name", f"S{sid}"), True, theme.color("text.info", (150, 150, 150)))
            SCREEN.blit(name_surf, (x + t_size_b//2 - name_surf.get_width()//2, y_right + t_size_b + 2))
        y_right += t_size_b + 28

        # ── Upload section (always visible) ─────────────────────────
        upload_font = load_font(16)
        upload_label = upload_font.render(theme.string("lobby.new_skin", "NIEUWE SKIN"), True, theme.color("text.subtitle", (200, 200, 200)))
        SCREEN.blit(upload_label, (right_cx - upload_label.get_width()//2, y_right))
        y_right += 22
        pending_path = getattr(self, '_pending_upload_path', None)
        name_w = int(WIDTH * 0.08)
        btn_w = int(WIDTH * 0.08)
        name_x = right_cx - name_w - int(WIDTH * 0.02)
        if pending_path:
            self.mp_skin_upload_name = self._draw_text_input(events, "",
                self.mp_skin_upload_name, name_x, y_right, name_w,
                height=26, field_id="mp_skin_upload_name")
            btn_x = right_cx + int(WIDTH * 0.02)
            con_rect = pygame.Rect(btn_x, y_right, btn_w, 26)
            hover = con_rect.collidepoint(mouse)
            pygame.draw.rect(SCREEN, theme.color("upload.hover_bg", (80, 120, 80)) if hover else theme.color("upload.bg", (60, 90, 60)), con_rect, border_radius=4)
            con_surf = upload_font.render(theme.string("lobby.confirm", "CONFIRM"), True, theme.color("upload.text", (200, 255, 200)))
            SCREEN.blit(con_surf, (btn_x + btn_w//2 - con_surf.get_width()//2, y_right + 5))
            self._skin_confirm_rect = con_rect
            pending_label = upload_font.render(getattr(self, '_pending_upload_filename', ''), True, theme.color("text.info", (180, 180, 180)))
            SCREEN.blit(pending_label, (name_x, y_right - 20))
        else:
            sel_rect = pygame.Rect(right_cx - btn_w//2, y_right, btn_w, 26)
            hover = sel_rect.collidepoint(mouse)
            pygame.draw.rect(SCREEN, theme.color("upload.hover_bg", (80, 120, 80)) if hover else theme.color("upload.bg", (60, 90, 60)), sel_rect, border_radius=4)
            sel_surf = upload_font.render(theme.string("lobby.select_file", "SELECT"), True, theme.color("upload.text", (200, 255, 200)))
            SCREEN.blit(sel_surf, (right_cx - sel_surf.get_width()//2, y_right + 5))
            self._skin_select_rect = sel_rect
        y_right += 32

        if self._upload_status:
            col = theme.color("text.success", (0, 200, 0)) if "gelukt" in self._upload_status.lower() else theme.color("text.warning", (200, 100, 0))
            st = load_numeric_font(15).render(self._upload_status, True, col)
            SCREEN.blit(st, (right_cx - st.get_width()//2, y_right))
            y_right += 20

        # ── Custom skins browser ────────────────────────────────────
        self._skin_custom_rects = []
        self._skin_custom_info = []
        if custom:
            cus_label = load_font(18).render(theme.string("lobby.custom", "CUSTOM"), True, theme.color("text.custom", (160, 140, 255)))
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

            per_page = theme.size("lobby.skins_per_page", 4)
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
                border_color = theme.color("skin.selected", (0, 200, 255)) if sid == GAME.skin_id else theme.color("skin.border", (60, 60, 60))
                pygame.draw.rect(SCREEN, border_color, rect, 2, border_radius=4)
                name_font = load_numeric_font(12)
                label = info.get("name", f"S{sid}")
                if len(label) > 14:
                    label = label[:13] + "..."
                name_surf = name_font.render(label, True, theme.color("text.info", (160, 160, 160)))
                SCREEN.blit(name_surf, (x + t_size_c//2 - name_surf.get_width()//2, y_right + t_size_c + 2))

            y_right += t_size_c + 22

            # Pagination controls
            self._skin_prev_rect = None
            self._skin_next_rect = None
            if total_pages > 1:
                arr_font = load_numeric_font(20)
                prev_surf = arr_font.render("<", True, theme.color("pagination.arrow", (200, 200, 200)))
                prev_rect = pygame.Rect(right_cx - int(WIDTH * 0.08), y_right - 6,
                                        prev_surf.get_width() + 8, prev_surf.get_height() + 4)
                pygame.draw.rect(SCREEN, theme.color("pagination.active_bg", (70, 70, 70)) if page > 0 else theme.color("pagination.disabled_bg", (40, 40, 40)), prev_rect, border_radius=4)
                SCREEN.blit(prev_surf, (prev_rect.x + 4, prev_rect.y + 2))
                self._skin_prev_rect = prev_rect
                self._skin_prev_page = page > 0

                page_surf = arr_font.render(f"{page + 1}/{total_pages}", True, theme.color("pagination.page", (180, 180, 180)))
                SCREEN.blit(page_surf, (right_cx - page_surf.get_width()//2, y_right - 4))

                next_surf = arr_font.render(">", True, theme.color("pagination.arrow", (200, 200, 200)))
                next_rect = pygame.Rect(right_cx + int(WIDTH * 0.06), y_right - 6,
                                        next_surf.get_width() + 8, next_surf.get_height() + 4)
                pygame.draw.rect(SCREEN, theme.color("pagination.active_bg", (70, 70, 70)) if page < total_pages - 1 else theme.color("pagination.disabled_bg", (40, 40, 40)),
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

                if getattr(self, '_skin_select_rect', None) and self._skin_select_rect.collidepoint(mouse):
                    root = tk.Tk()
                    root.withdraw()
                    filepath = filedialog.askopenfilename(
                        title="Selecteer een afbeelding",
                        filetypes=[("Afbeeldingen", "*.png *.jpg *.jpeg *.gif *.bmp"), ("Alle bestanden", "*.*")]
                    )
                    root.destroy()
                    if filepath:
                        self._pending_upload_path = filepath
                        filename = os.path.splitext(os.path.basename(filepath))[0]
                        self._pending_upload_filename = filename
                        self.mp_skin_upload_name = filename
                        self._upload_status = ""

                if getattr(self, '_skin_confirm_rect', None) and self._skin_confirm_rect.collidepoint(mouse):
                    skin_name = self.mp_skin_upload_name.strip()
                    if not skin_name:
                        skin_name = getattr(self, '_pending_upload_filename', 'skin')
                    uploader = GAME.player_name
                    self._upload_status = theme.string("lobby.upload_progress", "Bezig met uploaden...")
                    ok, msg, *rest = GAME.network_client.upload_skin(skin_name, uploader, self._pending_upload_path)
                    self._upload_status = msg
                    self._pending_upload_path = None
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

        # ── Countdown banner ───────────────────────────────────────────
        if self.lobby_countdown > 0:
            elapsed_ms = pygame.time.get_ticks() - getattr(self, '_cd_ticks', 0)
            frames_passed = elapsed_ms / (1000 / 60)
            remaining = max(0, int(self.lobby_countdown - frames_passed))
            if remaining > 0:
                seconds = max(1, remaining // 60 + 1)
                count_text = theme.string("lobby.countdown", "STARTING IN {s}...").format(s=seconds)
                count_surf = load_font(40).render(count_text, True, theme.color("lobby.countdown", (255, 200, 0)))
                SCREEN.blit(count_surf, (WIDTH//2 - count_surf.get_width()//2, int(HEIGHT * 0.12)))

        # ── Debug overlay ──────────────────────────────────────────────
        debug_parts = ["DEBUG"]
        for pd in players:
            pid = pd["pid"] if isinstance(pd, dict) else pd[1]
            ready = pd.get("ready", False) if isinstance(pd, dict) else False
            tag = "READY" if ready else "UNREADY"
            highlight = " ->" if pid == GAME.player_id else ""
            debug_parts.append(f"P{pid}:{tag}{highlight}")
        if not players:
            debug_parts.append("no players")
        debug_parts.append(f"cd={self.lobby_countdown}")
        debug_parts.append(f"act={'YES' if self.lobby_game_active else 'no'}")
        debug_surf = load_font(16).render(" | ".join(debug_parts), True, (255, 255, 0))
        SCREEN.blit(debug_surf, (int(WIDTH * 0.02), int(HEIGHT * 0.05)))

        def dc():
            GAME._disconnect()

        def toggle_ready():
            GAME._toggle_ready()

        def join_game():
            GAME._join_active_game()

        # ── Bottom buttons ─────────────────────────────────────────────
        btn_y = HEIGHT - int(HEIGHT * theme.pos("lobby.start_btn_y", 0.13))
        btn_w = int(WIDTH * 0.1)

        if self.lobby_game_active:
            self._draw_button_custom(events, theme.string("lobby.join_game", "JOIN GAME"),
                WIDTH//2 - btn_w//2, btn_y, btn_w, int(HEIGHT * 0.05), join_game)
        else:
            my_ready = False
            for pd in players:
                pid = pd["pid"] if isinstance(pd, dict) else pd[1]
                if pid == GAME.player_id:
                    my_ready = pd.get("ready", False) if isinstance(pd, dict) else False
                    break
            ready_label = theme.string("lobby.ready_done", "✓ READY") if my_ready else theme.string("lobby.ready_up", "READY UP")
            self._draw_button_custom(events, ready_label,
                WIDTH//2 - btn_w//2, btn_y, btn_w, int(HEIGHT * 0.05), toggle_ready)

        self._draw_button_custom(events, theme.string("lobby.disconnect", "DISCONNECT"), WIDTH//2 - int(WIDTH * 0.04),
            HEIGHT - int(HEIGHT * theme.pos("lobby.disconnect_btn_y", 0.07)), int(WIDTH * 0.08), int(HEIGHT * 0.03), dc)

    def _select_skin(self, GAME, skin_id):
        GAME.skin_id = skin_id
        self.mp_skin_id = skin_id
        if GAME.network_client and GAME.network_client.connected:
            GAME.network_client.send({"type": "select_skin", "skin_id": skin_id})
            NetworkClient._save_config(GAME.player_name,
                GAME.network_client.server_addr[0],
                GAME.network_client.server_addr[1], skin_id)

    # ── Settings ──────────────────────────────────────────────

    def _draw_section_header(self, text, y, color=None):
        if color is None:
            color = theme.color("text.section_header", (160, 160, 160))
        font = load_font(24)
        surf = font.render(text, True, color)
        cx = WIDTH // 2
        left_margin = int(WIDTH * theme.pos("section_header.left_margin", 0.08))
        right_margin = WIDTH - left_margin
        mid_y = y + surf.get_height() // 2
        gap = theme.size("section_header.gap", 14)
        lx = cx - surf.get_width() // 2 - gap
        rx = cx + surf.get_width() // 2 + gap
        if lx > left_margin:
            pygame.draw.line(SCREEN, color, (left_margin, mid_y), (lx, mid_y), 2)
        if rx < right_margin:
            pygame.draw.line(SCREEN, color, (rx, mid_y), (right_margin, mid_y), 2)
        SCREEN.blit(surf, (cx - surf.get_width() // 2, y))

    def draw_settings(self, events, GAME):
        self.game = GAME
        self._fill_bg()
        c = WIDTH // 2

        # ── Title ─────────────────────────────────────────────
        title_font = load_font(theme.size("settings.title_font", int(HEIGHT * 0.07)), bold=True)
        title_surf = title_font.render(theme.string("settings.title", "SETTINGS"), True, theme.color("text.title", 'white'))
        SCREEN.blit(title_surf, (c - title_surf.get_width() // 2, int(HEIGHT * theme.pos("mp.title_y", 0.04))))

        LABEL_FONT_SIZE = theme.size("settings.label_font", 20)
        btn_w = int(WIDTH * 0.09)
        btn_h = theme.size("settings.btn_h", int(HEIGHT * 0.05))
        gap = int(WIDTH * 0.02)

        # ── VIDEO ────────────────────────────────────────────
        self._draw_section_header(theme.string("settings.video", "VIDEO"), int(HEIGHT * theme.pos("settings.video_header_y", 0.14)))

        hi_active = self.game.resolution == "high"
        lo_active = self.game.resolution == "low"
        res_y = int(HEIGHT * theme.pos("settings.res_btn_y", 0.21))
        Res_high = Button(c - btn_w - gap // 2, res_y, btn_w, btn_h, theme.string("settings.high_res", "HIGH RES"), 22,
            text_color="white", button_color=(40, 100, 160) if hi_active else (60, 60, 70),
            hover_text_color="white", hover_button_color=(60, 130, 190) if hi_active else (80, 80, 95),
            game=self.game, target_state="settings", function="res_high")
        Res_low = Button(c + gap // 2, res_y, btn_w, btn_h, theme.string("settings.low_res", "LOW RES"), 22,
            text_color="white", button_color=(40, 100, 160) if lo_active else (60, 60, 70),
            hover_text_color="white", hover_button_color=(60, 130, 190) if lo_active else (80, 80, 95),
            game=self.game, target_state="settings", function="res_low")
        Res_high.draw_button(events)
        Res_low.draw_button(events)

        # ── AUDIO ────────────────────────────────────────────
        self._draw_section_header(theme.string("settings.audio", "AUDIO"), int(HEIGHT * theme.pos("settings.audio_header_y", 0.30)))

        self.get_volume_slider(GAME).draw(events)
        self.get_sfx_volume_slider(GAME).draw(events)

        # ── GAMEPLAY ─────────────────────────────────────────
        self._draw_section_header(theme.string("settings.gameplay", "GAMEPLAY"), int(HEIGHT * theme.pos("settings.gameplay_header_y", 0.52)))

        # Tutorial toggle
        tuto_active = self.game.bilal.flags["general"]
        tuto_btn = Button(c - int(WIDTH * 0.045), int(HEIGHT * theme.pos("settings.tutorial_btn_y", 0.59)),
            int(WIDTH * 0.09), int(HEIGHT * 0.05), theme.string("settings.tutorial", "TUTORIAL"), 22,
            text_color="white", button_color=(40, 100, 160) if tuto_active else (60, 60, 70),
            hover_text_color="white", hover_button_color=(60, 130, 190) if tuto_active else (80, 80, 95),
            game=self.game, target_state="settings", function="tutorial")
        tuto_btn.draw_button(events)

        # Texture pack → pack selector
        self._draw_main_button(events,
            theme.string("settings.texture_pack", "TEXTURE PACKS →"),
            int(HEIGHT * theme.pos("settings.pack_btn_y", 0.66)),
            int(WIDTH * 0.14),
            lambda: self._open_pack_select(GAME),
            font_size=28)

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
        self._draw_main_button(events, theme.string("button.back", "BACK"), HEIGHT - int(HEIGHT * theme.pos("menu.title_y", 0.08)), int(WIDTH * 0.11), go_back, font_size=34)

    # ── Pack Select ─────────────────────────────────────────

    def _open_pack_select(self, GAME):
        self._working_packs = list(TEXTURE_PACKS)
        self._pack_sel_avail_idx = 0
        self._pack_sel_active_idx = 0
        self._pack_sel_avail_scroll = 0
        self._pack_sel_active_scroll = 0
        GAME.state = "pack_select"

    def draw_pack_select(self, events, GAME):
        self.game = GAME
        self._fill_bg()
        c = WIDTH // 2

        title_font = load_font(theme.size("settings.title_font", int(HEIGHT * 0.07)), bold=True)
        title_surf = title_font.render(theme.string("pack_select.title", "TEXTURE PACKS"), True, theme.color("text.title", 'white'))
        SCREEN.blit(title_surf, (c - title_surf.get_width() // 2, int(HEIGHT * theme.pos("mp.title_y", 0.04))))

        all_packs = [p["value"] for p in list_packs()]
        avail = [p for p in all_packs if p not in self._working_packs]

        # ── Layout constants ──────────────────────────────
        col_w = int(WIDTH * 0.18)
        col_h = int(HEIGHT * 0.50)
        col_y = int(HEIGHT * 0.16)
        item_h = int(HEIGHT * 0.048)
        arr_w = int(WIDTH * 0.025)
        prio_w = int(WIDTH * 0.018)
        gap = int(WIDTH * 0.008)
        visible = col_h // item_h
        font = load_font(theme.size("pack_select.item_font", 22))
        label_font = load_font(theme.size("pack_select.column_label", 20))
        mouse = pygame.mouse.get_pos()

        # Center the whole block:
        block_w = col_w * 2 + arr_w + prio_w + gap * 4
        block_x = (WIDTH - block_w) // 2
        left_x = block_x
        arr_x = left_x + col_w + gap
        right_x = arr_x + arr_w + gap
        prio_x = right_x + col_w + gap

        box_border = theme.color("pack_select.box_border", (80, 80, 80))
        box_bg = theme.color("pack_select.box_bg", (30, 30, 35))
        sel_bg = theme.color("pack_select.selected_bg", (50, 70, 100))
        hover_bg = theme.color("pack_select.hover_bg", (60, 60, 70))
        item_bg = theme.color("pack_select.item_bg", (40, 40, 40))
        text_col = theme.color("pack_select.text", 'white')
        sub_col = theme.color("text.subtitle", (200, 200, 200))
        arrow_col = theme.color("pack_select.arrow_text", 'white')
        arr_idle = theme.color("pack_select.arrow_idle", (50, 50, 50))
        arr_hov = theme.color("pack_select.arrow_bg", (60, 60, 70))

        # ── Helper: draw a column list ────────────────────
        def draw_column(items, x, scroll, sel_idx):
            box = pygame.Rect(x, col_y, col_w, col_h)
            pygame.draw.rect(SCREEN, box_bg, box, border_radius=6)
            pygame.draw.rect(SCREEN, box_border, box, 2, border_radius=6)
            for i in range(visible):
                idx = scroll + i
                if idx >= len(items):
                    break
                y = col_y + i * item_h + 4
                rect = pygame.Rect(x + 4, y, col_w - 8, item_h - 4)
                selected = idx == sel_idx
                hover = rect.collidepoint(mouse)
                bg = sel_bg if selected else (hover_bg if hover else item_bg)
                pygame.draw.rect(SCREEN, bg, rect, border_radius=4)
                label = items[idx]
                surf = font.render(label, True, text_col)
                SCREEN.blit(surf, (rect.x + 8, rect.y + (rect.h - surf.get_height()) // 2))

        # ── Get display name helper ───────────────────────
        def display_name(value):
            for p in list_packs():
                if p["value"] == value:
                    return p["label"]
            return value

        # ── Left column: Available ─────────────────────────
        avail_labels = [display_name(p) for p in avail]
        left_label = label_font.render(theme.string("pack_select.available", "BESCHIKBAAR"), True, sub_col)
        SCREEN.blit(left_label, (left_x + col_w // 2 - left_label.get_width() // 2, col_y - 28))
        self._pack_sel_avail_scroll = max(0, min(self._pack_sel_avail_scroll, max(0, len(avail) - visible)))
        draw_column(avail_labels, left_x, self._pack_sel_avail_scroll, self._pack_sel_avail_idx)

        # ── Right column: Active ───────────────────────────
        active_labels = [f"{i + 1}. {display_name(p)}" for i, p in enumerate(self._working_packs)]
        right_label = label_font.render(theme.string("pack_select.active", "ACTIEF"), True, sub_col)
        SCREEN.blit(right_label, (right_x + col_w // 2 - right_label.get_width() // 2, col_y - 28))
        self._pack_sel_active_scroll = max(0, min(self._pack_sel_active_scroll, max(0, len(self._working_packs) - visible)))
        draw_column(active_labels, right_x, self._pack_sel_active_scroll, self._pack_sel_active_idx)

        # ── Arrow buttons (→ add, ← remove) ────────────────
        arr_btn_h = int(item_h * 0.6)
        arr_btn_w = arr_w
        center_y = col_y + col_h // 2
        left_btn = pygame.Rect(arr_x, center_y - arr_btn_h - 4, arr_btn_w, arr_btn_h)
        right_btn = pygame.Rect(arr_x, center_y + 4, arr_btn_w, arr_btn_h)
        def draw_arr_btn(rect, direction, enabled):
            hover = rect.collidepoint(mouse)
            pygame.draw.rect(SCREEN, arr_hov if hover else arr_idle, rect, border_radius=4)
            if enabled:
                _draw_arrow(SCREEN, rect, direction, arrow_col)
        draw_arr_btn(left_btn, 'right', bool(avail))
        draw_arr_btn(right_btn, 'left', bool(self._working_packs))

        # ── Priority up/down buttons ───────────────────────
        prio_btn_h = int(item_h * 0.5)
        def draw_prio_btn(rect, direction, enabled):
            hover = rect.collidepoint(mouse)
            pygame.draw.rect(SCREEN, arr_hov if hover else arr_idle, rect, border_radius=4)
            if enabled:
                _draw_arrow(SCREEN, rect, direction, arrow_col)
        up_rect = pygame.Rect(prio_x, col_y + int(item_h * 0.3), prio_w, prio_btn_h)
        dn_rect = pygame.Rect(prio_x, col_y + col_h - int(item_h * 0.3) - prio_btn_h, prio_w, prio_btn_h)
        has_multiple = len(self._working_packs) > 1
        draw_prio_btn(up_rect, 'up', has_multiple)
        draw_prio_btn(dn_rect, 'down', has_multiple)

        # ── Event handling ──────────────────────────────────
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                def hit_column(items, x, scroll, sel_attr):
                    for i in range(visible):
                        idx = scroll + i
                        if idx >= len(items):
                            break
                        y = col_y + i * item_h + 4
                        rect = pygame.Rect(x + 4, y, col_w - 8, item_h - 4)
                        if rect.collidepoint(mouse):
                            setattr(self, sel_attr, idx)
                            return True
                    return False

                hit_column(avail, left_x, self._pack_sel_avail_scroll, '_pack_sel_avail_idx')
                hit_column(self._working_packs, right_x, self._pack_sel_active_scroll, '_pack_sel_active_idx')

                if avail and left_btn.collidepoint(mouse):
                    p = avail[self._pack_sel_avail_idx]
                    self._working_packs.append(p)
                    self._pack_sel_active_idx = len(self._working_packs) - 1

                if self._working_packs and right_btn.collidepoint(mouse):
                    idx = self._pack_sel_active_idx
                    self._working_packs.pop(idx)
                    if self._pack_sel_active_idx >= len(self._working_packs):
                        self._pack_sel_active_idx = max(0, len(self._working_packs) - 1)

                if len(self._working_packs) > 1 and up_rect.collidepoint(mouse):
                    idx = self._pack_sel_active_idx
                    if idx > 0:
                        self._working_packs[idx], self._working_packs[idx - 1] = \
                            self._working_packs[idx - 1], self._working_packs[idx]
                        self._pack_sel_active_idx = idx - 1
                if len(self._working_packs) > 1 and dn_rect.collidepoint(mouse):
                    idx = self._pack_sel_active_idx
                    if idx < len(self._working_packs) - 1:
                        self._working_packs[idx], self._working_packs[idx + 1] = \
                            self._working_packs[idx + 1], self._working_packs[idx]
                        self._pack_sel_active_idx = idx + 1

            if ev.type == pygame.MOUSEWHEEL:
                if pygame.Rect(left_x, col_y, col_w, col_h).collidepoint(mouse):
                    self._pack_sel_avail_scroll -= ev.y
                if pygame.Rect(right_x, col_y, col_w, col_h).collidepoint(mouse):
                    self._pack_sel_active_scroll -= ev.y

        # ── Back / Confirm ──────────────────────────────────
        def confirm():
            GAME.Menu.draw_loading_screen(0, "Applying packs...")
            pygame.event.pump()
            save_active_packs(self._working_packs)
            set_packs(self._working_packs)
            GAME.reload_all_assets()
            back_target = getattr(GAME, '_settings_return', 'menu')
            GAME.state = back_target
            if back_target == "game":
                pygame.mouse.set_visible(False)
                pygame.event.set_grab(True)
                pygame.mixer.unpause()
                GAME.main_music.play()
            elif back_target == "paused":
                pygame.mouse.set_visible(True)
                pygame.event.set_grab(False)
                GAME.main_music.play()
            else:
                pygame.mouse.set_visible(True)
                pygame.event.set_grab(False)
            GAME._settings_return = "menu"
        self._draw_main_button(events, theme.string("button.back", "TERUG"),
            HEIGHT - int(HEIGHT * theme.pos("menu.title_y", 0.08)),
            int(WIDTH * 0.11), confirm, font_size=34)

    def draw_credits(self, events, GAME):
        self.game = GAME
        self._fill_bg()

        y = self.credits_height
        x = WIDTH // 4
        white = "white"

        self.title_font = load_font(theme.size("credits.title_font", int(HEIGHT * 0.29)), bold=True)
        title_surf = self.title_font.render(theme.string("menu.title", "GUNK"), True, white)
        SCREEN.blit(title_surf, (WIDTH // 2 - title_surf.get_width() // 2, y))

        self.text_font = load_font(int(HEIGHT * theme.pos("mp.title_y", 0.04)))
        lines = [
            ("Developed by:", int(HEIGHT * theme.pos("credits.dev_label_y", 0.27))),
            ("Kobe Motmans", int(HEIGHT * theme.pos("credits.kobe_y", 0.31))),
            ("Andreas Meuwissen", int(HEIGHT * theme.pos("credits.andreas_y", 0.35))),
            ("Ruben Verreth", int(HEIGHT * theme.pos("credits.ruben_y", 0.39))),
            ("Music by:", int(HEIGHT * theme.pos("credits.music_label_y", 0.47))),
            ("Rube van der Wielen", int(HEIGHT * theme.pos("credits.rube_y", 0.50))),
            ("Special thanks to:", int(HEIGHT * theme.pos("credits.thanks_label_y", 0.58))),
            ("Andrei", int(HEIGHT * theme.pos("credits.andrei_y", 0.62))),
            ("Ahmed", int(HEIGHT * theme.pos("credits.ahmed_y", 0.66))),
            ("Ruben", int(HEIGHT * theme.pos("credits.ruben2_y", 0.70))),
            ("Jan", int(HEIGHT * theme.pos("credits.jan_y", 0.74))),
            ("Bilal", int(HEIGHT * theme.pos("credits.bilal_y", 0.78))),
        ]

        for text, offset in lines:
            SCREEN.blit(
                self.text_font.render(text, False, white),
                (x, y + offset)
            )

        self.credits_height -= theme.size("credits.scroll_speed", 2)
        if self.credits_height < -int(HEIGHT * theme.pos("credits.scroll_reset", 0.87)):
            self.credits_height = HEIGHT

        btn_w = int(WIDTH * 0.07)
        btn_h = theme.size("credits.btn_h", int(HEIGHT * 0.06))
        Menu_button = Button(
            WIDTH // 2 - btn_w // 2,
            self.credits_height + HEIGHT // 2 - int(HEIGHT * theme.pos("credits.btn_y_offset1", 0.03)) + int(HEIGHT * theme.pos("credits.btn_y_offset2", 0.52)),
            btn_w, btn_h, theme.string("button.menu", "MENU"), 35,
            text_color="black", button_color="white",
            hover_text_color="white", hover_button_color="black",
            game=self.game, target_state="menu"
        )
        Menu_button.draw_button(events)
        
    def draw_UI(self, events):
        self.fps_font = load_numeric_font(theme.size("hud.fps_font", 20), bold=True)
        self.hp_font = load_numeric_font(int(HEIGHT * theme.pos("menu.title_y", 0.08)), bold=True)
        SCREEN.blit(self.fps_font.render(f"{round(self.game.clock.get_fps())}", True, theme.color("hud.fps", 'green')),(int(WIDTH * theme.pos("hud.fps_x", 0.01)), int(HEIGHT * theme.pos("hud.fps_y", 0.02))))
        SCREEN.blit(self.hp_font.render(f"{round(self.game.global_health)}/{START_HEALTH}", True, theme.color("hud.hp", 'red')),(WIDTH - int(WIDTH * theme.pos("hud.hp_x", 0.15)), int(HEIGHT * theme.pos("hud.hp_y", 0.02))))
        SCREEN.blit(self.hp_font.render(f"{round(self.game.global_ammo)}/{AMMO_CAP}", True, theme.color("hud.ammo", 'grey')),(int(WIDTH * theme.pos("hud.ammo_x", 0.01)), HEIGHT - int(HEIGHT * theme.pos("hud.ammo_y", 0.1))))
        in_transition = getattr(self.game, 'elevator_transition', False)
        door_open = getattr(self.game, 'player', None) and self.game.player.door_pos != 0
        if getattr(self.game, 'elevator_waiting', False) and not in_transition and not door_open:
            warn_font = load_numeric_font(theme.size("hud.warning_font", 36))
            elev_ready = getattr(self.game, 'elevator_ready', False)
            wait_timer = getattr(self.game, 'elevator_wait_timer', 0)
            player_near = getattr(self.game, 'player_near_exit', False)
            if elev_ready and wait_timer > 0:
                msg = theme.string("hud.elevator_countdown", "Lift vertrekt in {seconds}...").format(seconds=wait_timer//60 + 1)
                color = theme.color("hud.warning_elevator", (255, 200, 0))
            elif not player_near:
                msg = theme.string("hud.elevator_go", "GA NAAR DE LIFT!")
                color = theme.color("hud.warning_danger", (255, 80, 80))
            else:
                msg = theme.string("hud.elevator_wait", "Wacht op teamgenoten...")
                color = theme.color("hud.warning_info", (200, 200, 80))
            warn_surf = warn_font.render(msg, True, color)
            SCREEN.blit(warn_surf, (WIDTH//2 - warn_surf.get_width()//2, HEIGHT//2 - int(HEIGHT * theme.pos("hud.elevator_warn_y", 0.19))))
    def draw_paused_screen(self, events, GAME):
        self.game = GAME
        c = WIDTH//2
        def resume():
            pygame.mouse.set_visible(False)
            pygame.event.set_grab(True)
            GAME.state = "game"
            pygame.mixer.unpause()
        self._draw_main_button(events, theme.string("button.resume", "RESUME"), HEIGHT//2 - int(HEIGHT * theme.pos("pause.resume_y", 0.1)), int(WIDTH * 0.11), resume, font_size=34)

        def open_settings():
            GAME._settings_return = "paused"
            GAME.state = "settings"
        self._draw_main_button(events, theme.string("settings.title", "SETTINGS"), HEIGHT//2 - int(HEIGHT * theme.pos("pause.settings_y", 0.02)), int(WIDTH * 0.11), open_settings, font_size=34)

        def go_menu():
            pygame.mixer.stop()
            if GAME.multiplayer:
                GAME._disconnect()
            else:
                GAME.state = "menu"
        self._draw_main_button(events, theme.string("button.menu", "MENU"), HEIGHT//2 + int(HEIGHT * theme.pos("pause.menu_y", 0.06)), int(WIDTH * 0.11), go_menu, font_size=34)
    def draw_elevator(self, events, player):
        game = getattr(self, 'game', None)
        if game is None:
            return
        is_client = game.multiplayer
        elev_color = theme.color("elevator")
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
                        game.sounds["elev_ding"].set_volume(game.sfx_volume)
                        game.sounds["elev_ding"].play()
                self.lift_time -= 1
                if is_client:
                    player.door_pos += ELEV_SPEED
            else:
                if not is_client:
                    pygame.mixer.stop()
                    game.player.door_pos += ELEV_SPEED
                    game.escaped = True
                    game.sounds["victory"].set_volume(game.sfx_volume)
                    game.sounds["victory"].play()
                    pygame.mouse.set_visible(True)
                    pygame.event.set_grab(False)
                else:
                    player.door_pos += ELEV_SPEED

        elif WIDTH/2 + ELEV_SPEED <= player.door_pos < WIDTH:
            pygame.draw.rect(SCREEN,self.elev_color,[0,0,WIDTH-player.door_pos,HEIGHT])
            pygame.draw.rect(SCREEN,self.elev_color,[player.door_pos,0,WIDTH-player.door_pos,HEIGHT])
            player.door_pos += ELEV_SPEED

        elif player.door_pos >= WIDTH:
            if not game.escaped and not game.elevator_transition:
                player.door_pos = 0
            self.lift_time = ELEV_TIME
    def draw_dead_screen(self,events,GAME):
        self.game = GAME
        self.title_font = load_font(theme.size("dead.title_font", int(HEIGHT * 0.19)), bold=True)
        SCREEN.blit(SCREEN_DEAD, (0,0))
        self.score_font = load_numeric_font(int(HEIGHT * theme.pos("menu.title_y", 0.08)), bold=True)
        btn_w = int(WIDTH * 0.07)
        btn_h = theme.size("credits.btn_h", int(HEIGHT * 0.06))
        Menu_button = Button(WIDTH // 2 - btn_w // 2, HEIGHT // 2 - btn_h // 2 + int(HEIGHT * theme.pos("dead.btn_y", 0.1)),
            btn_w, btn_h, theme.string("button.menu", "MENU"), 35,
            text_color="black", button_color="white",
            hover_text_color="white", hover_button_color="black",
            game=self.game, target_state="menu", function="disconnect")
        Menu_button.draw_button(events)
        score_surf = self.score_font.render(theme.string("hud.score_format", "Score:{score}").format(score=self.game.player.score), True, theme.color("hud.score_dead", 'black'))
        SCREEN.blit(score_surf, (WIDTH//2 - score_surf.get_width()//2, HEIGHT//2 - int(HEIGHT * theme.pos("mp.title_y", 0.04))))
        title_surf = self.title_font.render(theme.string("hud.game_over", "GAME OVER"), True, theme.color("hud.title_dead", 'black'))
        SCREEN.blit(title_surf, (WIDTH//2 - title_surf.get_width()//2, HEIGHT//3 - int(HEIGHT * theme.pos("dead.title_y", 0.05))))
        
    def draw_escaped_screen(self,events,GAME):
        self.game = GAME
        self.endscreen_font = load_font(theme.size("escaped.title_font", int(HEIGHT * 0.15)), bold=True)
        self.score_font = load_numeric_font(int(HEIGHT * theme.pos("menu.title_y", 0.08)), bold=True)
        SCREEN.blit(VICTORY_SCREEN, (0,0))
        pygame.mouse.set_visible(True)
        s1 = self.endscreen_font.render(theme.string("hud.escaped_title_1", "SUCCESFUL"), True, theme.color("hud.title_escaped", 'white'))
        s2 = self.endscreen_font.render(theme.string("hud.escaped_title_2", "ESKAPE"), True, theme.color("hud.title_escaped", 'white'))
        score_surf = self.score_font.render(theme.string("hud.score_format", "Score:{score}").format(score=self.game.player.score), True, theme.color("hud.score_escaped", 'white'))
        SCREEN.blit(s1, (WIDTH//2 - s1.get_width()//2, HEIGHT//2 - int(HEIGHT * theme.pos("escaped.line1_y", 0.45))))
        SCREEN.blit(s2, (WIDTH//2 - s2.get_width()//2, HEIGHT//2 - int(HEIGHT * theme.pos("escaped.line2_y", 0.27))))
        SCREEN.blit(score_surf, (WIDTH//2 - score_surf.get_width()//2, HEIGHT//2 + int(HEIGHT * theme.pos("escaped.score_y", 0.01))))
        btn_w = int(WIDTH * 0.07)
        btn_h = theme.size("credits.btn_h", int(HEIGHT * 0.06))
        Menu_button = Button(WIDTH // 2 - btn_w // 2, HEIGHT // 2 - btn_h // 2 + int(HEIGHT * theme.pos("escaped.btn_y", 0.15)),
            btn_w, btn_h, theme.string("button.menu", "MENU"), 35,
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
                GAME.save_settings()
            self.volume_slider = Slider(
                self._slider_center_x(int(WIDTH * 0.21)), int(HEIGHT * theme.pos("slider.music_y", 0.37)),
                int(WIDTH * 0.21), int(HEIGHT * 0.01),
                min_val=0.0, max_val=1.0, initial_val=GAME.music_volume,
                label=theme.string("settings.music_volume", "MUSIC VOLUME"), game=GAME,
                on_change=on_music_change
                )
        return self.volume_slider

    def get_sfx_volume_slider(self, GAME):
        if self.sfx_volume_slider is None:
            def on_sfx_change(val):
                GAME.sfx_volume = val
                GAME.update_sfx_volume()
                GAME.save_settings()
            self.sfx_volume_slider = Slider(
                self._slider_center_x(int(WIDTH * 0.21)), int(HEIGHT * theme.pos("slider.sfx_y", 0.44)),
                int(WIDTH * 0.21), int(HEIGHT * 0.01),
                min_val=0.0, max_val=1.0, initial_val=getattr(GAME, 'sfx_volume', 0.3),
                label=theme.string("settings.sfx_volume", "SFX VOLUME"), game=GAME,
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
        self.font = load_font(text_size, bold=True)

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
                        self.GAME.save_settings()
                    elif self.function == "res_low":
                        set_resolution("low")
                        self.GAME.resolution = "low"
                        self.GAME.save_settings()
                    elif self.function == "tutorial":
                        self.GAME.bilal.flags["general"] = not self.GAME.bilal.flags["general"]
                        self.GAME.save_settings()
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
        pygame.draw.rect(SCREEN, bg, self.rect, border_radius=theme.size("button.border_radius", 6))
        text_surf = self.font.render(self.text, True, fg)
        tx = self.rect.x + (self.rect.w - text_surf.get_width()) // 2
        ty = self.rect.y + (self.rect.h - text_surf.get_height()) // 2
        SCREEN.blit(text_surf, (tx, ty))

class Dropdown:
    @staticmethod
    def _expand_color(): return theme.color("dropdown.expand_color", (50, 60, 120))
    @staticmethod
    def _option_hover(): return theme.color("dropdown.option_hover", (70, 70, 90))
    @staticmethod
    def _option_bg(): return theme.color("dropdown.option_bg", (50, 50, 60))
    @staticmethod
    def _option_selected(): return theme.color("dropdown.option_selected", (40, 80, 120))
    @staticmethod
    def _border(): return theme.color("dropdown.border", (150, 150, 150))

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
        font = load_font(int(self.h * 0.5), bold=True)

        # Main box
        bg = Dropdown._expand_color() if self.expanded else (theme.color("dropdown.hover_bg", (60, 60, 70)) if hover else theme.color("dropdown.bg", (40, 40, 40)))
        pygame.draw.rect(SCREEN, bg, main_rect, border_radius=6)
        pygame.draw.rect(SCREEN, Dropdown._border(), main_rect, 2, border_radius=6)

        # Selected text
        label = self.options[self.selected_index]["label"]
        text_surf = font.render(label, True, theme.color("dropdown.text", 'white'))
        SCREEN.blit(text_surf, (self.x + 10, self.y + (self.h - text_surf.get_height()) // 2))

        # Arrow (drawn triangle to avoid unicode font issues)
        ax = self.x + self.w - 18
        ay = self.y + self.h // 2
        if self.expanded:
            pygame.draw.polygon(SCREEN, theme.color("dropdown.arrow", 'white'), [(ax, ay + 5), (ax - 6, ay - 4), (ax + 6, ay - 4)])
        else:
            pygame.draw.polygon(SCREEN, theme.color("dropdown.arrow", 'white'), [(ax, ay - 5), (ax - 6, ay + 4), (ax + 6, ay + 4)])

        # Expanded options
        if self.expanded:
            opt_y = self.y + self.h + 4
            for i, opt in enumerate(self.options):
                opt_rect = pygame.Rect(self.x, opt_y, self.w, self.h)
                opt_hover = opt_rect.collidepoint(mouse)
                bg2 = Dropdown._option_selected() if i == self.selected_index else (Dropdown._option_hover() if opt_hover else Dropdown._option_bg())
                pygame.draw.rect(SCREEN, bg2, opt_rect, border_radius=4)
                pygame.draw.rect(SCREEN, Dropdown._border(), opt_rect, 1, border_radius=4)
                opt_surf = font.render(opt["label"], True, theme.color("dropdown.text", 'white'))
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
        current = TEXTURE_PACKS[0] if TEXTURE_PACKS else None
        for i, opt in enumerate(self.options):
            if opt["value"] == current:
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
        self.handle_r = theme.size("slider.handle_r", height)


    def get_handle_x(self):
        ratio = (self.value - self.min_val) / (self.max_val - self.min_val)
        return self.track_x + ratio * self.w

    def draw(self, events):
        self.font = load_numeric_font(theme.size("slider.label_font", int(HEIGHT * 0.02)))
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

        pygame.draw.rect(SCREEN, theme.color("slider.track", 'white'), [self.track_x, self.track_y - 4, self.w, 8], border_radius=4)

        filled_w = self.get_handle_x() - self.track_x
        pygame.draw.rect(SCREEN, theme.color("slider.fill", (0, 200, 255)), [self.track_x, self.track_y - 4, filled_w, 8], border_radius=4)

        handle_x = self.get_handle_x()
        pygame.draw.circle(SCREEN, theme.color("slider.handle_drag", (0, 200, 255)) if self.dragging else theme.color("slider.handle", 'white'), (int(handle_x), int(self.track_y)), self.handle_r)

        label_surf = self.font.render(f"{self.label}: {int(self.value * 100)}%", True, theme.color("slider.label", 'white'))
        SCREEN.blit(label_surf, (self.track_x, self.track_y - int(HEIGHT * theme.pos("mp.title_y", 0.04))))


# ---- Het grootste deel hiervan is AI code, eerder flavour en tutorial dan functionele game code-----
class Tekstballon:
    def __init__(self, text, y_pos, x_pos, GAME, max_width=280, padding=10,):
        self.text = text
        self.y_pos = y_pos
        self.x_pos = x_pos
        self.max_width = max_width
        self.padding = padding
        self.font = load_font(theme.size("speech_bubble.font", 20))
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
            theme.color("speech_bubble.border", (0, 0, 0)),
            [x - 4, y - 4, box_w + 8, box_h + 8],
            border_radius=8
        )
        pygame.draw.rect(
            SCREEN,
            theme.color("speech_bubble.bg", (255, 255, 255)),
            [x, y, box_w, box_h],
            border_radius=8
        )

        for i, line in enumerate(raw_lines):
            SCREEN.blit(
                self.font.render(line, False, theme.color("speech_bubble.text", (0, 0, 0))),
                (x + self.padding, y + self.padding + i * line_height)
            )

        tail_x = x + box_w // 2
        tail_y = y + box_h

        pygame.draw.polygon(
            SCREEN,
            theme.color("speech_bubble.tail_outer", (0, 0, 0)),
            [(tail_x - 12, tail_y),
             (tail_x + 12, tail_y),
             (tail_x, tail_y + 22)]
        )
        pygame.draw.polygon(
            SCREEN,
            theme.color("speech_bubble.tail_inner", (255, 255, 255)),
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
            Tekstballon(text, HEIGHT - int(HEIGHT * theme.pos("speech_bubble.y", 0.43)), int(WIDTH * theme.pos("speech_bubble.x", 0.01)), self.Game).draw()
            SCREEN.blit(TUTORIAL, (0, HEIGHT - int(HEIGHT * theme.pos("tutorial.image_y", 0.33))))

    def trigger(self, event_name):
        if self.flags.get(event_name):
            return

        self.flags[event_name] = True

        if event_name == "seen_enemy":
            self.interrupt(
                theme.string("tutorial.seen_enemy",
                    "Pas op, de assistenten proberen je ontsnapping tegen te houden! "
                    "Je zal ze moeten neerschieten met linker-muisklik!")
            )

        elif event_name == "monster":
            self.interrupt(
                theme.string("tutorial.monster",
                    "Door Monster Energy te drinken krijg je twee HP terug!"), 200
            )

        elif event_name == "keycard":
            self.interrupt(
                theme.string("tutorial.keycard",
                    "Daar ligt de keycard! Breng hem naar de lift en verdwijn van deze verdieping")
            )

        elif event_name == "boss_warning":
            self.interrupt(
                theme.string("tutorial.boss_warning",
                    "Daar is Jan! Dit is je kans om hier een einde aan te maken!")
            )

        elif event_name == "floor_3":
            self.say(
                theme.string("tutorial.floor_3",
                    "We zijn op verdieping 3 geraakt. Je hebt ook een minigun gevonden "
                    "op verdieping 4. Duw op A om te wisselen"),
                400
            )

        elif event_name == "floor_1":
            self.say(
                theme.string("tutorial.floor_1",
                    "Net wanneer we hier binnenkwamen lag hier een rifle. Zoek hem via A.")
            )

        elif event_name == "floor_0":
            self.say(
                theme.string("tutorial.floor_0_a",
                    "Dit is verdieping 0. Er is wel een probleempje. Jan is hier, en hij heeft de laatste keycard.")
            )
            self.say(
                theme.string("tutorial.floor_0_b",
                    "Je kan hem vinden in de garage. Maar pas op, hij is heel erg sterk!")
            )
