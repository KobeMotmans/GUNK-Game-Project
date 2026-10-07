import os
import math
import pygame
import tkinter as tk
from tkinter import filedialog
from ..core import config as _cfg
from ..core.config import set_resolution, START_HEALTH, AMMO_CAP, ELEV_SPEED, MAX_LEVEL, ELEV_TIME, DEFAULT_PORT, TILE_SIZE
from ..core.paths import list_packs, set_packs, save_active_packs, TEXTURE_PACKS, load_font, load_numeric_font, resolve_asset
from ..core.theme import theme
from ..core import audio
from collections import deque
from ..core.map_loader import M, WALL_VALUES
from ..core.minimap import UIT as MINIMAP_UIT, GEZIEN as MINIMAP_GEZIEN, VOLLEDIG as MINIMAP_VOLLEDIG
from ..assets.skin_manager import SkinManager
from ..network.network import NetworkClient
from ..network.discovery import DiscoveryListener

# ── schalen met de resolutie ──────────────────────────────────
#
# De posities in dit bestand zijn fracties van WIDTH/HEIGHT, maar de
# fontgrotes stonden als losse pixels (16, 22, 36). Op 1920x1080 past dat
# toevallig precies; bij 1024x768 of 800x600 blijven de letters even groot
# terwijl de kaders krimpen, en dan loopt de tekst over elkaar heen of uit
# beeld. `base_px` is de maat op 1080p, dus op een Full HD-scherm verandert
# er niets aan het uiterlijk.
REF_HEIGHT = 1080.0


def _scale_px(base_px, ref="min"):
    """Reken een maat op 1080p om naar de huidige resolutie."""
    fractie = base_px / REF_HEIGHT
    if ref == "width":
        return int(_cfg.WIDTH * fractie)
    if ref == "height":
        return int(_cfg.HEIGHT * fractie)
    return int(min(_cfg.WIDTH, _cfg.HEIGHT) * fractie)


def _font_px(key, base_px, ref="min"):
    """Fontmaat die met de resolutie meegroeit.

    De key gaat naar het thema, dus een pack kan hem overriden. Let op:
    gebruik GEEN bestaande themasleutel, want theme.scaled leest de waarde als
    fractie en `sizes.input.height = 30` zou dan 30x1080 pixels betekenen.

    Module-niveau en niet als methode, omdat klassen buiten Menu (zoals
    Tekstballon) dezelfde maat nodig hebben zonder Menu te zijn.
    """
    return max(10, int(theme.scaled(key, base_px / REF_HEIGHT, ref)))


# De drie standen van de minimap, in de volgorde waarin de knop ze doorloopt.
# De teksten staan als (themasleutel, terugvaltekst) zodat een texture pack ze
# kan vertalen; de kleuren geven aan welke stand actief is.
MINIMAP_LABELS = (
    ("settings.minimap_off", "MINIMAP: OFF"),
    ("settings.minimap_seen", "MINIMAP: SEEN"),
    ("settings.minimap_all", "MINIMAP: ALL"),
)
MINIMAP_KLEUREN = ((60, 60, 70), (40, 100, 160), (120, 90, 30))


def _fit_width(surf, max_width):
    """Schalen als een regel te breed is om in beeld te passen.

    Een lange onveranderde string loopt anders aan beide kanten uit beeld,
    en dat is precies wat je op een smal scherm ziet gebeuren. Schalen is
    beter dan afkappen: de speler mist dan geen woorden.
    """
    if surf.get_width() <= max_width:
        return surf
    factor = max_width / surf.get_width()
    return pygame.transform.smoothscale(
        surf, (max(1, int(surf.get_width() * factor)), surf.get_height()))


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
        self.credits_height = _cfg.HEIGHT
        self.volume_slider = None
        self.sfx_volume_slider = None
        
        self.lift_time = ELEV_TIME
        self.loading_progress = 0
        self._minimap_vergeet()

        # Multiplayer input fields + disk cache
        netcfg = NetworkClient.load_config()
        self.mp_name_input = netcfg.get("last_name", "")
        self.mp_host_port = str(DEFAULT_PORT)
        self.mp_join_ip = netcfg.get("last_ip", "127.0.0.1")
        # De opgeslagen poort is letterlijk wat de speler vorige keer typte.
        # Gaat de server op de standaardpoort verder, dan moet dat hier
        # automatisch meebewegen anders joint iedere verse installatie op 25565.
        self.mp_join_port = netcfg.get("last_port", "") or str(DEFAULT_PORT)
        self.mp_skin_id = netcfg.get("last_skin_id", 0)
        self.input_focus = None
        self.lobby_status = ""
        self.client_list = []
        self.lobby_countdown = 0
        self.lobby_game_active = False
        self.host_pid = -1
        self.lobby_options = {"shared_health": True, "shared_ammo": True}
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
                self._bg_img = pygame.transform.scale(img, (_cfg.WIDTH, _cfg.HEIGHT))
            except Exception:
                self._bg_img = None
        else:
            self._bg_img = None
        self.bg_color = theme.color("menu.bg", (70, 70, 70))

    def _fill_bg(self):
        if self._bg_img:
            _cfg.SCREEN.blit(self._bg_img, (0, 0))
        else:
            _cfg.SCREEN.fill(self.bg_color)

    # ── schalen met de resolutie ──────────────────────────────────
    #
    # De rekenregels staan module-breed bovenaan dit bestand, zodat Button
    # en Menu dezelfde maat gebruiken. `base_px` is de maat op 1080p.
    REF_HEIGHT = REF_HEIGHT

    def _scale(self, base_px, ref="min"):
        return _scale_px(base_px, ref)

    def _font_px(self, key, base_px, ref="min"):
        return _font_px(key, base_px, ref)

    def _gap_px(self, base_px, ref="min"):
        """Ruimte tussen twee regels, die ook meeschuift met de resolutie."""
        return max(3, self._scale(base_px, ref))

    def _fit_width(self, surf, max_width):
        return _fit_width(surf, max_width)

    def draw_loading_screen(self, progress=None, label=None):
        self._fill_bg()
        loading_font = load_font(theme.size("loading.text_font", int(_cfg.HEIGHT * 0.1)), bold=True)
        load_surf = loading_font.render(theme.string("loading.text", "Loading..."), True, theme.color("text.title", 'white'))
        _cfg.SCREEN.blit(load_surf, (_cfg.WIDTH // 2 - load_surf.get_width() // 2, _cfg.HEIGHT - int(_cfg.HEIGHT * theme.pos("loading.text_y", 0.29))))

        title_font = load_font(theme.size("menu.title_font", int(_cfg.HEIGHT * 0.29)), bold=True)
        title_surf = title_font.render(theme.string("menu.title", "GUNK"), True, theme.color("text.title", 'white'))
        _cfg.SCREEN.blit(title_surf, (_cfg.WIDTH // 2 - title_surf.get_width() // 2, _cfg.HEIGHT // 2 - title_surf.get_height() // 2))

        bar_width = theme.size("loading.bar_width", int(_cfg.WIDTH * 0.31))
        bar_height = theme.size("loading.bar_height", int(_cfg.HEIGHT * 0.03))
        bar_x = _cfg.WIDTH // 2 - bar_width // 2
        bar_y = _cfg.HEIGHT - int(_cfg.HEIGHT * theme.pos("loading.bar_y", 0.15))

        pygame.draw.rect(_cfg.SCREEN, theme.color("loading.bar_bg", (80, 80, 80)), (bar_x, bar_y, bar_width, bar_height))

        if progress is not None:
            self.loading_progress = progress
        progress_width = bar_width * self.loading_progress
        pygame.draw.rect(_cfg.SCREEN, theme.color("loading.bar_fill", (0, 200, 0)), (bar_x, bar_y, progress_width, bar_height))
        if progress is None:
            self.loading_progress += 0.2

        if label:
            label_font = load_font(self._font_px("ui.font.loading_label", 16))
            label_surf = self._fit_width(label_font.render(label, True, theme.color("text.subtitle", (150, 150, 150))),
                                         int(_cfg.WIDTH * 0.8))
            _cfg.SCREEN.blit(label_surf, (_cfg.WIDTH // 2 - label_surf.get_width() // 2,
                                         bar_y + bar_height + self._gap_px(6)))

        pygame.display.flip()

    def _draw_main_button(self, events, text, y_pos, w, action=None, h=None, font_size=None, x=None):
        """Een knop uit het hoofdmenu.

        `font_size` is de maat op 1080p; hier schalen we hem om, zodat de
        aanroepers geen resolutie hoeven te kennen. 'MULTIPLAYER' paste
        anders niet eens in zijn eigen knop op een kleiner scherm.
        """
        if x is None:
            x = _cfg.WIDTH//2 - w//2
        if h is None:
            h = theme.size("menu.btn_h", int(_cfg.HEIGHT * 0.04))
        rect = pygame.Rect(x, y_pos, w, h)
        mouse = pygame.mouse.get_pos()
        hover = rect.collidepoint(mouse)
        br = theme.size("button.border_radius", 8)
        pygame.draw.rect(_cfg.SCREEN, theme.color("button.hover_bg", (100, 100, 100)) if hover else theme.color("button.bg", (70, 70, 70)), rect, border_radius=br)
        if hover:
            pygame.draw.rect(_cfg.SCREEN, theme.color("button.border", (180, 180, 180)), rect, 2, border_radius=br)
        font = load_font(self._font_px("ui.font.main_button", font_size or 28))
        tc = theme.color("button.hover_text", 'white') if hover else theme.color("button.text", 'white')
        surf = self._fit_width(font.render(text, True, tc), w - 12)
        _cfg.SCREEN.blit(surf, (x + w//2 - surf.get_width()//2, y_pos + h//2 - surf.get_height()//2))
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if rect.collidepoint(ev.pos) and action:
                    action()
                    return True
        return False

    def draw_main_menu(self, events, GAME):
        self.game = GAME
        self._fill_bg()
        title_font = load_font(theme.size("menu.title_font", int(_cfg.HEIGHT * 0.29)), bold=True)
        title_surf = title_font.render(theme.string("menu.title", "GUNK"), True, theme.color("text.title", 'white'))
        _cfg.SCREEN.blit(title_surf, (_cfg.WIDTH // 2 - title_surf.get_width() // 2, int(_cfg.HEIGHT * theme.pos("menu.title_y", 0.08))))

        c = _cfg.WIDTH//2
        btn_w = theme.size("menu.btn_wide", int(_cfg.WIDTH * 0.16))
        gap = theme.size("menu.btn_gap", int(_cfg.WIDTH * 0.03))
        self._draw_main_button(events, theme.string("menu.solo", "SOLO"), int(_cfg.HEIGHT * theme.pos("menu.solo_mp_y", 0.38)), btn_w, lambda: GAME.reset_game("campaign"), font_size=36, x=c - btn_w - gap//2)
        self._draw_main_button(events, theme.string("menu.multiplayer", "MULTIPLAYER"), int(_cfg.HEIGHT * theme.pos("menu.solo_mp_y", 0.38)), btn_w, lambda: setattr(GAME, 'state', 'multiplayer_menu'), font_size=36, x=c + gap//2)
        self._draw_main_button(events, theme.string("menu.options", "OPTIONS"), int(_cfg.HEIGHT * theme.pos("menu.options_y", 0.47)), int(_cfg.WIDTH * 0.11), lambda: setattr(GAME, 'state', 'settings'), font_size=36)
        self._draw_main_button(events, theme.string("menu.credits", "CREDITS"), int(_cfg.HEIGHT * theme.pos("menu.credits_y", 0.54)), int(_cfg.WIDTH * 0.11), lambda: setattr(GAME, 'state', 'credits'), font_size=36)
        self._draw_main_button(events, theme.string("menu.quit", "QUIT"), int(_cfg.HEIGHT * theme.pos("menu.quit_y", 0.62)), int(_cfg.WIDTH * 0.11), lambda: setattr(GAME, 'running', False), font_size=36)
    # --- Multiplayer UI ----------------------------------------

    def _draw_text_input(self, events, label, current_text, x, y, width, height=None, field_id=None, numeric=False):
        """Draw a text input field. Returns the (possibly updated) text."""
        text_px = self._font_px("input.text_font_px", 22)
        if height is None:
            # Een vast aantal pixels blijft op een smallere resolutie te hoog
            # voor de letter, dus de hoogte volgt de font.
            height = max(20, int(text_px * 1.4))
        mouse = pygame.mouse.get_pos()
        rect = pygame.Rect(x, y, width, height)

        label_font = load_font(self._font_px("input.label_font_px", 22))
        label_surf = label_font.render(label, True, theme.color("text.title", 'white'))
        if label_surf.get_width():
            _cfg.SCREEN.blit(label_surf, (x, y - label_surf.get_height() - self._gap_px(3)))

        focused = self.input_focus == field_id
        bg_color = theme.color("input.focus_bg", (60, 60, 80)) if focused else theme.color("input.bg", (40, 40, 40))
        pygame.draw.rect(_cfg.SCREEN, bg_color, rect, border_radius=4)
        pygame.draw.rect(_cfg.SCREEN, theme.color("input.focus_border", (180, 180, 255)) if focused else theme.color("input.border", (100, 100, 100)), rect, 2, border_radius=4)

        font = load_numeric_font(text_px)
        display_text = current_text + ("|" if focused else "")
        text_surf = font.render(display_text, True, theme.color("text.title", 'white'))
        # Een lang adres of een lange zoekterm moet niet over de rand heen.
        text_surf = self._fit_width(text_surf, width - self._gap_px(10))
        _cfg.SCREEN.blit(text_surf, (x + self._gap_px(6), y + (height - text_surf.get_height()) // 2))

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
        pygame.draw.rect(_cfg.SCREEN, bg, rect, border_radius=br)
        if hover:
            pygame.draw.rect(_cfg.SCREEN, theme.color("button.border", (180, 180, 180)), rect, 2, border_radius=br)
        font = load_font(self._font_px("mp.font.button", 28))
        tc = theme.color("button.hover_text", 'white') if hover else theme.color("button.text", 'white')
        surf = font.render(text, True, tc)
        # Blijft de tekst breder dan de knop, dan schalen we hem mee. Anders
        # stak 'HOST SERVER' op een smallere resolutie over de buurknop heen.
        surf = self._fit_width(surf, w - 12)
        _cfg.SCREEN.blit(surf, (x + w//2 - surf.get_width()//2, y + h//2 - surf.get_height()//2))
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if rect.collidepoint(mouse) and enabled:
                    action()
                    return True
        return False

    def draw_multiplayer_menu(self, events, GAME):
        self.game = GAME
        self._fill_bg()

        # Eén luisteraar voor het leven van het spel: die blijft op de
        # ontdekkingspoort zitten zodat de lijst meteen gevuld is zodra je
        # hier binnenkomt.
        if getattr(GAME, "discovery_listener", None) is None:
            GAME.discovery_listener = DiscoveryListener()
            GAME.discovery_listener.start()

        join_font = load_font(self._font_px("mp.font.title", 36))
        join_label = join_font.render(theme.string("multiplayer.title", "JOIN SERVER"), True, theme.color("text.title", 'white'))
        _cfg.SCREEN.blit(join_label, (_cfg.WIDTH//2 - join_label.get_width()//2, int(_cfg.HEIGHT * theme.pos("mp.title_y", 0.04))))

        # De host draait run_server.py in een eigen venster; dat venster
        # drukt het adres af waarmee je hier moet verbinden. Zeg dat zo
        # duidelijk mogelijk, anders zoekt iedereen het IP-veld.
        info_lines = [
            theme.string("multiplayer.info", "Host: start python run_server.py in een eigen venster"),
            theme.string("multiplayer.info_hint",
                         "Typ hieronder het adres dat dat venster afdrukt (LAN werkt alleen op hetzelfde netwerk)"),
        ]
        info_font_px = self._font_px("mp.font.info", 16)
        info_y = int(_cfg.HEIGHT * theme.pos("menu.title_y", 0.08))
        for line in info_lines:
            info = load_font(info_font_px).render(line, True, theme.color("text.info", (150, 150, 150)))
            # Te breed voor het scherm? Dan kleiner, anders loopt de regel
            # aan beide kanten uit beeld (op 800x600 was dat 870 op 800 px).
            info = self._fit_width(info, _cfg.WIDTH * 0.94)
            _cfg.SCREEN.blit(info, (_cfg.WIDTH//2 - info.get_width()//2, info_y))
            info_y += info.get_height() + self._gap_px(4)

        label_font_px = self._font_px("mp.font.label", 22)
        name_label = load_font(label_font_px).render(theme.string("multiplayer.name_label", "JOUW NAAM"), True, theme.color("text.subtitle", (200, 200, 200)))
        _cfg.SCREEN.blit(name_label, (_cfg.WIDTH//2 - name_label.get_width()//2, int(_cfg.HEIGHT * theme.pos("mp.name_label_y", 0.13))))
        self.mp_name_input = self._draw_text_input(events, "", self.mp_name_input, _cfg.WIDTH//2 - int(_cfg.WIDTH * 0.09), int(_cfg.HEIGHT * theme.pos("mp.name_input_y", 0.16)), int(_cfg.WIDTH * 0.18), field_id="mp_name")

        small_label_px = self._font_px("mp.font.small_label", 20)
        ip_label = load_font(small_label_px).render(theme.string("multiplayer.ip_label", "SERVER IP"), True, theme.color("text.subtitle", (200, 200, 200)))
        _cfg.SCREEN.blit(ip_label, (_cfg.WIDTH//2 - ip_label.get_width()//2, int(_cfg.HEIGHT * theme.pos("mp.ip_label_y", 0.22))))
        self.mp_join_ip = self._draw_text_input(events, "", self.mp_join_ip, _cfg.WIDTH//2 - int(_cfg.WIDTH * 0.09), int(_cfg.HEIGHT * theme.pos("mp.ip_input_y", 0.25)), int(_cfg.WIDTH * 0.18), field_id="mp_join_ip")

        port_label = load_font(small_label_px).render(theme.string("multiplayer.port_label", "POORT"), True, theme.color("text.subtitle", (200, 200, 200)))
        _cfg.SCREEN.blit(port_label, (_cfg.WIDTH//2 - port_label.get_width()//2, int(_cfg.HEIGHT * theme.pos("mp.port_label_y", 0.31))))
        self.mp_join_port = self._draw_text_input(events, "", self.mp_join_port, _cfg.WIDTH//2 - int(_cfg.WIDTH * 0.09), int(_cfg.HEIGHT * theme.pos("mp.port_input_y", 0.34)), int(_cfg.WIDTH * 0.18), field_id="mp_join_port", numeric=True)

        def join(ip, port):
            name = self.mp_name_input.strip() or theme.string("multiplayer.default_name", "Player")
            GAME._do_connect(ip, port, name)

        def do_connect():
            ip = self.mp_join_ip.strip() or "127.0.0.1"
            try:
                port = int(self.mp_join_port) if self.mp_join_port else DEFAULT_PORT
            except ValueError:
                port = DEFAULT_PORT
            join(ip, port)

        # Twee knoppen naast elkaar: meespelen of zelf hosten. Zelf hosten
        # hoeft geen tweede venster en geen commando's, want de server
        # draait in dit proces mee.
        btn_w = int(_cfg.WIDTH * 0.12)
        btn_h = int(_cfg.HEIGHT * 0.05)
        gap = int(_cfg.WIDTH * 0.02)
        join_x = (_cfg.WIDTH - (2 * btn_w + gap)) // 2
        btn_y = int(_cfg.HEIGHT * theme.pos("mp.join_btn_y", 0.40))

        def do_host():
            try:
                port = int(self.mp_join_port) if self.mp_join_port else DEFAULT_PORT
            except ValueError:
                port = DEFAULT_PORT
            name = self.mp_name_input.strip() or theme.string("multiplayer.default_name", "Player")
            self.mp_status = theme.string("multiplayer.hosting", "Server gestart, verbinden...")
            GAME._do_host(port, name)

        self._draw_button_custom(events, theme.string("multiplayer.join", "JOIN GAME"),
                                 join_x, btn_y, btn_w, btn_h, do_connect)
        self._draw_button_custom(events, theme.string("multiplayer.host", "HOST SERVER"),
                                 join_x + btn_w + gap, btn_y, btn_w, btn_h, do_host)

        # ── Servers die zich op het eigen netwerk hebben gemeld ──
        self._draw_lan_servers(events, GAME, int(_cfg.HEIGHT * 0.52), join)

        if self.mp_status:
            color = theme.color("text.success", (0, 200, 0)) if "gelukt" in self.mp_status else theme.color("text.fail", (200, 0, 0))
            status = load_font(self._font_px("mp.font.status", 22)).render(self.mp_status, True, color)
            _cfg.SCREEN.blit(status, (_cfg.WIDTH//2 - status.get_width()//2, int(_cfg.HEIGHT * theme.pos("mp.status_y", 0.48))))

        self._draw_button_custom(events, theme.string("button.back", "BACK"), _cfg.WIDTH//2 - int(_cfg.WIDTH * 0.04), _cfg.HEIGHT - int(_cfg.HEIGHT * theme.pos("menu.title_y", 0.08)), int(_cfg.WIDTH * 0.08), int(_cfg.HEIGHT * 0.04), lambda: setattr(GAME, 'state', 'menu'))

    def _draw_lan_servers(self, events, GAME, top_y, join):
        """Toont de servers die zich op het LAN hebben aangemeld.

        Broadcast werkt alleen binnen één netwerk: een campus-WLAN houdt
        verkeer tussen laptops tegen, en dan blijft deze lijst leeg. Dat is
        geen fout, dus we zeggen het eerlijk in plaats van te doen alsof er
        iets zoekt.
        """
        title = theme.string("multiplayer.lan_title", "SERVERS IN JOUW NETWERK")
        title_surf = load_font(self._font_px("mp.font.lan_title", 18)).render(title, True, theme.color("text.subtitle", (200, 200, 200)))
        _cfg.SCREEN.blit(title_surf, (_cfg.WIDTH//2 - title_surf.get_width()//2, top_y))

        listener = getattr(GAME, "discovery_listener", None)
        servers = listener.list_servers() if listener else []
        if not servers:
            hint = theme.string("multiplayer.lan_empty",
                                "Nog niets gevonden (werkt niet op campus-wifi, wel thuis)")
            hint_surf = load_font(self._font_px("mp.font.lan_hint", 15)).render(hint, True, theme.color("text.info", (150, 150, 150)))
            _cfg.SCREEN.blit(hint_surf, (_cfg.WIDTH//2 - hint_surf.get_width()//2,
                                        top_y + title_surf.get_height() + self._gap_px(12)))
            return

        row_h = int(_cfg.HEIGHT * 0.04)
        row_w = int(_cfg.WIDTH * 0.34)
        row_x = _cfg.WIDTH//2 - row_w//2
        # Dezelfde afstand als de lege-tijd regel hierboven, zodat de eerste
        # server op dezelfde regel begint als die hint.
        eerste_y = top_y + title_surf.get_height() + self._gap_px(12)
        for index, server in enumerate(servers[:5]):
            y = eerste_y + index * row_h
            # Een server die geen limiet meestuurt mag niet het hele
            # tekenscherm slaan, dus komt er een vraagteken in beeld.
            max_players = server["max_players"]
            label = "%s   %d/%s" % (server["ip"], server["players"],
                                     max_players if max_players else "?")
            self._draw_button_custom(
                events, label, row_x, y, row_w, row_h - self._gap_px(6),
                lambda s=server: join(s["ip"], s["port"]))

    def _draw_host_address(self, GAME, events=()):
        """Toont de gasten het adres waarop ze kunnen verbinden.

        Zonder dit moet iemand die niet op je netwerk zitten eerst vragen
        wat je IP is, en dat is precies het punt waar multiplayer online
        vastloopt.

        Een klik op een regel zet hem op het klembord. Je kunt tekst op een
        scherm nu eenmaal niet selecteren met de muis, dus zonder dit moet
        iemand het adres overtypen en dat is precies de fout die het
        internetadres onbruikbaar maakt.
        """
        if getattr(GAME, "hosted_server", None) is None:
            return
        info = getattr(GAME, "hosted_address", None)
        lines = []
        if info is None:
            lines.append((theme.string("lobby.host_searching", "Bezig met je adres opzoeken..."),
                          theme.color("text.info", (150, 150, 150))))
        else:
            if info.get("lan_ip"):
                lines.append((theme.string("lobby.host_lan", "LAN: {ip}:{port}").format(
                    ip=info["lan_ip"], port=GAME.hosted_port or DEFAULT_PORT),
                    (140, 230, 140)))
            if info.get("public_ip"):
                key, default = ("lobby.host_internet", "Internet: {ip}:{port}") \
                    if info.get("mapped") else \
                    ("lobby.host_internet_nomap", "Internet: {ip}:{port}  (poort nog niet open)")
                lines.append((theme.string(key, default).format(
                    ip=info["public_ip"], port=info.get("external_port", DEFAULT_PORT)),
                    (150, 200, 255) if info.get("mapped") else (255, 180, 80)))
        y = getattr(self, "_lobby_title_bottom", None)
        if y is None:
            y = int(_cfg.HEIGHT * 0.145)
        else:
            y += self._gap_px(8)
        rects = []
        kopieer = []
        addr_px = self._font_px("lobby.font.addr", 17)
        for text, color in lines:
            surf = load_font(addr_px).render(text, True, color)
            # De internetregel is met '(poort nog niet open)' de langste van
            # de twee en liep op een smal scherm dwars door de LAN-regel heen.
            surf = self._fit_width(surf, _cfg.WIDTH * 0.90)
            x = _cfg.WIDTH // 2 - surf.get_width() // 2
            _cfg.SCREEN.blit(surf, (x, y))
            rects.append((pygame.Rect(x - 6, y - 3, surf.get_width() + 12,
                                      surf.get_height() + 6), text))
            y += surf.get_height() + self._gap_px(4)

        self._host_addr_rects = rects
        self._host_addr_bottom = y

        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for rect, tekst in rects:
                    if rect.collidepoint(pygame.mouse.get_pos()):
                        self._copy_to_clipboard(tekst)
                        kopieer.append((tekst, 0))

        for tekst, _ in kopieer:
            self._flash_text(tekst)

    def _flash_text(self, tekst):
        """Laat kort zien dat er gekopieerd is.

        Een verborgen klembordklik geeft geen enkel bewijs, dus zonder
        zichtbare bevestiging weet de host niet of het werkte.

        De doos staat vlak onder de adresregels. _draw_host_address stuurt
        het beginadres mee zodat dit hier niet opnieuw berekend hoeft te
        worden en er geen twee maten voor dezelfde regel in de code komen.
        """
        self._copy_flash = (tekst, pygame.time.get_ticks())
        if getattr(self, "_copy_flash_rect", None) is not None:
            return
        top = getattr(self, "_host_addr_bottom",
                      int(_cfg.HEIGHT * 0.145))
        surf = load_font(self._font_px("lobby.font.addr", 17)).render(tekst, True, (140, 230, 140))
        rect = pygame.Rect(0, 0, surf.get_width() + 20, surf.get_height() + 10)
        rect.center = (_cfg.WIDTH // 2, top + 18)
        self._copy_flash_rect = rect
        self._copy_flash_surface = surf

    def _draw_copy_flash(self):
        """Teken de bevestiging weg, en ruim hem op als hij te oud is."""
        flash = getattr(self, "_copy_flash", None)
        rect = getattr(self, "_copy_flash_rect", None)
        surf = getattr(self, "_copy_flash_surface", None)
        if not flash or rect is None or surf is None:
            return
        if pygame.time.get_ticks() - flash[1] > 1500:
            self._copy_flash = None
            self._copy_flash_rect = None
            self._copy_flash_surface = None
            return
        pygame.draw.rect(_cfg.SCREEN, (0, 0, 0), rect, border_radius=4)
        _cfg.SCREEN.blit(surf, (rect.x + 10, rect.y + 5))

    def _copy_to_clipboard(self, tekst):
        """Zet tekst op het klembord.

        pygame heeft geen klembord, dus we lenen die van tkinter. Dat is
        al een verplichte import voor het uploadvenster van skins, dus dit
        voegt geen nieuwe afhankelijkheid toe aan de verpakte build.
        """
        root = None
        try:
            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(tekst)
            # Zonder dit wist het klembord de inhoud weer zodra dit
            # venster sluit, en viel de kopieeractie stil.
            root.update()
        except Exception:
            pass
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    def draw_waiting_lobby(self, events, GAME):
        self.game = GAME
        self._fill_bg()

        for sid in SkinManager.get_completed_downloads():
            self._skin_thumbnails.pop(sid, None)
        SkinManager.clear_completed_downloads()

        title = load_font(self._font_px("lobby.font.title", 50)).render(theme.string("lobby.title", "LOBBY"), True, theme.color("text.title", 'white'))
        title_y = int(_cfg.HEIGHT * theme.pos("menu.title_y", 0.08))
        _cfg.SCREEN.blit(title, (_cfg.WIDTH//2 - title.get_width()//2, title_y))
        # Het gasten-adres staat als kop onder de titel, en niet op de hoogte
        # van de kolommen: anders liep die lange internetregel dwars door het
        # 'KIEZEN' van de rechterkolom.
        self._lobby_title_bottom = title_y + title.get_height()

        if SkinManager.is_downloading():
            prog = SkinManager.get_download_progress()
            dl_label = "%s %d/%d" % (theme.string("lobby.downloading", "Skins downloaden..."), prog["done"], prog["total"])
            dl_text = load_font(self._font_px("lobby.font.dl", 16)).render(dl_label, True, theme.color("text.info", (150, 150, 150)))
            _cfg.SCREEN.blit(dl_text, (_cfg.WIDTH//2 - dl_text.get_width()//2, self._lobby_title_bottom + self._gap_px(6)))

        mouse = pygame.mouse.get_pos()

        # ── Host: laat zien hoe de gasten hier moeten komen ──────────
        self._draw_host_address(GAME, events)

        # De kolommen beginnen pas onder het adresblok, zodat niets elkaar
        # kan overlappen ongeacht hoe breed de regel met het IP-adres is.
        kolom_top = max(int(_cfg.HEIGHT * theme.pos("lobby.left_start_y", 0.15)),
                        getattr(self, "_host_addr_bottom", 0) + self._gap_px(14))

        # ── Left column: player list ──────────────────────────────
        left_x = int(_cfg.WIDTH * 0.04)
        left_cx = int(_cfg.WIDTH * 0.20)
        y_left = kolom_top
        players = self.client_list if self.client_list else []
        thumb_size = theme.size("lobby.thumb_size", self._scale(36))
        name_px = self._font_px("lobby.font.name", 26)
        ready_px = self._font_px("lobby.font.ready", 16)
        text_x = left_x + thumb_size + self._gap_px(10)
        # Kolombreedte voor de tekst, zodat een lange naam niet in de
        # rechterkolom met de skins loopt.
        col_w = int(_cfg.WIDTH * 0.30)
        all_ready = True
        for pd in players:
            pid = pd["pid"] if isinstance(pd, dict) else pd[1]
            name = pd["name"] if isinstance(pd, dict) else pd[0]
            skin_id = pd.get("skin_id", 0) if isinstance(pd, dict) else (pd[2] if len(pd) > 2 else 0)
            ready = pd.get("ready", False) if isinstance(pd, dict) else False
            if not ready:
                all_ready = False
            is_host = (pid == self.host_pid if self.host_pid >= 0 else False)
            color = theme.color("player.highlight", (0, 200, 255)) if pid == GAME.player_id else theme.color("text.title", (255, 255, 255))
            if skin_id not in self._skin_thumbnails or self._skin_thumbnails[skin_id].get_width() != thumb_size:
                self._skin_thumbnails[skin_id] = SkinManager.create_thumbnail(skin_id, (thumb_size, thumb_size))
            _cfg.SCREEN.blit(self._skin_thumbnails[skin_id], (left_x, y_left))
            ready_text = theme.string("lobby.ready", "READY") if ready else theme.string("lobby.not_ready", "NOT READY")
            ready_color = theme.color("lobby.ready", (0, 200, 0)) if ready else theme.color("lobby.not_ready", (200, 80, 80))
            ready_surf = load_font(ready_px).render(ready_text, True, ready_color)
            label = f"[P{pid}] {name}"
            if is_host:
                label += " (HOST)"
                color = (255, 220, 0)  # gold for host
            p_text = load_numeric_font(name_px).render(label, True, color)
            p_text = self._fit_width(p_text, col_w)
            _cfg.SCREEN.blit(p_text, (text_x, y_left))
            # De READY-regel begint ná de hoogte van de naam, niet op een
            # vaste 28 pixels: bij een kleinere font paste de naam er anders
            # bovenop.
            _cfg.SCREEN.blit(ready_surf, (text_x, y_left + p_text.get_height() + self._gap_px(4)))
            y_left += max(thumb_size, p_text.get_height() + ready_surf.get_height()
                          ) + self._gap_px(16)
        if not players:
            all_ready = False
            wait = load_font(self._font_px("lobby.font.waiting", 22)).render(theme.string("lobby.waiting", "Wachten op spelers..."), True, theme.color("text.info", (150, 150, 150)))
            wait = self._fit_width(wait, col_w)
            _cfg.SCREEN.blit(wait, (left_cx - wait.get_width()//2, y_left))
        elif not all_ready:
            # Zeg wie er nog op READY UP moet zitten, anders wacht de host
            # op een groep die allang klaar is zonder dat iemand op Start kan.
            n_pending = sum(1 for pd in players
                            if not (pd.get("ready", False) if isinstance(pd, dict) else False))
            pending_surf = load_font(self._font_px("lobby.font.pending", 20)).render(
                theme.string("lobby.waiting_ready", "Wachten op {n} speler(s) op READY").format(n=n_pending),
                True, theme.color("text.info", (150, 150, 150)))
            pending_surf = self._fit_width(pending_surf, col_w)
            _cfg.SCREEN.blit(pending_surf, (left_x, y_left))

        # ── Right column: skin selector ───────────────────────────
        right_cx = int(_cfg.WIDTH * 0.66)
        y_right = kolom_top

        sel_label = load_font(self._font_px("lobby.font.skin_choose", 22)).render(theme.string("lobby.skin_choose", "KIEZEN"), True, theme.color("text.subtitle", (200, 200, 200)))
        _cfg.SCREEN.blit(sel_label, (right_cx - sel_label.get_width()//2, y_right))
        y_right += sel_label.get_height() + self._gap_px(10)

        avail = SkinManager.get_available_skins()
        builtin = [s for s in avail if s.get("type") == "builtin"]
        custom = [s for s in avail if s.get("type") == "custom"]
        t_size_b = int(min(_cfg.WIDTH * 0.04, _cfg.HEIGHT * 0.055))
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
            _cfg.SCREEN.blit(self._skin_thumbnails[sid], (x, y_right))
            border_color = theme.color("skin.selected", (0, 200, 255)) if sid == GAME.skin_id else theme.color("skin.border", (60, 60, 60))
            pygame.draw.rect(_cfg.SCREEN, border_color, rect, 3, border_radius=4)
            name_surf = load_numeric_font(self._font_px("lobby.font.builtin_name", 13)).render(info.get("name", f"S{sid}"), True, theme.color("text.info", (150, 150, 150)))
            # De naam mag niet breder zijn dan het vakje erboven, anders
            # liepen zes namen over elkaar heen op een smal scherm.
            name_surf = self._fit_width(name_surf, int((t_size_b + gap_b) * 0.95))
            _cfg.SCREEN.blit(name_surf, (x + t_size_b//2 - name_surf.get_width()//2, y_right + t_size_b + self._gap_px(2)))
        y_right += t_size_b + self._gap_px(28)

        # ── Upload section (always visible) ─────────────────────────
        upload_font = load_font(self._font_px("lobby.font.upload", 16))
        upload_label = upload_font.render(theme.string("lobby.new_skin", "NIEUWE SKIN"), True, theme.color("text.subtitle", (200, 200, 200)))
        _cfg.SCREEN.blit(upload_label, (right_cx - upload_label.get_width()//2, y_right))
        y_right += upload_label.get_height() + self._gap_px(10)
        pending_path = getattr(self, '_pending_upload_path', None)
        name_w = int(_cfg.WIDTH * 0.08)
        btn_w = int(_cfg.WIDTH * 0.08)
        name_x = right_cx - name_w - int(_cfg.WIDTH * 0.02)
        # De hoogte van de velden en knoppen volgt de font, anders blijft
        # een vaste 26 pixels te laag zodra de font schaalt.
        row_h = max(18, int(upload_font.get_height() + self._gap_px(8)))
        if pending_path:
            # De bestandsnaam krijgt een eigen regel. Eerst stond hij
            # boven het veld getekend, precies op de hoogte van het
            # 'NIEUWE SKIN'-label er boven.
            pending_label = upload_font.render(getattr(self, '_pending_upload_filename', ''), True, theme.color("text.info", (180, 180, 180)))
            pending_label = self._fit_width(pending_label, name_w + btn_w)
            _cfg.SCREEN.blit(pending_label, (name_x, y_right))
            y_right += pending_label.get_height() + self._gap_px(6)
            self.mp_skin_upload_name = self._draw_text_input(events, "",
                self.mp_skin_upload_name, name_x, y_right, name_w,
                height=row_h, field_id="mp_skin_upload_name")
            btn_x = right_cx + int(_cfg.WIDTH * 0.02)
            con_rect = pygame.Rect(btn_x, y_right, btn_w, row_h)
            hover = con_rect.collidepoint(mouse)
            pygame.draw.rect(_cfg.SCREEN, theme.color("upload.hover_bg", (80, 120, 80)) if hover else theme.color("upload.bg", (60, 90, 60)), con_rect, border_radius=4)
            con_surf = upload_font.render(theme.string("lobby.confirm", "CONFIRM"), True, theme.color("upload.text", (200, 255, 200)))
            con_surf = self._fit_width(con_surf, btn_w - 8)
            _cfg.SCREEN.blit(con_surf, (btn_x + btn_w//2 - con_surf.get_width()//2, y_right + (row_h - con_surf.get_height())//2))
            self._skin_confirm_rect = con_rect
        else:
            sel_rect = pygame.Rect(right_cx - btn_w//2, y_right, btn_w, row_h)
            hover = sel_rect.collidepoint(mouse)
            pygame.draw.rect(_cfg.SCREEN, theme.color("upload.hover_bg", (80, 120, 80)) if hover else theme.color("upload.bg", (60, 90, 60)), sel_rect, border_radius=4)
            sel_surf = upload_font.render(theme.string("lobby.select_file", "SELECT"), True, theme.color("upload.text", (200, 255, 200)))
            sel_surf = self._fit_width(sel_surf, btn_w - 8)
            _cfg.SCREEN.blit(sel_surf, (right_cx - sel_surf.get_width()//2, y_right + (row_h - sel_surf.get_height())//2))
            self._skin_select_rect = sel_rect
        y_right += row_h + self._gap_px(12)

        if self._upload_status:
            col = theme.color("text.success", (0, 200, 0)) if "gelukt" in self._upload_status.lower() else theme.color("text.warning", (200, 100, 0))
            st = load_numeric_font(self._font_px("lobby.font.upload_status", 15)).render(self._upload_status, True, col)
            st = self._fit_width(st, int(_cfg.WIDTH * 0.24))
            _cfg.SCREEN.blit(st, (right_cx - st.get_width()//2, y_right))
            y_right += st.get_height() + self._gap_px(6)

        # ── Custom skins browser ────────────────────────────────────
        self._skin_custom_rects = []
        self._skin_custom_info = []
        if custom:
            cus_label = load_font(self._font_px("lobby.font.custom", 18)).render(theme.string("lobby.custom", "CUSTOM"), True, theme.color("text.custom", (160, 140, 255)))
            _cfg.SCREEN.blit(cus_label, (right_cx - cus_label.get_width()//2, y_right))
            y_right += cus_label.get_height() + self._gap_px(10)

            search_w = int(_cfg.WIDTH * 0.12)
            search_x = right_cx - search_w//2
            self.mp_skin_search = self._draw_text_input(events, "",
                getattr(self, 'mp_skin_search', ""), search_x, y_right, search_w,
                height=row_h, field_id="mp_skin_search")
            y_right += row_h + self._gap_px(12)

            filter_text = getattr(self, 'mp_skin_search', "").lower()
            filtered = [s for s in custom if filter_text in s.get("name", "").lower()]

            per_page = theme.size("lobby.skins_per_page", 4)
            total_pages = max(1, (len(filtered) + per_page - 1) // per_page)
            page = getattr(self, '_skin_page', 0)
            if page >= total_pages:
                page = total_pages - 1
            self._skin_page = page

            t_size_c = int(_cfg.WIDTH * 0.06)
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
                _cfg.SCREEN.blit(self._skin_thumbnails[sid], (x, y_right))
                border_color = theme.color("skin.selected", (0, 200, 255)) if sid == GAME.skin_id else theme.color("skin.border", (60, 60, 60))
                pygame.draw.rect(_cfg.SCREEN, border_color, rect, 2, border_radius=4)
                label = info.get("name", f"S{sid}")
                if len(label) > 14:
                    label = label[:13] + "..."
                name_surf = load_numeric_font(self._font_px("lobby.font.custom_name", 12)).render(label, True, theme.color("text.info", (160, 160, 160)))
                # Net als bij de built-ins: de naam blijft binnen het vakje
                # erboven, anders lopen vier namen over elkaar heen.
                name_surf = self._fit_width(name_surf, int((t_size_c + gap_c) * 0.95))
                _cfg.SCREEN.blit(name_surf, (x + t_size_c//2 - name_surf.get_width()//2, y_right + t_size_c + self._gap_px(2)))

            y_right += t_size_c + self._gap_px(22)

            # Pagination controls
            self._skin_prev_rect = None
            self._skin_next_rect = None
            if total_pages > 1:
                arr_font = load_numeric_font(self._font_px("lobby.font.page", 20))
                pad = self._gap_px(4)
                arr_w = max(int(_cfg.WIDTH * 0.04), arr_font.get_height() + pad * 2)
                arr_h = arr_font.get_height() + pad * 2
                arr_y = y_right + self._gap_px(6)
                prev_surf = arr_font.render("<", True, theme.color("pagination.arrow", (200, 200, 200)))
                prev_rect = pygame.Rect(right_cx - int(_cfg.WIDTH * 0.08), arr_y, arr_w, arr_h)
                pygame.draw.rect(_cfg.SCREEN, theme.color("pagination.active_bg", (70, 70, 70)) if page > 0 else theme.color("pagination.disabled_bg", (40, 40, 40)), prev_rect, border_radius=4)
                _cfg.SCREEN.blit(prev_surf, (prev_rect.centerx - prev_surf.get_width()//2,
                                             prev_rect.centery - prev_surf.get_height()//2))
                self._skin_prev_rect = prev_rect
                self._skin_prev_page = page > 0

                page_surf = arr_font.render(f"{page + 1}/{total_pages}", True, theme.color("pagination.page", (180, 180, 180)))
                _cfg.SCREEN.blit(page_surf, (right_cx - page_surf.get_width()//2,
                                             arr_y + (arr_h - page_surf.get_height())//2))

                next_surf = arr_font.render(">", True, theme.color("pagination.arrow", (200, 200, 200)))
                next_rect = pygame.Rect(right_cx + int(_cfg.WIDTH * 0.06), arr_y, arr_w, arr_h)
                pygame.draw.rect(_cfg.SCREEN, theme.color("pagination.active_bg", (70, 70, 70)) if page < total_pages - 1 else theme.color("pagination.disabled_bg", (40, 40, 40)),
                                 next_rect, border_radius=4)
                _cfg.SCREEN.blit(next_surf, (next_rect.centerx - next_surf.get_width()//2,
                                             next_rect.centery - next_surf.get_height()//2))
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

                for opt_key, opt_rect in getattr(self, '_lobby_option_rects', []):
                    if opt_rect.collidepoint(mouse):
                        new_val = not self.lobby_options.get(opt_key, True)
                        GAME._set_lobby_option(opt_key, new_val)

        # ── Countdown banner ───────────────────────────────────────────
        if self.lobby_countdown > 0:
            elapsed_ms = pygame.time.get_ticks() - getattr(self, '_cd_ticks', 0)
            frames_passed = elapsed_ms / (1000 / 60)
            remaining = max(0, int(self.lobby_countdown - frames_passed))
            if remaining > 0:
                seconds = max(1, remaining // 60 + 1)
                count_text = theme.string("lobby.countdown", "STARTING IN {s}...").format(s=seconds)
                count_surf = load_font(self._font_px("lobby.font.countdown", 40)).render(count_text, True, theme.color("lobby.countdown", (255, 200, 0)))
                _cfg.SCREEN.blit(count_surf, (_cfg.WIDTH//2 - count_surf.get_width()//2, int(_cfg.HEIGHT * 0.12)))

        # ── Lobby settings (host only) ─────────────────────────────────
        # Dit blok stond op 55% van de breedte en daarmee midden in de
        # skinkolom, waar de paginering van de custom skins ook staat. Op
        # sommige resoluties en skin-aantallen landde 'LOBBY SETTINGS' dan
        # bovenop de pijlen. Links onder de spelerlijst staat er wel altijd
        # ruimte: die is daar leeg zodra de wachttijd of de melding weg is.
        if not self.lobby_game_active:
            opts = self.lobby_options if hasattr(self, 'lobby_options') else {}
            is_host = GAME.is_host if hasattr(GAME, 'is_host') else False
            sx = left_x
            sy = y_left + self._gap_px(20)
            set_font = load_font(self._font_px("lobby.font.setting", 18))
            set_h = max(16, int(set_font.get_height() + self._gap_px(8)))
            set_label = set_font.render("LOBBY SETTINGS", True, theme.color("text.subtitle", (200, 200, 200)))
            _cfg.SCREEN.blit(set_label, (sx, sy))
            sy += set_label.get_height() + self._gap_px(8)

            self._lobby_option_rects = []
            for opt_key, opt_display in [("shared_health", "Shared Health"), ("shared_ammo", "Shared Ammo")]:
                val = opts.get(opt_key, True)
                txt = f"{opt_display}: {'ON' if val else 'OFF'}"
                col = theme.color("lobby.ready", (0, 200, 0)) if val else theme.color("lobby.not_ready", (200, 80, 80))
                rect = pygame.Rect(sx, sy, int(_cfg.WIDTH * 0.14), set_h)
                if is_host:
                    hover = rect.collidepoint(mouse)
                    bg = theme.color("button.hover_bg", (80, 80, 80)) if hover else theme.color("button.bg", (60, 60, 60))
                    pygame.draw.rect(_cfg.SCREEN, bg, rect, border_radius=4)
                    if hover:
                        pygame.draw.rect(_cfg.SCREEN, (180, 180, 180), rect, 1, border_radius=4)
                    self._lobby_option_rects.append((opt_key, rect))
                else:
                    pygame.draw.rect(_cfg.SCREEN, (40, 40, 40), rect, border_radius=4)
                opt_surf = set_font.render(txt, True, col)
                opt_surf = self._fit_width(opt_surf, rect.w - self._gap_px(10))
                _cfg.SCREEN.blit(opt_surf, (sx + self._gap_px(6), sy + (set_h - opt_surf.get_height())//2))
                sy += set_h + self._gap_px(8)

        # ── "gekopieerd"-bevestiging bovenop alles wat al getekend is ──
        self._draw_copy_flash()



        def dc():
            GAME._silence_music()
            GAME._disconnect()

        def toggle_ready():
            GAME._toggle_ready()

        def join_game():
            GAME._join_active_game()

        # ── Bottom buttons ─────────────────────────────────────────────
        btn_y = _cfg.HEIGHT - int(_cfg.HEIGHT * theme.pos("lobby.start_btn_y", 0.16))
        btn_w = int(_cfg.WIDTH * 0.1)

        if self.lobby_game_active:
            self._draw_button_custom(events, theme.string("lobby.join_game", "JOIN GAME"),
                _cfg.WIDTH//2 - btn_w//2, btn_y, btn_w, int(_cfg.HEIGHT * 0.05), join_game)
        else:
            my_ready = False
            for pd in players:
                pid = pd["pid"] if isinstance(pd, dict) else pd[1]
                if pid == GAME.player_id:
                    my_ready = pd.get("ready", False) if isinstance(pd, dict) else False
                    break
            ready_label = theme.string("lobby.ready_done", "READY") if my_ready else theme.string("lobby.ready_up", "READY UP")
            self._draw_button_custom(events, ready_label,
                _cfg.WIDTH//2 - btn_w//2, btn_y, btn_w, int(_cfg.HEIGHT * 0.05), toggle_ready)
            if my_ready:
                # Dezelfde schaalbare font als de knoptekst, anders blijft
                # het vinkje op een plek hangen die niet meer bij de knop
                # hoort zodra de resolutie kleiner wordt.
                font = load_font(self._font_px("mp.font.button", 28))
                ts = self._fit_width(font.render(ready_label, True, 'white'),
                                    btn_w - 12)
                cx = _cfg.WIDTH//2 - ts.get_width()//2 - self._gap_px(20)
                cy = btn_y + int(_cfg.HEIGHT * 0.05)//2
                v = max(2, self._gap_px(6))
                pts = [(cx, cy - v // 2), (cx + v, cy + v // 2), (cx + v * 3, cy - v)]
                pygame.draw.lines(_cfg.SCREEN, theme.color("lobby.ready_check", (0, 220, 0)), False, pts, max(1, v // 2))

            if self.host_pid >= 0 and self.host_pid == GAME.player_id:
                # Zonder deze knop zit de groep vast zodra één iemand op
                # READY UP blijft hangen: het spel start pas als ALLE klaar zijn.
                def start_game():
                    if GAME.network_client:
                        GAME.network_client.send({"type": "start_game"})
                self._draw_button_custom(events, theme.string("lobby.start_now", "START"),
                    _cfg.WIDTH//2 + btn_w + int(_cfg.WIDTH * 0.02), btn_y, btn_w,
                    int(_cfg.HEIGHT * 0.05), start_game)

        self._draw_button_custom(events, theme.string("lobby.disconnect", "DISCONNECT"), _cfg.WIDTH//2 - int(_cfg.WIDTH * 0.055),
            _cfg.HEIGHT - int(_cfg.HEIGHT * theme.pos("lobby.disconnect_btn_y", 0.10)), int(_cfg.WIDTH * 0.11), int(_cfg.HEIGHT * 0.055), dc)

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
        font = load_font(self._font_px("ui.font.section_header", 24))
        surf = self._fit_width(font.render(text, True, color), int(_cfg.WIDTH * 0.5))
        cx = _cfg.WIDTH // 2
        left_margin = int(_cfg.WIDTH * theme.pos("section_header.left_margin", 0.08))
        right_margin = _cfg.WIDTH - left_margin
        mid_y = y + surf.get_height() // 2
        gap = self._gap_px(14)
        lx = cx - surf.get_width() // 2 - gap
        rx = cx + surf.get_width() // 2 + gap
        if lx > left_margin:
            pygame.draw.line(_cfg.SCREEN, color, (left_margin, mid_y), (lx, mid_y), max(1, self._gap_px(2)))
        if rx < right_margin:
            pygame.draw.line(_cfg.SCREEN, color, (rx, mid_y), (right_margin, mid_y), max(1, self._gap_px(2)))
        _cfg.SCREEN.blit(surf, (cx - surf.get_width() // 2, y))

    def draw_settings(self, events, GAME):
        self.game = GAME
        self._fill_bg()
        c = _cfg.WIDTH // 2

        # ── Title ─────────────────────────────────────────────
        title_font = load_font(theme.size("settings.title_font", int(_cfg.HEIGHT * 0.07)), bold=True)
        title_surf = title_font.render(theme.string("settings.title", "SETTINGS"), True, theme.color("text.title", 'white'))
        _cfg.SCREEN.blit(title_surf, (c - title_surf.get_width() // 2, int(_cfg.HEIGHT * theme.pos("mp.title_y", 0.04))))

        btn_w = int(_cfg.WIDTH * 0.09)
        btn_h = theme.size("settings.btn_h", int(_cfg.HEIGHT * 0.05))
        gap = int(_cfg.WIDTH * 0.02)
        # 22 is de maat op 1080p; Button schaalt hem zelf om.
        btn_font_px = 22

        # ── VIDEO ────────────────────────────────────────────
        self._draw_section_header(theme.string("settings.video", "VIDEO"), int(_cfg.HEIGHT * theme.pos("settings.video_header_y", 0.14)))

        hi_active = self.game.resolution == "high"
        lo_active = self.game.resolution == "low"
        res_y = int(_cfg.HEIGHT * theme.pos("settings.res_btn_y", 0.21))
        Res_high = Button(c - btn_w - gap // 2, res_y, btn_w, btn_h, theme.string("settings.high_res", "HIGH RES"), btn_font_px,
            text_color="white", button_color=(40, 100, 160) if hi_active else (60, 60, 70),
            hover_text_color="white", hover_button_color=(60, 130, 190) if hi_active else (80, 80, 95),
            game=self.game, target_state="settings", function="res_high")
        Res_low = Button(c + gap // 2, res_y, btn_w, btn_h, theme.string("settings.low_res", "LOW RES"), btn_font_px,
            text_color="white", button_color=(40, 100, 160) if lo_active else (60, 60, 70),
            hover_text_color="white", hover_button_color=(60, 130, 190) if lo_active else (80, 80, 95),
            game=self.game, target_state="settings", function="res_low")
        Res_high.draw_button(events)
        Res_low.draw_button(events)

        # ── AUDIO ────────────────────────────────────────────
        self._draw_section_header(theme.string("settings.audio", "AUDIO"), int(_cfg.HEIGHT * theme.pos("settings.audio_header_y", 0.30)))

        self.get_volume_slider(GAME).draw(events)
        self.get_sfx_volume_slider(GAME).draw(events)

        # ── GAMEPLAY ─────────────────────────────────────────
        self._draw_section_header(theme.string("settings.gameplay", "GAMEPLAY"), int(_cfg.HEIGHT * theme.pos("settings.gameplay_header_y", 0.52)))

        # Tutorial toggle
        tuto_active = self.game.bilal.flags["general"]
        tuto_btn = Button(c - int(_cfg.WIDTH * 0.045), int(_cfg.HEIGHT * theme.pos("settings.tutorial_btn_y", 0.59)),
            int(_cfg.WIDTH * 0.09), int(_cfg.HEIGHT * 0.05), theme.string("settings.tutorial", "TUTORIAL"), btn_font_px,
            text_color="white", button_color=(40, 100, 160) if tuto_active else (60, 60, 70),
            hover_text_color="white", hover_button_color=(60, 130, 190) if tuto_active else (80, 80, 95),
            game=self.game, target_state="settings", function="tutorial")
        tuto_btn.draw_button(events)

        # Minimap: drie standen, en de knop zegt welke. De kleur alleen kan
        # niet, want er zijn er drie in plaats van twee.
        minimap_stand = getattr(self.game, "minimap_mode", MINIMAP_UIT)
        label_key, label_default = MINIMAP_LABELS[minimap_stand]
        minimap_label = theme.string(label_key, label_default)
        minimap_kleur = MINIMAP_KLEUREN[minimap_stand]
        minimap_btn = Button(c - int(_cfg.WIDTH * 0.08), int(_cfg.HEIGHT * theme.pos("settings.minimap_btn_y", 0.66)),
            int(_cfg.WIDTH * 0.16), int(_cfg.HEIGHT * 0.05), minimap_label, btn_font_px,
            text_color="white", button_color=minimap_kleur,
            hover_text_color="white", hover_button_color=tuple(min(255, c + 20) for c in minimap_kleur),
            game=self.game, target_state="settings", function="minimap")
        minimap_btn.draw_button(events)

        # Texture pack → pack selector
        self._draw_main_button(events,
            theme.string("settings.texture_pack", "TEXTURE PACKS >"),
            int(_cfg.HEIGHT * theme.pos("settings.pack_btn_y", 0.73)),
            int(_cfg.WIDTH * 0.14),
            lambda: self._open_pack_select(GAME),
            font_size=28)

        # ── Back ──────────────────────────────────────────────
        back_target = getattr(GAME, '_settings_return', 'menu')
        def go_back():
            GAME.state = back_target
            if back_target == "game":
                pygame.mouse.set_visible(False)
                pygame.event.set_grab(True)
                audio.unpause()
            elif back_target == "paused":
                pygame.mouse.set_visible(True)
                pygame.event.set_grab(False)
            else:
                pygame.mouse.set_visible(True)
                pygame.event.set_grab(False)
            GAME._settings_return = "menu"
        self._draw_main_button(events, theme.string("button.back", "BACK"), _cfg.HEIGHT - int(_cfg.HEIGHT * theme.pos("menu.title_y", 0.08)), int(_cfg.WIDTH * 0.11), go_back, font_size=34)

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
        c = _cfg.WIDTH // 2

        title_font = load_font(theme.size("settings.title_font", int(_cfg.HEIGHT * 0.07)), bold=True)
        title_surf = title_font.render(theme.string("pack_select.title", "TEXTURE PACKS"), True, theme.color("text.title", 'white'))
        _cfg.SCREEN.blit(title_surf, (c - title_surf.get_width() // 2, int(_cfg.HEIGHT * theme.pos("mp.title_y", 0.04))))

        all_packs = [p["value"] for p in list_packs()]
        avail = [p for p in all_packs if p not in self._working_packs]

        # ── Layout constants ──────────────────────────────
        col_w = int(_cfg.WIDTH * 0.18)
        col_h = int(_cfg.HEIGHT * 0.50)
        col_y = int(_cfg.HEIGHT * 0.16)
        item_h = int(_cfg.HEIGHT * 0.048)
        arr_w = int(_cfg.WIDTH * 0.025)
        prio_w = int(_cfg.WIDTH * 0.018)
        gap = int(_cfg.WIDTH * 0.008)
        visible = col_h // item_h
        font = load_font(self._font_px("ui.font.pack_item", 22))
        label_font = load_font(self._font_px("ui.font.pack_label", 20))
        mouse = pygame.mouse.get_pos()

        # Center the whole block:
        block_w = col_w * 2 + arr_w + prio_w + gap * 4
        block_x = (_cfg.WIDTH - block_w) // 2
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
        def item_rect(x, i):
            """Het vakje van item i. Tekenen én klikken gebruiken dit allebei,
            anders raakt een klik op een andere plek dan wat je ziet."""
            y = col_y + i * item_h + self._gap_px(4)
            return pygame.Rect(x + self._gap_px(4), y, col_w - self._gap_px(8),
                               item_h - self._gap_px(4))

        def draw_column(items, x, scroll, sel_idx):
            box = pygame.Rect(x, col_y, col_w, col_h)
            pygame.draw.rect(_cfg.SCREEN, box_bg, box, border_radius=6)
            pygame.draw.rect(_cfg.SCREEN, box_border, box, 2, border_radius=6)
            for i in range(visible):
                idx = scroll + i
                if idx >= len(items):
                    break
                rect = item_rect(x, i)
                selected = idx == sel_idx
                hover = rect.collidepoint(mouse)
                bg = sel_bg if selected else (hover_bg if hover else item_bg)
                pygame.draw.rect(_cfg.SCREEN, bg, rect, border_radius=4)
                label = items[idx]
                surf = font.render(label, True, text_col)
                # Een lange packnaam loopt anders over de rand van de kolom
                # heen en in de kolom ernaast.
                surf = self._fit_width(surf, rect.w - self._gap_px(12))
                _cfg.SCREEN.blit(surf, (rect.x + self._gap_px(6), rect.y + (rect.h - surf.get_height()) // 2))

        # ── Get display name helper ───────────────────────
        def display_name(value):
            for p in list_packs():
                if p["value"] == value:
                    return p["label"]
            return value

        # ── Left column: Available ─────────────────────────
        avail_labels = [display_name(p) for p in avail]
        left_label = label_font.render(theme.string("pack_select.available", "BESCHIKBAAR"), True, sub_col)
        left_label = self._fit_width(left_label, col_w)
        _cfg.SCREEN.blit(left_label, (left_x + col_w // 2 - left_label.get_width() // 2,
                                     col_y - left_label.get_height() - self._gap_px(8)))
        self._pack_sel_avail_scroll = max(0, min(self._pack_sel_avail_scroll, max(0, len(avail) - visible)))
        draw_column(avail_labels, left_x, self._pack_sel_avail_scroll, self._pack_sel_avail_idx)

        # ── Right column: Active ───────────────────────────
        active_labels = [f"{i + 1}. {display_name(p)}" for i, p in enumerate(self._working_packs)]
        right_label = label_font.render(theme.string("pack_select.active", "ACTIEF"), True, sub_col)
        right_label = self._fit_width(right_label, col_w)
        _cfg.SCREEN.blit(right_label, (right_x + col_w // 2 - right_label.get_width() // 2,
                                       col_y - right_label.get_height() - self._gap_px(8)))
        self._pack_sel_active_scroll = max(0, min(self._pack_sel_active_scroll, max(0, len(self._working_packs) - visible)))
        draw_column(active_labels, right_x, self._pack_sel_active_scroll, self._pack_sel_active_idx)

        # ── Arrow buttons (→ add, ← remove) ────────────────
        arr_btn_h = int(item_h * 0.6)
        arr_btn_w = arr_w
        center_y = col_y + col_h // 2
        left_btn = pygame.Rect(arr_x, center_y - arr_btn_h - self._gap_px(4), arr_btn_w, arr_btn_h)
        right_btn = pygame.Rect(arr_x, center_y + self._gap_px(4), arr_btn_w, arr_btn_h)
        def draw_arr_btn(rect, direction, enabled):
            hover = rect.collidepoint(mouse)
            pygame.draw.rect(_cfg.SCREEN, arr_hov if hover else arr_idle, rect, border_radius=4)
            if enabled:
                _draw_arrow(_cfg.SCREEN, rect, direction, arrow_col)
        draw_arr_btn(left_btn, 'right', bool(avail))
        draw_arr_btn(right_btn, 'left', bool(self._working_packs))

        # ── Priority up/down buttons ───────────────────────
        prio_btn_h = int(item_h * 0.5)
        def draw_prio_btn(rect, direction, enabled):
            hover = rect.collidepoint(mouse)
            pygame.draw.rect(_cfg.SCREEN, arr_hov if hover else arr_idle, rect, border_radius=4)
            if enabled:
                _draw_arrow(_cfg.SCREEN, rect, direction, arrow_col)
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
                        if item_rect(x, i).collidepoint(mouse):
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
                audio.unpause()
                GAME._play_music()
            elif back_target == "paused":
                pygame.mouse.set_visible(True)
                pygame.event.set_grab(False)
                GAME._play_music()
            else:
                pygame.mouse.set_visible(True)
                pygame.event.set_grab(False)
            GAME._settings_return = "menu"
        self._draw_main_button(events, theme.string("button.back", "TERUG"),
            _cfg.HEIGHT - int(_cfg.HEIGHT * theme.pos("menu.title_y", 0.08)),
            int(_cfg.WIDTH * 0.11), confirm, font_size=34)

    def draw_credits(self, events, GAME):
        self.game = GAME
        self._fill_bg()

        y = self.credits_height
        x = _cfg.WIDTH // 4
        white = "white"

        self.title_font = load_font(theme.size("credits.title_font", int(_cfg.HEIGHT * 0.29)), bold=True)
        title_surf = self.title_font.render(theme.string("menu.title", "GUNK"), True, white)
        _cfg.SCREEN.blit(title_surf, (_cfg.WIDTH // 2 - title_surf.get_width() // 2, y))

        self.text_font = load_font(self._font_px("ui.font.credits", 43))
        # De thema-posities geven 0.04 van het beeldhoogte per regel aan, terwijl
        # die font een regelhoogte van net iets meer oplevert. Elke regel stond
        # daardoor een paar pixels in zijn voorganger, en de eerste regel stond
        # bovenop het logo. We rekenen de stap daarom vanaf de werkelijk
        # gemeten regelhoogte, met de thema-positie als minimum. Zo blijft de
        # grotere sprong tussen de secties (Developed by / Music by / ...) ook
        # echt een sprong.
        regel_h = self.text_font.get_height()
        stap = regel_h + self._gap_px(4)
        lines = [
            ("Developed by:", int(_cfg.HEIGHT * theme.pos("credits.dev_label_y", 0.27))),
            ("Kobe Motmans", int(_cfg.HEIGHT * theme.pos("credits.kobe_y", 0.31))),
            ("Andreas Meuwissen", int(_cfg.HEIGHT * theme.pos("credits.andreas_y", 0.35))),
            ("Ruben Verreth", int(_cfg.HEIGHT * theme.pos("credits.ruben_y", 0.39))),
            ("Music by:", int(_cfg.HEIGHT * theme.pos("credits.music_label_y", 0.47))),
            ("Rube van der Wielen", int(_cfg.HEIGHT * theme.pos("credits.rube_y", 0.50))),
            ("Special thanks to:", int(_cfg.HEIGHT * theme.pos("credits.thanks_label_y", 0.58))),
            ("Andrei", int(_cfg.HEIGHT * theme.pos("credits.andrei_y", 0.62))),
            ("Ahmed", int(_cfg.HEIGHT * theme.pos("credits.ahmed_y", 0.66))),
            ("Ruben", int(_cfg.HEIGHT * theme.pos("credits.ruben2_y", 0.70))),
            ("Jan", int(_cfg.HEIGHT * theme.pos("credits.jan_y", 0.74))),
            ("Bilal", int(_cfg.HEIGHT * theme.pos("credits.bilal_y", 0.78))),
        ]

        # Het hele blok schuift een stukje omlaag als de eerste regel anders
        # bovenop het logo terechtkomt. Eén keer voor alle regels, zodat de
        # geachte sprong ertussen gewoon een sprong blijft.
        duw = max(0, title_surf.get_height() + self._gap_px(10) - lines[0][1])
        vorige_onder = None
        for text, offset in lines:
            regel_y = y + offset + duw
            if vorige_onder is not None:
                regel_y = max(regel_y, vorige_onder)
            _cfg.SCREEN.blit(
                self.text_font.render(text, False, white),
                (x, regel_y)
            )
            vorige_onder = regel_y + stap

        self.credits_height -= theme.size("credits.scroll_speed", 2)
        if self.credits_height < -int(_cfg.HEIGHT * theme.pos("credits.scroll_reset", 0.87)):
            self.credits_height = _cfg.HEIGHT

        btn_w = int(_cfg.WIDTH * 0.07)
        btn_h = theme.size("credits.btn_h", int(_cfg.HEIGHT * 0.06))
        Menu_button = Button(
            _cfg.WIDTH // 2 - btn_w // 2,
            self.credits_height + _cfg.HEIGHT // 2 - int(_cfg.HEIGHT * theme.pos("credits.btn_y_offset1", 0.03)) + int(_cfg.HEIGHT * theme.pos("credits.btn_y_offset2", 0.52)),
            btn_w, btn_h, theme.string("button.menu", "MENU"), 35,
            text_color="black", button_color="white",
            hover_text_color="white", hover_button_color="black",
            game=self.game, target_state="menu"
        )
        Menu_button.draw_button(events)
        
    def draw_UI(self, events):
        self.fps_font = load_numeric_font(self._font_px("ui.font.fps", 20), bold=True)
        self.hp_font = load_numeric_font(int(_cfg.HEIGHT * theme.pos("menu.title_y", 0.08)), bold=True)
        _cfg.SCREEN.blit(self.fps_font.render(f"{round(self.game.clock.get_fps())}", True, theme.color("hud.fps", 'green')),(int(_cfg.WIDTH * theme.pos("hud.fps_x", 0.01)), int(_cfg.HEIGHT * theme.pos("hud.fps_y", 0.02))))
        max_hp = self.game.max_health()
        _cfg.SCREEN.blit(self.hp_font.render(f"{round(self.game.global_health)}/{max_hp}", True, theme.color("hud.hp", 'red')),(_cfg.WIDTH - int(_cfg.WIDTH * theme.pos("hud.hp_x", 0.15)), int(_cfg.HEIGHT * theme.pos("hud.hp_y", 0.02))))
        _cfg.SCREEN.blit(self.hp_font.render(f"{round(self.game.global_ammo)}/{AMMO_CAP}", True, theme.color("hud.ammo", 'grey')),(int(_cfg.WIDTH * theme.pos("hud.ammo_x", 0.01)), _cfg.HEIGHT - int(_cfg.HEIGHT * theme.pos("hud.ammo_y", 0.1))))

        # Run timer
        if getattr(self.game, 'run_timer_active', False):
            t = getattr(self.game, 'run_time_ms', 0)
            total_ms = int(t)
            s = total_ms // 1000
            ms = (total_ms % 1000) // 10
            m = s // 60
            s_rem = s % 60
            timer_str = f"{m:02d}:{s_rem:02d}.{ms:02d}"
            timer_font = load_font(self._font_px("ui.font.hud", 20), bold=True)
            timer_surf = timer_font.render(timer_str, True, (255, 255, 255))
            _cfg.SCREEN.blit(timer_surf, (_cfg.WIDTH - timer_surf.get_width() - 20, 20))
        in_transition = getattr(self.game, 'elevator_transition', False)
        door_open = getattr(self.game, 'player', None) and self.game.player.door_pos != 0
        if getattr(self.game, 'elevator_waiting', False) and not in_transition and not door_open:
            warn_font = load_numeric_font(self._font_px("ui.font.warning", 36))
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
                # Zeg hoeveel er nog moeten komen: anders staat iedereen te
                # wachten zonder te weten dat er iemand ontbreekt.
                pending = getattr(self.game, 'elevator_pending', None) or [0, 0]
                near, total = pending[0], pending[1]
                if total > 1 and near < total:
                    msg = theme.string("hud.elevator_wait_count",
                                       "Wacht op teamgenoten ({near}/{total})").format(
                                           near=near, total=total)
                else:
                    msg = theme.string("hud.elevator_wait", "Wacht op teamgenoten...")
                color = theme.color("hud.warning_info", (200, 200, 80))
            warn_surf = warn_font.render(msg, True, color)
            _cfg.SCREEN.blit(warn_surf, (_cfg.WIDTH//2 - warn_surf.get_width()//2, _cfg.HEIGHT//2 - int(_cfg.HEIGHT * theme.pos("hud.elevator_warn_y", 0.19))))

        # Meekijken na je eigen dood: zeg wie je volgt en hoe je wisselt,
        # anders lijkt het of het spel vastzit. Eigen font, want de
        # liftmelding hierboven maakt er alleen een als die nodig is.
        if getattr(self.game, 'spectating', False):
            name = getattr(self.game, '_spectate_name', "") or "?"
            spectate_msg = theme.string(
                "hud.spectating",
                "SPECTEERT {name}   [Q/E wisselen, ESC stoppen]").format(name=name)
            spectate_font = load_font(self._font_px("ui.font.spectating", 20), bold=True)
            spectate_surf = spectate_font.render(spectate_msg, True, (140, 200, 255))
            _cfg.SCREEN.blit(spectate_surf, (
                _cfg.WIDTH // 2 - spectate_surf.get_width() // 2,
                int(_cfg.HEIGHT * 0.06)))

        # Run timer tijdens spectate (volgt dezelfde run)
        if getattr(self.game, 'run_timer_active', False):
            t = getattr(self.game, 'run_time_ms', 0)
            total_ms = int(t)
            s = total_ms // 1000
            ms = (total_ms % 1000) // 10
            m = s // 60
            s_rem = s % 60
            timer_str = f"{m:02d}:{s_rem:02d}.{ms:02d}"
            font = load_font(self._font_px("ui.font.hud", 18), bold=True)
            surf = font.render(timer_str, True, (200, 220, 255))
            _cfg.SCREEN.blit(surf, (_cfg.WIDTH - surf.get_width() - 20, 20))
    def draw_paused_screen(self, events, GAME):
        self.game = GAME
        c = _cfg.WIDTH//2
        def resume():
            pygame.mouse.set_visible(False)
            pygame.event.set_grab(True)
            GAME.state = "game"
            audio.unpause()
        self._draw_main_button(events, theme.string("button.resume", "RESUME"), _cfg.HEIGHT//2 - int(_cfg.HEIGHT * theme.pos("pause.resume_y", 0.1)), int(_cfg.WIDTH * 0.11), resume, font_size=34)

        def open_settings():
            GAME._settings_return = "paused"
            GAME.state = "settings"
        self._draw_main_button(events, theme.string("settings.title", "SETTINGS"), _cfg.HEIGHT//2 - int(_cfg.HEIGHT * theme.pos("pause.settings_y", 0.02)), int(_cfg.WIDTH * 0.11), open_settings, font_size=34)

        def go_menu():
            GAME._silence_music()
            if GAME.multiplayer:
                GAME._disconnect()
            else:
                GAME.state = "menu"
        self._draw_main_button(events, theme.string("button.menu", "MENU"), _cfg.HEIGHT//2 + int(_cfg.HEIGHT * theme.pos("pause.menu_y", 0.06)), int(_cfg.WIDTH * 0.11), go_menu, font_size=34)
    def draw_elevator(self, events, player):
        game = getattr(self, 'game', None)
        if game is None:
            return
        is_client = game.multiplayer
        elev_color = theme.color("elevator")
        self.elev_color = tuple(elev_color) if elev_color else (20,20,20)
        half = int(_cfg.WIDTH / 2)

        if player.door_pos <= half:
            # ── Phase 1: doors closing ──
            pygame.draw.rect(_cfg.SCREEN,self.elev_color,[0,0,player.door_pos,_cfg.HEIGHT])
            pygame.draw.rect(_cfg.SCREEN,self.elev_color,[_cfg.WIDTH - player.door_pos,0,player.door_pos,_cfg.HEIGHT])
            player.door_pos += ELEV_SPEED
            if player.door_pos > half:
                self.lift_time = ELEV_TIME

        elif self.lift_time > 0 and not game.escaped:
            # ── Phase 2: doors fully closed, waiting ──
            pygame.draw.rect(_cfg.SCREEN,self.elev_color,[0,0,half,_cfg.HEIGHT])
            pygame.draw.rect(_cfg.SCREEN,self.elev_color,[half,0,half,_cfg.HEIGHT])
            _cfg.SCREEN.fill(self.elev_color)
            self.lift_time -= 1
            if self.lift_time == 0:
                if M.map_level < MAX_LEVEL:
                    if not is_client:
                        game.level_up()
                        game.sounds["elev_ding"].set_volume(game.sfx_volume)
                        game.sounds["elev_ding"].play()
                else:
                    if not is_client:
                        audio.stop_all()
                        game.escaped = True
                        game.sounds["victory"].set_volume(game.sfx_volume)
                        game.sounds["victory"].play()
                        pygame.mouse.set_visible(True)
                        pygame.event.set_grab(False)
                player.door_pos = half + ELEV_SPEED

        elif half < player.door_pos < _cfg.WIDTH:
            # ── Phase 3: doors opening ──
            pygame.draw.rect(_cfg.SCREEN,self.elev_color,[0,0,_cfg.WIDTH - player.door_pos,_cfg.HEIGHT])
            pygame.draw.rect(_cfg.SCREEN,self.elev_color,[player.door_pos,0,_cfg.WIDTH - player.door_pos,_cfg.HEIGHT])
            player.door_pos += ELEV_SPEED

        elif player.door_pos >= _cfg.WIDTH:
            # ── Phase 4: doors fully open ──
            if not game.escaped and not game.elevator_transition:
                player.door_pos = 0
    def draw_dead_screen(self,events,GAME):
        self.game = GAME
        self.title_font = load_font(theme.size("dead.title_font", int(_cfg.HEIGHT * 0.19)), bold=True)
        _cfg.SCREEN.blit(_cfg.SCREEN_DEAD, (0,0))
        self.score_font = load_numeric_font(int(_cfg.HEIGHT * theme.pos("menu.title_y", 0.08)), bold=True)
        btn_w = int(_cfg.WIDTH * 0.07)
        btn_h = theme.size("credits.btn_h", int(_cfg.HEIGHT * 0.06))
        Menu_button = Button(_cfg.WIDTH // 2 - btn_w // 2, _cfg.HEIGHT // 2 - btn_h // 2 + int(_cfg.HEIGHT * theme.pos("dead.btn_y", 0.1)),
            btn_w, btn_h, theme.string("button.menu", "MENU"), 35,
            text_color="black", button_color="white",
            hover_text_color="white", hover_button_color="black",
            game=self.game, target_state="menu", function="disconnect")
        Menu_button.draw_button(events)
        # Meekijken kan alleen in multiplayer en alleen als er nog iemand
        # over is om naar te kijken.
        if getattr(self.game, 'multiplayer', False) and self.game.can_spectate():
            spectate_w = int(_cfg.WIDTH * 0.11)
            spectate_h = theme.size("credits.btn_h", int(_cfg.HEIGHT * 0.06))
            spectate_button = Button(
                _cfg.WIDTH // 2 - spectate_w // 2,
                _cfg.HEIGHT // 2 - spectate_h // 2 + int(_cfg.HEIGHT * theme.pos("dead.btn_y", 0.1))
                + spectate_h + 12,
                spectate_w, spectate_h,
                theme.string("dead.spectate", "MEEKIJKEN"), 26,
                text_color="black", button_color="white",
                hover_text_color="white", hover_button_color="black",
                game=self.game, function="spectate")
            spectate_button.draw_button(events)
        score_surf = self.score_font.render(theme.string("hud.score_format", "Score:{score}").format(score=self.game.player.score), True, theme.color("hud.score_dead", 'black'))
        _cfg.SCREEN.blit(score_surf, (_cfg.WIDTH//2 - score_surf.get_width()//2, _cfg.HEIGHT//2 - int(_cfg.HEIGHT * theme.pos("mp.title_y", 0.04))))
        title_surf = self.title_font.render(theme.string("hud.game_over", "GAME OVER"), True, theme.color("hud.title_dead", 'black'))
        _cfg.SCREEN.blit(title_surf, (_cfg.WIDTH//2 - title_surf.get_width()//2, _cfg.HEIGHT//3 - int(_cfg.HEIGHT * theme.pos("dead.title_y", 0.05))))
        
    def draw_escaped_screen(self,events,GAME):
        self.game = GAME
        self.endscreen_font = load_font(theme.size("escaped.title_font", int(_cfg.HEIGHT * 0.15)), bold=True)
        self.score_font = load_numeric_font(int(_cfg.HEIGHT * theme.pos("menu.title_y", 0.08)), bold=True)
        _cfg.SCREEN.blit(_cfg.VICTORY_SCREEN, (0,0))
        pygame.mouse.set_visible(True)
        s1 = self.endscreen_font.render(theme.string("hud.escaped_title_1", "SUCCESFUL"), True, theme.color("hud.title_escaped", 'white'))
        s2 = self.endscreen_font.render(theme.string("hud.escaped_title_2", "ESKAPE"), True, theme.color("hud.title_escaped", 'white'))
        score_surf = self.score_font.render(theme.string("hud.score_format", "Score:{score}").format(score=self.game.player.score), True, theme.color("hud.score_escaped", 'white'))
        _cfg.SCREEN.blit(s1, (_cfg.WIDTH//2 - s1.get_width()//2, _cfg.HEIGHT//2 - int(_cfg.HEIGHT * theme.pos("escaped.line1_y", 0.45))))
        _cfg.SCREEN.blit(s2, (_cfg.WIDTH//2 - s2.get_width()//2, _cfg.HEIGHT//2 - int(_cfg.HEIGHT * theme.pos("escaped.line2_y", 0.27))))
        _cfg.SCREEN.blit(score_surf, (_cfg.WIDTH//2 - score_surf.get_width()//2, _cfg.HEIGHT//2 + int(_cfg.HEIGHT * theme.pos("escaped.score_y", 0.01))))

        # Run timer + PB
        t = getattr(GAME, 'run_time_ms', 0)
        total_ms = int(t)
        s = total_ms // 1000
        ms = (total_ms % 1000) // 10
        m = s // 60
        s_rem = s % 60
        timer_str = f"{m:02d}:{s_rem:02d}.{ms:02d}"
        time_font = load_font(self._font_px("ui.font.hud", 24), bold=True)
        time_surf = time_font.render(timer_str, True, (255, 255, 255))
        _cfg.SCREEN.blit(time_surf, (_cfg.WIDTH//2 - time_surf.get_width()//2, _cfg.HEIGHT//2 + int(_cfg.HEIGHT * theme.pos("escaped.score_y", 0.08))))
        if getattr(GAME, 'run_is_pb', False):
            pb_font = load_font(self._font_px("ui.font.hud", 20), bold=True)
            pb_surf = pb_font.render("NEW PB!", True, (255, 215, 0))
            _cfg.SCREEN.blit(pb_surf, (_cfg.WIDTH//2 - pb_surf.get_width()//2, _cfg.HEIGHT//2 + int(_cfg.HEIGHT * theme.pos("escaped.score_y", 0.14))))
        elif getattr(GAME, 'run_pb_ms', 0) > 0:
            pb_total = int(GAME.run_pb_ms)
            p_s = pb_total // 1000
            p_ms = (pb_total % 1000) // 10
            p_m = p_s // 60
            p_s_rem = p_s % 60
            pb_str = f"PB {p_m:02d}:{p_s_rem:02d}.{p_ms:02d}"
            pb_font = load_font(self._font_px("ui.font.hud", 18))
            pb_surf = pb_font.render(pb_str, True, (200, 200, 200))
            _cfg.SCREEN.blit(pb_surf, (_cfg.WIDTH//2 - pb_surf.get_width()//2, _cfg.HEIGHT//2 + int(_cfg.HEIGHT * theme.pos("escaped.score_y", 0.14))))
        btn_w = int(_cfg.WIDTH * 0.07)
        btn_h = theme.size("credits.btn_h", int(_cfg.HEIGHT * 0.06))
        Menu_button = Button(_cfg.WIDTH // 2 - btn_w // 2, _cfg.HEIGHT // 2 - btn_h // 2 + int(_cfg.HEIGHT * theme.pos("escaped.btn_y", 0.15)),
            btn_w, btn_h, theme.string("button.menu", "MENU"), 35,
            text_color="black", button_color="white",
            hover_text_color="white", hover_button_color="black",
            game=self.game, target_state="menu", function="disconnect")
        Menu_button.draw_button(events)
    def _slider_center_x(self, width):
        return _cfg.WIDTH // 2 - width // 2

    def get_volume_slider(self, GAME):
        if self.volume_slider is None:
            def on_music_change(val):
                GAME.music_volume = val
                if GAME.main_music_intro:
                    GAME.main_music_intro.set_volume(val)
                GAME.main_music_loop.set_volume(val)
                GAME.save_settings()
            self.volume_slider = Slider(
                self._slider_center_x(int(_cfg.WIDTH * 0.21)), int(_cfg.HEIGHT * theme.pos("slider.music_y", 0.37)),
                int(_cfg.WIDTH * 0.21), int(_cfg.HEIGHT * 0.01),
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
                self._slider_center_x(int(_cfg.WIDTH * 0.21)), int(_cfg.HEIGHT * theme.pos("slider.sfx_y", 0.44)),
                int(_cfg.WIDTH * 0.21), int(_cfg.HEIGHT * 0.01),
                min_val=0.0, max_val=1.0, initial_val=getattr(GAME, 'sfx_volume', 0.3),
                label=theme.string("settings.sfx_volume", "SFX VOLUME"), game=GAME,
                on_change=on_sfx_change
                )
        return self.sfx_volume_slider

    # ── Minimap ──────────────────────────────────────────────
    #
    # De kaart toont de hele level, maar alleen de tegels die de speler heeft
    # gezien. `game.minimap` (src/core/minimap.py) houdt bij welke dat zijn; de
    # tekening hieronder doet niets dan die twee lagen kleuren en de speler,
    # teamgenoten, vijanden en objects eroverheen zetten.
    #
    # De kaart bestaat uit twee oppervlakken van één pixel per tegel:
    # `onthouden` is de tegels die je ooit hebt gezien, in donkere kleuren, en
    # `helder` is élke tegel in de gewone kleuren. In de stand GEZIEN zetten we
    # de helder-lagen over de zichtbare tegels heen; in de stand VOLLEDIG is
    # dat de hele kaart en hebben we geen enkel per-tegel werk nodig.
    #
    # Dit is bewust één pixel per tegel in plaats van een rect per tegel per
    # frame: een level van 40x40 is 1600 rects, en `pygame.transform.scale`
    # doet het vergroten in C.

    def _minimap_vergeet(self):
        """Gooi de getekende lagen weg. Bij een nieuw level, thema of resize."""
        self._mm_kaart = None
        self._mm_onthouden = None
        self._mm_helder = None
        self._mm_versie = -1

    def _minimap_laag(self, kleur_voor):
        """Een oppervlak van M.width x M.height met één pixel per tegel.

        `kleur_voor(x, y)` geeft de kleur van die tegel, of None om de tegel
        transparant te laten.
        """
        surf = pygame.Surface((M.width, M.height), pygame.SRCALPHA)
        for y in range(M.height):
            for x in range(M.width):
                kleur = kleur_voor(x, y)
                if kleur is not None:
                    surf.set_at((x, y), kleur)
        return surf

    def _minimap_kleuren(self):
        muur = tuple(theme.color("minimap.wall", (80, 80, 80)))
        vloer = tuple(theme.color("minimap.floor", (40, 40, 40)))
        # De onthouden tegels zijn flink donkerder dan de zichtbare, zodat je
        # in één oogopslag ziet waar je nu bent en waar je al was.
        muur_donker = tuple(theme.color("minimap.wall_donker", (48, 48, 48)))
        vloer_donker = tuple(theme.color("minimap.floor_donker", (22, 22, 22)))
        return muur, vloer, muur_donker, vloer_donker

    def _minimap_lagen(self, fog):
        """De onthouden tegellaag, plus de kleuren van de helder getekende laag.

        De helder laag is elke tegel in de gewone kleuren en verandert alleen
        bij een andere kaart. De onthouden laag heeft alleen de tegels die de
        speler heeft gezien, in donkere kleuren. De twee kleuren gaan mee terug
        omdat de tekening ze nodig heeft voor de tegels die nu zichtbaar zijn.
        """
        muur, vloer, muur_donker, vloer_donker = self._minimap_kleuren()
        if self._mm_kaart is not M.MAP:
            self._mm_kaart = M.MAP
            self._mm_onthouden = None
            self._mm_helder = self._minimap_laag(
                lambda x, y: muur if M.MAP[y][x] in WALL_VALUES else vloer)
        # `versie` telt omhoog zodra de speler nieuwe tegels heeft ontdekt, en
        # dat is het enige moment waarop de onthouden laag opnieuw getekend moet
        # worden. Zonder die check zou elke frame 1600 set_at kosten.
        if self._mm_onthouden is None or self._mm_versie != fog.versie:
            self._mm_onthouden = self._minimap_laag(
                lambda x, y: (muur_donker if M.MAP[y][x] in WALL_VALUES
                              else vloer_donker)
                if (x, y) in fog.gezien else None)
            self._mm_versie = fog.versie
        return self._mm_onthouden, muur, vloer

    def _minimap_positie(self, size):
        """Waar het vakje op het scherm komt, voor een vakje van `size` px.

        De maat schaalt met het scherm maar de positie is een fractie van de
        breedte, en blit pakt de linkerbovenhoek. Bij een grotere minimap of
        een smal venster zou het rechterdeel dus buiten beeld schuiven.
        Daarom wint de opgegeven linkerhoek alleen als er ruimte voor is;
        anders schuift de hele vak op zodat de rechterrand tegen de marge
        blijft die het thema nu al heeft. Eén plek die dat doet, zodat de
        tekening en de tests niet uit elkaar kunnen lopen.
        """
        x = int(_cfg.WIDTH * theme.pos("minimap.x", 0.78))
        y = int(_cfg.HEIGHT * theme.pos("minimap.y", 0.02))
        marge = max(8, int(_cfg.WIDTH * 0.013))
        x = min(x, _cfg.WIDTH - size - marge)
        y = min(y, _cfg.HEIGHT - size - marge)
        return max(0, x), max(0, y)

    def draw_minimap(self, game):
        stand = getattr(game, "minimap_mode", MINIMAP_UIT)
        if stand == MINIMAP_UIT:
            # Standaard uit. Niets tekenen en niets onthouden.
            return

        fog = getattr(game, "minimap", None)
        if fog is None:
            return
        # In spectate willen we dat de minimap de gevolgde speler volgt, niet
        # onze eigen dode speler. De game vervangt game.player al voor de camera,
        # maar we maken het hier explicieter voor de duidelijkheid.
        if getattr(game, 'spectating', False):
            px, py = game.player.pos.x, game.player.pos.y
            angle = game.player.angle
        else:
            px, py = game.player.pos.x, game.player.pos.y
            angle = game.player.angle
        # De stand GEZIEN gebruikt de kijkhoek en het bereik uit het thema,
        # maar niet de cheatstand: die zou de hele level onthouden.
        if stand == MINIMAP_GEZIEN:
            fog.zicht_tegels = theme.size("minimap.view_radius", 7)
        fog.update(M.MAP, M.width, M.height, px, py, angle, stand)

        onthouden, muur, vloer = self._minimap_lagen(fog)

        if stand == MINIMAP_VOLLEDIG:
            # Alles is al helder getekend, dus er is niets per frame te doen.
            laag = self._mm_helder
        else:
            # De onthouden laag is een kopie, en daarop zetten we de tegels neer
            # die de speler nu zicht op heeft. Een tegel die je ziet staat dus
            # helder, een tegel die je alleen kent donker.
            laag = onthouden.copy()
            for (tx, ty) in fog.zichtbaar:
                laag.set_at((tx, ty), muur if M.MAP[ty][tx] in WALL_VALUES else vloer)

        # De hele level in een vierkant vakje, met de verhouding intact. De
        # kaarten zijn niet vierkant (22 tot 40 tegels per kant), dus er blijft
        # een rand staan waar niets in staat.
        size = theme.scaled("minimap.size", 0.12, "min")
        kaart_w, kaart_h = M.width, M.height
        if kaart_w >= kaart_h:
            doel_w = size
            doel_h = max(1, int(size * kaart_h / kaart_w))
        else:
            doel_h = size
            doel_w = max(1, int(size * kaart_w / kaart_h))
        in_x = (size - doel_w) / 2
        in_y = (size - doel_h) / 2

        mm = pygame.Surface((size, size), pygame.SRCALPHA)
        mm.fill(tuple(theme.color("minimap.bg", (0, 0, 0, 160))))
        mm.blit(pygame.transform.scale(laag, (doel_w, doel_h)),
                (int(in_x), int(in_y)))

        # Wereldpositie -> pixel op het kaartje. Alle markers gaan hierdoorheen,
        # zodat ze op dezelfde plek staan als de tegel die ze beschrijven.
        def to_mm(wx, wy):
            return (in_x + (wx / TILE_SIZE) / kaart_w * doel_w,
                    in_y + (wy / TILE_SIZE) / kaart_h * doel_h)

        def op_kaart(wx, wy):
            mm_x, mm_y = to_mm(wx, wy)
            return mm_x, mm_y, 0 <= mm_x <= size and 0 <= mm_y <= size

        # ── de speler ──────────────────────────────────────────
        # Driehoekje in de kijkrichting, op de eigen positie. Nu de kaart de
        # hele level toont moet dat ook echt de plek zijn waar hij staat: een
        # pijltje in het midden zou zeggen "hier ben ik" terwijl de speler
        # ergens anders op de kaart staat.
        player_c = tuple(theme.color("minimap.player", (0, 255, 0)))
        outline_c = tuple(theme.color("minimap.player_outline", (0, 180, 0)))
        tri = max(4, int(size * 0.035))
        cx, cy = to_mm(px, py)
        # De speler staat normaal altijd op de kaart, maar niet het moment dat
        # de level net is gewisseld of de speler net is teruggezet na de lift.
        # Dan zou het pijltje in de rand zweven, dus dan tekenen we het niet.
        if 0 <= cx <= size and 0 <= cy <= size:
            # Eerst een grotere donkere driehoek, dan de puntige erop: zo blijft
            # het pijltje zichtbaar ook als de tegel eronder bijna dezelfde
            # kleur heeft.
            for schaal, kleur in ((1.9, outline_c), (1.4, player_c)):
                r = tri * schaal
                tip = (cx + r * math.cos(angle), cy + r * math.sin(angle))
                bl = (cx + r * math.cos(angle + 2.5), cy + r * math.sin(angle + 2.5))
                br = (cx + r * math.cos(angle - 2.5), cy + r * math.sin(angle - 2.5))
                pygame.draw.polygon(mm, kleur, [tip, bl, br])

        # ── teamgenoten ────────────────────────────────────────
        # Altijd zichtbaar, ook door muren heen: het zijn je eigen mensen en je
        # moet ze kunnen terugvinden als je ze kwijt bent.
        ally_c = tuple(theme.color("minimap.ally", (0, 150, 255)))
        for rp in game.remote_players:
            if rp is None:
                continue
            mm_x, mm_y, op_kaart_xy = op_kaart(rp.pos.x, rp.pos.y)
            if not op_kaart_xy:
                continue
            pygame.draw.circle(mm, ally_c, (int(mm_x), int(mm_y)),
                max(2, int(size * 0.025)))

        # ── vijanden ───────────────────────────────────────────
        # Alleen waar de speler nu echt zicht op heeft. Ze verdwijnen dus weer
        # zodra je je omdraait, en dat is precies zoals het in de wereld gaat.
        enemy_c = tuple(theme.color("minimap.enemy", (255, 50, 50)))
        for e in list(game.objects.get("enemies", [])):
            if e.health <= 0 or not fog.is_zichtbaar(e.pos.x, e.pos.y):
                continue
            mm_x, mm_y, op_kaart_xy = op_kaart(e.pos.x, e.pos.y)
            if not op_kaart_xy:
                continue
            pygame.draw.circle(mm, enemy_c, (int(mm_x), int(mm_y)),
                max(1, int(size * 0.015)))

        # ── uitgang, keycard en pickups ─────────────────────────
        # Pas als je ze gezien hebt. Anders weet de speler vanaf de eerste
        # seconde waar alles op de kaart ligt en is verkennen zinloos.
        s = max(2, int(size * 0.025))
        for naam, kleur_key in (("exit", "minimap.exit"),
                                ("keycard", "minimap.keycard"),
                                ("ammo", "minimap.ammo"),
                                ("health", "minimap.health")):
            obj = game.objects.get(naam)
            if obj is None:
                continue
            if not isinstance(obj, list):
                obj = [obj]
            kleur = tuple(theme.color(kleur_key, (255, 255, 255)))
            for o in obj:
                if o is None or not fog.is_gezien(o.pos.x, o.pos.y):
                    continue
                mm_x, mm_y, op_kaart_xy = op_kaart(o.pos.x, o.pos.y)
                if not op_kaart_xy:
                    continue
                pygame.draw.rect(mm, kleur,
                                 (int(mm_x) - s // 2, int(mm_y) - s // 2, s, s))

        border = theme.size("minimap.border", 2)
        if border > 0:
            border_c = tuple(theme.color("minimap.border", (200, 200, 200)))
            pygame.draw.rect(mm, border_c, (0, 0, size, size), border)

        screen_x, screen_y = self._minimap_positie(size)
        _cfg.SCREEN.blit(mm, (screen_x, screen_y))


Menu_inst = Menu()

class Button:
    def __init__(self, x, y, width, height, text, text_size=25,
                 text_color="black", button_color="white",
                 hover_text_color="white", hover_button_color="black",
                 game=None, target_state=None, mouse_visible=True,
                 function=None):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = text
        # `text_size` is de maat op 1080p en wordt hier omgeschakeld, zodat
        # geen enkele aanroeper hoeft te weten in welke resolutie we draaien.
        self.text_size = _scale_px(text_size)
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
                    if self.function == "spectate" and self.GAME:
                        # De state zet _start_spectating zelf, want die
                        # moet eerst een levende speler kiezen om te volgen.
                        self.GAME._start_spectating()
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
                    elif self.function == "minimap":
                        self.GAME.cycle_minimap()
                    if self.target_state == "reset":
                        self.GAME.reset_game()
                    elif self.target_state == "Stop":
                        audio.stop_all()
                        self.GAME.running = False
                    elif self.target_state == "game":
                        audio.unpause()
                    elif self.target_state == "menu":
                        audio.stop_all()

        bg = self.hover_button_color if hovering else self.button_color
        fg = self.hover_text_color if hovering else self.text_color
        pygame.draw.rect(_cfg.SCREEN, bg, self.rect, border_radius=theme.size("button.border_radius", 6))
        text_surf = self.font.render(self.text, True, fg)
        # Een lang etiket schaalt mee in plaats van over de rand van de
        # knop heen te lopen.
        text_surf = _fit_width(text_surf, self.rect.w - 8)
        tx = self.rect.x + (self.rect.w - text_surf.get_width()) // 2
        ty = self.rect.y + (self.rect.h - text_surf.get_height()) // 2
        _cfg.SCREEN.blit(text_surf, (tx, ty))

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
        self.font = load_numeric_font(theme.size("slider.label_font", int(_cfg.HEIGHT * 0.02)))
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

        pygame.draw.rect(_cfg.SCREEN, theme.color("slider.track", 'white'), [self.track_x, self.track_y - 4, self.w, 8], border_radius=4)

        filled_w = self.get_handle_x() - self.track_x
        pygame.draw.rect(_cfg.SCREEN, theme.color("slider.fill", (0, 200, 255)), [self.track_x, self.track_y - 4, filled_w, 8], border_radius=4)

        handle_x = self.get_handle_x()
        pygame.draw.circle(_cfg.SCREEN, theme.color("slider.handle_drag", (0, 200, 255)) if self.dragging else theme.color("slider.handle", 'white'), (int(handle_x), int(self.track_y)), self.handle_r)

        label_surf = self.font.render(f"{self.label}: {int(self.value * 100)}%", True, theme.color("slider.label", 'white'))
        _cfg.SCREEN.blit(label_surf, (self.track_x, self.track_y - int(_cfg.HEIGHT * theme.pos("mp.title_y", 0.04))))


# ---- Het grootste deel hiervan is AI code, eerder flavour en tutorial dan functionele game code-----
class Tekstballon:
    def __init__(self, text, y_pos, x_pos, GAME, max_width=280, padding=10,):
        self.text = text
        self.y_pos = y_pos
        self.x_pos = x_pos
        self.max_width = max_width
        self.padding = padding
        # Let op: module-niveau _font_px, niet self._font_px. Tekstballon is
        # geen Menu, dus die methode bestaat hier niet.
        self.font = load_font(_font_px("ui.font.speech", 20))
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
            _cfg.SCREEN,
            theme.color("speech_bubble.border", (0, 0, 0)),
            [x - 4, y - 4, box_w + 8, box_h + 8],
            border_radius=8
        )
        pygame.draw.rect(
            _cfg.SCREEN,
            theme.color("speech_bubble.bg", (255, 255, 255)),
            [x, y, box_w, box_h],
            border_radius=8
        )

        for i, line in enumerate(raw_lines):
            _cfg.SCREEN.blit(
                self.font.render(line, False, theme.color("speech_bubble.text", (0, 0, 0))),
                (x + self.padding, y + self.padding + i * line_height)
            )

        tail_x = x + box_w // 2
        tail_y = y + box_h

        pygame.draw.polygon(
            _cfg.SCREEN,
            theme.color("speech_bubble.tail_outer", (0, 0, 0)),
            [(tail_x - 12, tail_y),
             (tail_x + 12, tail_y),
             (tail_x, tail_y + 22)]
        )
        pygame.draw.polygon(
            _cfg.SCREEN,
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
            Tekstballon(text, _cfg.HEIGHT - int(_cfg.HEIGHT * theme.pos("speech_bubble.y", 0.43)), int(_cfg.WIDTH * theme.pos("speech_bubble.x", 0.01)), self.Game).draw()
            _cfg.SCREEN.blit(_cfg.TUTORIAL, (0, _cfg.HEIGHT - int(_cfg.HEIGHT * theme.pos("tutorial.image_y", 0.33))))

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
