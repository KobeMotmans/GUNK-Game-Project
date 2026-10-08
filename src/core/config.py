"""
config.py - Centrale configuratie en constanten voor het spel
"""

import os
import pygame
from math import pi, tan
from .paths import asset_path, resolve_asset
from .theme import theme

# ── Display initialisatie (headless-vriendelijk) ─────────────
# Zet GUNK_HEADLESS=1 in de omgeving om pygame display over te slaan.
# Gebruikt door run_server.py om geen venster te openen.
_HEADLESS = os.environ.get("GUNK_HEADLESS") == "1"

_resolution_quality = "high"

def set_resolution(quality: str):
    global _resolution_quality, NUM_RAYS, DELTA_ANGLE
    _resolution_quality = quality
    if _HEADLESS:
        return
    divisor = 4 if quality == "high" else 8
    NUM_RAYS = WIDTH // divisor
    DELTA_ANGLE = FOV / NUM_RAYS

def resize_display(w, h):
    global WIDTH, HEIGHT, SCREEN, PROJ_DIST, NUM_RAYS, DELTA_ANGLE
    global SCREEN_FLASH, SCREEN_DEAD, VICTORY_SCREEN, TUTORIAL
    global DAMAGE_FLASH, AMMO_FLASH, KEYCARD_FLASH, HEALTH_FLASH
    if _HEADLESS:
        return
    WIDTH = w
    HEIGHT = h
    SCREEN = pygame.display.set_mode((w, h), pygame.RESIZABLE | pygame.DOUBLEBUF)
    PROJ_DIST = int((WIDTH / 2) / tan(FOV / 2))
    set_resolution(_resolution_quality)

    SCREEN_FLASH = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.damage_flash", "textures/ui/Damage_Flash.png"))).convert_alpha(), (WIDTH, HEIGHT))
    SCREEN_DEAD = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.dead", "textures/ui/dead.png"))).convert_alpha(), (WIDTH, HEIGHT))
    TUTORIAL = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.tutorial", "textures/ui/bilal.png"))).convert_alpha(), (200, 200))
    VICTORY_SCREEN = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.victory", "textures/ui/victory.png"))).convert_alpha(), (WIDTH, HEIGHT))

    DAMAGE_FLASH = SCREEN_FLASH.copy()
    DAMAGE_FLASH.fill((255,0,0), special_flags=pygame.BLEND_MULT)
    AMMO_FLASH = SCREEN_FLASH.copy()
    AMMO_FLASH.fill((255,215,0), special_flags=pygame.BLEND_MULT)
    KEYCARD_FLASH = SCREEN_FLASH.copy()
    KEYCARD_FLASH.fill((0,0,255), special_flags=pygame.BLEND_MULT)
    HEALTH_FLASH = SCREEN_FLASH.copy()
    HEALTH_FLASH.fill((0,255,0), special_flags=pygame.BLEND_MULT)

if not _HEADLESS:
    pygame.init()
    infoObject = pygame.display.Info()
    WIDTH = infoObject.current_w
    HEIGHT = infoObject.current_h - 50
    SCREEN = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE | pygame.DOUBLEBUF)
else:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    WIDTH = 1920
    HEIGHT = 1080
    SCREEN = None

# Map instellingen
TILE_SIZE = 100
MAP_PATH = [asset_path("assets/textures/floor/floor_5.png"), asset_path("assets/textures/floor/floor_3.png"), asset_path("assets/textures/floor/floor_2.png"), asset_path("assets/textures/floor/floor_1.png"), asset_path("assets/textures/floor/floor_0.png")]
MAX_LEVEL = len(MAP_PATH)-1
START_ANGLES = [-pi/2, 0, 0, pi/2, -pi/2]
ELEV_SPEED = 10
ELEV_TIME = 30

# Raycasting instellingen
FOV = pi / 2
MAX_DEPTH = 1000
PROJ_DIST = int((WIDTH / 2) / tan(FOV / 2))  # tan(FOV/2) = tan(pi/4) = 1
NUM_RAYS = 0
DELTA_ANGLE = 0

# Speler instellingen
PLAYER_SPEED = 6
PLAYER_ROT_SPEED = 0.0008

START_HEALTH = 10

# Sprite instellingen
SPRITE_SIZE = 100
MIN_DIST = 40
ATTACK_DIST = 43

# Hoe vaak A* opnieuw berekend wordt (in frames)
PATHFIND_INTERVAL = 20

# Wapen instellingen
WEAPON_OFFSET_X = 0.0  # gecentreerd

#Object instellingen
HEALTH_CHANCE = 0.20

SFX_VOLUME = 0.3
HEALTH_REGEN = 2

START_AMMO = 100
AMMO_CAP = 200
# Wat één ammo-pickup waard is. Ook het getal waarmee een dode speler zijn
# ammo in hele oppakkingen laat liggen, dus dit staat op één plek.
AMMO_PICKUP_AMOUNT = 50

# ── Gamemodes ────────────────────────────────────────────────────────
# Elke gamemode heeft hier een blok met precies dezelfde vorm. Er is géén
# "standaard gamemode": de code kiest nergens een mode als waarheid, die
# leest alleen uit deze tabel. Een nieuwe mode toevoegen = een nieuwe
# sleutel, en de rest van de game gaat vanzelf mee.
GAMEMODES = {
    "campaign": {
        # Wat er in het moduskeuzescherm onder de knop staat. Korte zin,
        # in het Nederlands, zoals de rest van de toelichting.
        "omschrijving": "Verlaag elke verdieping en ontsnap via de lift.",
        "start_health": 10,
        "health_cap": 10,
        "start_ammo": START_AMMO,
        "ammo_cap": AMMO_CAP,
        # De lift jaagt de volgende floor aan.
        "level_progression": True,
        "uses_elevator": True,
        # De klok loopt en een betere tijd wordt bewaard, maar alleen als
        # je er ook echt uitkomt: een run die op de vloer eindigt is geen
        # volle run. Daarom "escape" en niet "death" - zie _einde_run().
        "run_timer": True,
        "save_pb": True,
        "pb_bij": "escape",
        # Geen teller van de kills tijdens het spelen: de campaign-HUD
        # blijft zoals hij is. Het scoretje op de eindschermen blijft wel.
        "hud_score": False,
    },
    "survival": {
        "omschrijving": "Blijf in leven. De stroom houdt niet op.",
        # Ruime HP-balk zodat damage in echte stappen kan lopen
        # (17, 24, ...) in plaats van tikjes van 10.
        "start_health": 100,
        "health_cap": 100,
        "start_ammo": 300,
        # Boven de campaign-cap: anders zou de startvoorraad al afgeknepen
        # worden zodra de server hem sanitizet.
        "ammo_cap": 400,
        # Geen floors: je blijft op de kaart tot je valt.
        "level_progression": False,
        "uses_elevator": False,
        # De klok ís de run: hij loopt, en de tijd wordt bewaard zodra de
        # run voorbij is. De kills staan ernaast als ranglijst. In survival
        # eindigt een run bij het overlijden - er is geen uitgang - dus daar
        # is "death" en niet "escape"; anders werd nooit iets opgeslagen.
        "run_timer": True,
        "save_pb": True,
        "pb_bij": "death",
        # Tijdens het spelen het aantal kills erbij, naast de tijd.
        "hud_score": True,
        # Eén eigen kaart. Daardoor is er geen levelnummer om af te leiden
        # en ook geen START_ANGLES[level]: pad en hoek komen hier vandaan.
        # Zie kaart_voor().
        "map": asset_path("assets/textures/floor/survival.png"),
        "start_angle": -pi / 2,
        # De stroom brengt de vijanden; er staat er geen bij de start.
        "spawn_enemies_at_start": False,
        # De hele regeling van die stroom, als één blok. Geen
        # `if mode == "survival"` in de gameplay-code: die leest dit en
        # draait het. Een mode zonder dit blok heeft geen stroom.
        # Zie src/core/stroom.py.
        "stream": {
            # Hoeveel er tegelijk in leven mogen zijn: 4 bij de start, 16
            # als plafond. Het plafond is er omdat de map 24 bronnen heeft
            # en een stapeling tot de boel vastloopt; 16 laat acht plekken
            # vrij zodat de stroom altijd ergens heen kan. Let op: de kaart
            # is sinds 2026-10-08 2,25x zo groot terwijl dit plafond hetzelfde
            # bleef, dus de vijandendichtheid per tegel is gezakt.
            "start_alive": 4,
            "max_alive": 16,
            # Tijd waarin 4 -> 16 en de interval 2 -> 8 doorlopen wordt.
            # Vijf minuten: lang genoeg om op te warmen, kort genoeg dat je
            # het plafond in een zittende sessie haalt.
            "ramp_seconds": 300,
            # Interval tussen twee spawns aan begin en einde. Langer wordend
            # = minder vaak een nieuwe erbij, zoals het dossier wil: het
            # plafond bepaalt de druk, de interval voorkomt dat er per
            # seconde drie bij komen zodra de kaart al vol is.
            "start_interval": 2.0,
            "end_interval": 8.0,
            # De mix, begin en einde. Gewichten, dus 0 = nooit. Tanks
            # beginnen op nul en komen er later bij.
            "start_mix": {"normal_enemy": 3, "fast_enemy": 1, "tank_enemy": 0},
            "end_mix": {"normal_enemy": 2, "fast_enemy": 2, "tank_enemy": 2},
            # Een spawn-punt is bezet als er al een vijand op minder dan dit
            # staat (pixels; één tegel).
            "spawn_straal": 64.0,
        },
    },
}

DEFAULT_GAMEMODE = "campaign"


def gamemode(name):
    """Config van een gamemode.

    Onbekende naam valt terug op DEFAULT_GAMEMODE, zodat een verkeerde of
    verouderde naam nooit een KeyError midden in een run veroorzaakt.
    """
    return GAMEMODES.get(name, GAMEMODES[DEFAULT_GAMEMODE])


def kaart_voor(mode, level=0):
    """(kaartpad, start_angle) voor een mode op een level.

    Een mode met een eigen `"map"` bepaalt zelf pad én hoek, en het
    levelnummer doet er dan niet toe: survival heeft precies één kaart.
    Zonder eigen kaart tellen MAP_PATH en START_ANGLES gewoon mee, dus
    de campaign krijgt exact dezelfde twee waarden als hiervoor.

    Alle plekken die een kaart laden vragen hierom in plaats van zelf
    `MAP_PATH[level]` te nemen. Zou een enkele plek dat wel blijven
    doen, dan waren er twee waarheden en werkte een mode met eigen kaart
    op de ene plek wel en op de andere niet - precies het soort tweede
    waarheid dat de gamemodes-tabellen er juist uit moesten halen.
    """
    config = gamemode(mode)
    pad = config.get("map")
    if pad is not None:
        return pad, config.get("start_angle", -pi / 2)
    return MAP_PATH[level], START_ANGLES[level]


# ── Drops ────────────────────────────────────────────────────────────
# Wat elk voorwerp oplevert staat op het voorwerp zelf, niet in een if in
# de interactie-code. Daardoor is een tweede, grotere variant gewoon een
# extra regel hier, in plaats van een nieuwe aftakking in objects.py.
#
#   give    het effect: "ammo", "health", "keycard" of "exit"
#   amount  hoeveel het oplevert (health/ammo; keycard en exit negeren dit)
#   sound   naam in game.sounds; None = geen geluid
#   size    schaalfactor t.o.v. SPRITE_SIZE; 1.0 is exact zoals nu
#   radius  opnamestraal in pixels; None = MIN_DIST (zoals nu)
#
# De campaign-waarden hieronder zijn letterlijk de waarden die er voorheen
# hardcoded in objects.py stonden, zodat de campaign niets verandert.
DROPS = {
    "objects/ammo": {"give": "ammo", "amount": AMMO_PICKUP_AMOUNT,
                     "sound": "ammo", "size": 1.0, "radius": None},
    "objects/health": {"give": "health", "amount": HEALTH_REGEN,
                       "sound": "drink", "size": 1.0, "radius": None},
    "objects/keycard": {"give": "keycard", "amount": 1,
                        "sound": "key", "size": 1.0, "radius": None},
    "objects/exit": {"give": "exit", "amount": 0,
                     "sound": None, "size": 1.0, "radius": None},
    # Grotere varianten. Niet in de campaign (die roept deze sleutels nooit
    # aan), maar survival kan ze spawnen met bv.
    # PickupObject("objects/health_big", x, y).
    "objects/health_big": {"give": "health", "amount": 25,
                           "sound": "drink", "size": 1.6, "radius": None},
    "objects/ammo_big": {"give": "ammo", "amount": 150,
                         "sound": "ammo", "size": 1.6, "radius": None},
}


def drop(type_name):
    """Drop-data voor een voorwerp. Onbekende sleutel = lege data,
    zodat een nieuwe tekstuur nooit een crash geeft."""
    return DROPS.get(type_name, {})


# ── Muurtexturen ────────────────────────────────────────────────────
# Muurtegel-waarde -> tekstuur. Dit is tegelijk dé definitie van "muur":
# map_loader.WALL_VALUES is hieruit afgeleid en collision, raycaster,
# minimap en padvinding lezen daar allemaal van. Een nieuwe muursoort
# toevoegen = één regel hier + één kleur in map_loader.color_to_number.
#
# Een pad dat niet bestaat valt terug op een procedureel patroon met
# dezelfde bestandsnaam (zie assets/wall_textures.py), zodat de renderer
# ook zonder kunstwerken werkt en meteen zichtbaar is. Echte PNG's horen
# in assets/textures/wall/.
WALL_TEXTURES = {
    1: "textures/wall/beton.png",
}

# Aantal afstandslicht-niveaus. Elk niveau is een vooraf verdunde kopie van
# de tekstuur; per frame kost dat alleen een tabelindex, dus meer banden is
# vrijwel gratis en geeft geen zichtbare trappen over een muurvlak.
WALL_SHADE_BANDS = 32

# Muurtexturen worden hier naartoe geschaald bij het laden. Groot genoeg voor
# scherpe muren (per ray bemonsteren we één texelkolom per schermkolom van
# 4 px), klein genoeg om niet 16000 oppervlakken per textuur te vullen als
# iemand een 512x512 afbeelding als muur opgeeft.
WALL_TEXTURE_SIZE = 128


def wall_texture(value):
    """Tekstuurpad voor een muurtegel.

    Onbekende waarde valt terug op de eerste muur, zodat een nieuwe
    tegelwaarde nooit een KeyError midden in een run geeft.
    """
    return WALL_TEXTURES.get(value) or next(iter(WALL_TEXTURES.values()))


if not _HEADLESS:
    SCREEN_FLASH = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.damage_flash", "textures/ui/Damage_Flash.png"))).convert_alpha(), (WIDTH, HEIGHT))
    SCREEN_DEAD = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.dead", "textures/ui/dead.png"))).convert_alpha(), (WIDTH, HEIGHT))
    TUTORIAL = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.tutorial", "textures/ui/bilal.png"))).convert_alpha(), (200, 200))

    VICTORY_SCREEN = pygame.transform.scale(pygame.image.load(resolve_asset(theme.get("textures.ui.victory", "textures/ui/victory.png"))).convert_alpha(), (WIDTH, HEIGHT))


    DAMAGE_FLASH = SCREEN_FLASH.copy()
    DAMAGE_FLASH.fill((255,0,0), special_flags=pygame.BLEND_MULT)

    AMMO_FLASH = SCREEN_FLASH.copy()
    AMMO_FLASH.fill((255,215,0), special_flags=pygame.BLEND_MULT)

    KEYCARD_FLASH = SCREEN_FLASH.copy()
    KEYCARD_FLASH.fill((0,0,255), special_flags=pygame.BLEND_MULT)

    HEALTH_FLASH = SCREEN_FLASH.copy()
    HEALTH_FLASH.fill((0,255,0), special_flags=pygame.BLEND_MULT)
else:
    SCREEN_FLASH = None
    SCREEN_DEAD = None
    TUTORIAL = None
    VICTORY_SCREEN = None
    DAMAGE_FLASH = None
    AMMO_FLASH = None
    KEYCARD_FLASH = None
    HEALTH_FLASH = None

#Enemy instellingen
AGGRO_DIST = 1000

# Multiplayer instellingen
DEFAULT_PORT = 5555
MAX_PLAYERS = 6
ELEVATOR_WAIT_DIST = 200   # pixels van exit tot speler
ELEVATOR_WAIT_FRAMES = 90  # frames na "allemaal klaar" voor lift vertrekt
ELEVATOR_STUCK_FRAMES = 1800  # frames dat de lift op een speiler wacht voor de
                              # groep volledig is, voordat hij alsnog vertrekt.
                              # Voorkomt een permanent vastgelopen level als er
                              # een speler is die blijft hangen.

