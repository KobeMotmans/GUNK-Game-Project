#!/usr/bin/env python3
"""Bouwt de survival-kaart uit ASCII.

    py tools/gen_survival_map.py

De ASCII hieronder is de bron van waarheid voor het grondplan; de PNG is
het product dat het spel laadt. SURVIVAL.md toont hetzelfde plan met
uitleg erbij, en de test `survival_ascii_in_het_dossier_is_dezelfde`
houdt die twee gelijk zodat het document niet stilletjes achterloopt.

Twee dingen die expres niet gekopieerd worden:

- **De kleurentabel.** De tekens worden vertaald via
  `map_loader.color_to_number`, dezelfde tabel die het spel gebruikt.
  Staat er een kleur in die de loader niet kent, dan zou
  `png_to_list_fast` er midden in een run met een KeyError op knallen;
  hier faalt het dus meteen, bij het bouwen.
- **De validaties.** Een kaart die niet klopt, wordt niet geschreven.
  Ruzie maken over een defecte PNG die al in de repo ligt is veel
  vervelender dan hem nu weigeren te maken.
"""

import os
import sys

# Zonder dit crasht `convert_alpha()` in de rest van de codebase op een
# machine zonder venster. De generator zelf tekent niets.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.pop("GUNK_HEADLESS", None)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image                                     # noqa: E402
from src.core.map_loader import color_to_number           # noqa: E402

# ── Het grondplan ─────────────────────────────────────────────────────
# Zes kamers, een ring-corridor van twee tegels breed en twee gangen die
# elkaar in het midden kruisen. Elke kamer heeft minstens twee
# doorgangen: een doodlopende cel betekent in survival een speler die
# vastzit in een hoek.
#
#   .  leeg        #  muur        @  spelerspawn
#   X  vijand      A  ammo        H  health
#
# Geen E, K of B: survival heeft geen lift, dus geen uitgang, geen
# keycard en geen boss.
GRONDPLAN = """
################################
#H...A........................H#
#.X.....X..............X.....X.#
#..#######..###..#######..###..#
#..#....#.....#..#..........#..#
#..#....#.....#XX#..........#..#
#..#..A.#..A..#..#....A.....#..#
#..#....#.....#..#..........#..#
#.X.....#........#..........#X.#
#.......#........#..........#..#
#..#....#.....#..#..........#..#
#..#....#.....#..#..........#..#
#..#....#.....#..#..........#..#
#..#....#.....#..#..........#..#
#..##..########..#####..#####..#
#....X.................H..X....#
#....X..H.......@.........X....#
#..#####..#####..############..#
#..#..........#..#..........#..#
#..#..........#.......A.....#..#
#..#..........#.............#..#
#..#..........#..#..........#..#
#.....A.......#..#######..###..#
#.X...........#..#..........#X.#
#..#..........#.............#..#
#..#..........#.......A........#
#..#..........#XX#.............#
#..#..........#..#..........#..#
#..############..############..#
#.X.....X..............X.....X.#
#H........................A...H#
################################
"""

# Alle tekens die in het grondplan mogen voorkomen en hun tegelkleur.
# De waarden móeten in map_loader.color_to_number staan; dat wordt
# hieronder gecontroleerd, niet aangenomen.
TEKEN_KLEUR = {
    ".": (255, 255, 255),   # 0 leeg
    "#": (0, 0, 0),         # 1 muur
    "E": (0, 255, 0),       # 2 uitgang
    "X": (255, 0, 0),       # 3 vijand
    "@": (0, 255, 255),     # 4 spelerspawn
    "K": (0, 0, 255),       # 5 keycard
    "A": (255, 255, 0),     # 6 ammo
    "B": (255, 0, 255),     # 7 boss
    "H": (255, 128, 0),     # 8 health
}

# Wat survival níet mag hebben. Een E zou een lift neerzetten op een
# groene tegel die er niet is, en dat komt dan als (0,0) binnen.
VERBODEN = "EKB"

MIN_AFSTAND_VIJAND = 5   # tegels, vogelvlucht
UITVOER = os.path.join(ROOT, "assets", "textures", "floor", "survival.png")


def lees_grondplan(bron=GRONDPLAN):
    """Haal de regels uit de bron; lege regels aan de randen negeren."""
    return [regel for regel in bron.splitlines() if regel.strip()]


def controleer_tabel():
    """Elke kleur die we kunnen schrijven moet de loader ook kennen."""
    onbekend = {kleur: teken
                for teken, kleur in TEKEN_KLEUR.items()
                if kleur not in color_to_number}
    if onbekend:
        return ["kleur niet in map_loader.color_to_number: "
                + ", ".join(f"{t}={k}" for k, t in onbekend.items())]
    return []


def vind(rijen, teken):
    return [(x, y) for y, rij in enumerate(rijen) for x, c in enumerate(rij)
            if c == teken]


def valideer(rijen):
    """Alle redenen om deze kaart te weigeren. Lege lijst = in orde."""
    fouten = []

    hoogte = len(rijen)
    if hoogte != 32:
        fouten.append(f"{hoogte} rijen in plaats van 32")
        return fouten

    for y, rij in enumerate(rijen):
        if len(rij) != 32:
            fouten.append(f"rij {y} is {len(rij)} tegels breed in plaats van 32")

    # Onbekende tekens: die zouden als muur of leeg doorglippen.
    for y, rij in enumerate(rijen):
        for x, c in enumerate(rij):
            if c not in TEKEN_KLEUR:
                fouten.append(f"onbekend teken {c!r} op ({x}, {y})")

    if fouten:
        return fouten

    # De rand is overal muur, anders loopt de speler het plaatje uit en
    # vallen de raycasts buiten de array.
    for x in range(32):
        if rijen[0][x] != "#":
            fouten.append(f"bovenrand op x={x} is geen muur")
        if rijen[31][x] != "#":
            fouten.append(f"onderrand op x={x} is geen muur")
    for y in range(32):
        if rijen[y][0] != "#":
            fouten.append(f"linkerrand op y={y} is geen muur")
        if rijen[y][31] != "#":
            fouten.append(f"rechterrand op y={y} is geen muur")

    # Precies één startpunt.
    spawns = vind(rijen, "@")
    if len(spawns) != 1:
        fouten.append(f"{len(spawns)} spelerspawns in plaats van één")
        return fouten
    sx, sy = spawns[0]

    # Geen lift, keycard of boss.
    for teken in VERBODEN:
        if teken in "".join(rijen):
            fouten.append(f"survival mag geen {teken!r}-tegel hebben")

    # Alles bereikbaar vanaf de spawn. Een gesloten cel is een deel van
    # de kaart waar nooit iets komt, en dus verborgen rommel.
    bereik = {(sx, sy)}
    stapel = [(sx, sy)]
    while stapel:
        x, y = stapel.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < 32 and 0 <= ny < 32):
                continue
            if (nx, ny) in bereik or rijen[ny][nx] == "#":
                continue
            bereik.add((nx, ny))
            stapel.append((nx, ny))

    for y, rij in enumerate(rijen):
        for x, c in enumerate(rij):
            if c != "#" and (x, y) not in bereik:
                fouten.append(f"tegel {c!r} op ({x}, {y}) is niet bereikbaar "
                              f"vanaf de spawn")

    # De eerste vijand moet niet al naast je staan.
    for x, y in vind(rijen, "X"):
        afstand = ((x - sx) ** 2 + (y - sy) ** 2) ** 0.5
        if afstand < MIN_AFSTAND_VIJAND:
            fouten.append(f"vijand op ({x}, {y}) staat {afstand:.1f} tegels "
                          f"van de spawn (< {MIN_AFSTAND_VIJAND})")

    return fouten


def schrijf_png(rijen, pad):
    img = Image.new("RGB", (len(rijen[0]), len(rijen)))
    for y, rij in enumerate(rijen):
        for x, c in enumerate(rij):
            img.putpixel((x, y), TEKEN_KLEUR[c])
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    img.save(pad)
    return img


def samenvatting(rijen):
    telling = {}
    for rij in rijen:
        for c in rij:
            telling[c] = telling.get(c, 0) + 1
    return telling


def main():
    rijen = lees_grondplan()

    fouten = controleer_tabel() + valideer(rijen)
    if fouten:
        print("De survival-kaart is niet in orde:")
        for f in fouten:
            print("  -", f)
        return 1

    img = schrijf_png(rijen, UITVOER)
    telling = samenvatting(rijen)
    print(f"{UITVOER}")
    print(f"  {img.size[0]}x{img.size[1]} tegels")
    print("  " + ", ".join(f"{t}={telling[t]}" for t in "@XAH" if t in telling))
    print("  alle validaties gehaald")
    return 0


if __name__ == "__main__":
    sys.exit(main())
