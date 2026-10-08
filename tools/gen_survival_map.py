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
# Zestien kamers van 7x7, straten van één tegel breed en een ring-corridor
# van twee tegels breed die rondom loopt. Elke kamer heeft minstens twee
# doorgangen: een doodlopende cel betekent in survival een speler die
# vastzit in een hoek. De straten breken op alle zestien plekken door de
# scheidingsmuur, zodat er aan geen enkel uiteinde een doodlopend straatje
# overblijft.
#
# Waarom 48 en niet 32: de gangen en kamers waren ruim maar de wereld
# zelf klein (keuze 2026-10-08). 48x48 is 2,25x het oppervlak, met
# smallere gangen en kamers van ~10 breed naar 7.
#
#   .  leeg        #  muur        @  spelerspawn
#   X  vijand      A  ammo        H  health
#
# Geen E, K of B: survival heeft geen lift, dus geen uitgang, geen
# keycard en geen boss.
FORMAAT = 48

GRONDPLAN = """
################################################
#...........H......................H...........#
#.X....................X.....................X.#
#..#.#########.#########.#########.##########..#
#...X.........X.........A.........X............#
#..#.######.##.######.##.######.##.######.###..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.........#.........#.........#.........##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.#...X...#.#...A...#.#...X...#.#...A...##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.#.........#.........#.........#.......##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.##.######.##.######.##.######.##.#######..#
#...X.........H.........H.........X............#
#..#.######.##.######.##.######.##.######.###..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.........#.........#.........#.........##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.#...A...#.#...X...#.#...A...#.#...X...##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.#.........#.........#.........#.......##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#.X#.##.######.##.######.##.######.##.#######X.#
#...A.........H.........@.........A............#
#..#.######.##.######.##.######.##.######.###..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.........#.........#.........#.........##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.#...X...#.#...A...#.#...X...#.#...A...##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.#.........#.........#.........#.......##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.##.######.##.######.##.######.##.#######..#
#...X.........X.........A.........X............#
#..#.######.##.######.##.######.##.######.###..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.........#.........#.........#.........##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.#...A...#.#...X...#.#...A...#.#...X...##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.#.........#.........#.........#.......##..#
#..#.#.......#.#.......#.#.......#.#.......##..#
#..#.#########.#########.#########.##########..#
#..#.#########.#########.#########.##########..#
#.X....................X.....................X.#
#...........H......................H...........#
################################################
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


def rechthoeken(rijen):
    """Alle maximale rechthoeken vloer van minstens 3x3, één keer elk.

    Elke linkerbovenhoek levert de breedste rij die daar begint, en die
    breedte zolang elke rij eronder nog haalt. Zo hoef je niet te weten
    waar de kamers staan om ze te vinden: een kamer is in dit plan gewoon
    een blok vloer dat nergens tegen een gang aan ligt zonder muur.
    """
    formaat = len(rijen)
    breedte = [[0] * formaat for _ in range(formaat)]
    for y in range(formaat):
        for x in range(formaat - 1, -1, -1):
            if rijen[y][x] == "#":
                breedte[y][x] = 0
            else:
                # De rechterkolom heeft geen buur meer.
                rest = breedte[y][x + 1] if x + 1 < formaat else 0
                breedte[y][x] = 1 + rest

    uit = []
    for y in range(formaat):
        for x in range(formaat):
            b = breedte[y][x]
            if b < 3:
                continue
            hoogte, yy = 0, y
            while yy < formaat and breedte[yy][x] >= b:
                hoogte += 1
                yy += 1
            if hoogte >= 3:
                uit.append((x, y, x + b - 1, y + hoogte - 1))
    return uit


def deuren_rond(rijen, vak):
    """De vloercellen die net buiten het vak liggen: dat zijn de deuren.

    De cellen er net buiten zijn normaal muur, behalve waar een deur zit.
    """
    x0, y0, x1, y1 = vak
    formaat = len(rijen)
    teller = 0
    for x in range(x0, x1 + 1):
        for y in (y0 - 1, y1 + 1):
            if 0 <= y < formaat and rijen[y][x] != "#":
                teller += 1
    for y in range(y0, y1 + 1):
        for x in (x0 - 1, x1 + 1):
            if 0 <= x < formaat and rijen[y][x] != "#":
                teller += 1
    return teller


def valideer(rijen):
    """Alle redenen om deze kaart te weigeren. Lege lijst = in orde."""
    fouten = []
    formaat = FORMAAT

    hoogte = len(rijen)
    if hoogte != formaat:
        fouten.append(f"{hoogte} rijen in plaats van {formaat}")
        return fouten

    for y, rij in enumerate(rijen):
        if len(rij) != formaat:
            fouten.append(f"rij {y} is {len(rij)} tegels breed in plaats "
                          f"van {formaat}")

    # Onbekende tekens: die zouden als muur of leeg doorglippen.
    for y, rij in enumerate(rijen):
        for x, c in enumerate(rij):
            if c not in TEKEN_KLEUR:
                fouten.append(f"onbekend teken {c!r} op ({x}, {y})")

    if fouten:
        return fouten

    # De rand is overal muur, anders loopt de speler het plaatje uit en
    # vallen de raycasts buiten de array.
    for x in range(formaat):
        if rijen[0][x] != "#":
            fouten.append(f"bovenrand op x={x} is geen muur")
        if rijen[formaat - 1][x] != "#":
            fouten.append(f"onderrand op x={x} is geen muur")
    for y in range(formaat):
        if rijen[y][0] != "#":
            fouten.append(f"linkerrand op y={y} is geen muur")
        if rijen[y][formaat - 1] != "#":
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
            if not (0 <= nx < formaat and 0 <= ny < formaat):
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

    # Geen doodlopende cel: een vloertegel met maar één vloerbuur is een
    # zak waar je in verdwijnt en niet meer uitkomt.
    for y, rij in enumerate(rijen):
        for x, c in enumerate(rij):
            if c == "#":
                continue
            buren = sum(1
                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                        if 0 <= x + dx < formaat and 0 <= y + dy < formaat
                        and rijen[y + dy][x + dx] != "#")
            if buren <= 1:
                fouten.append(f"doodlopende cel op ({x}, {y})")

    # Elke kamer heeft minstens twee doorgangen. Eén deur betekent dat je
    # je in een hoek laat opjagen en er niet meer uitkomt. Die regel staat
    # in het dossier, en hier is het dus geen afspraak maar een controle:
    # een kamer is een blok vloer, en wat er net buiten ligt is muur
    # behalve bij een deur.
    for vak in rechthoeken(rijen):
        deuren = deuren_rond(rijen, vak)
        if deuren < 2:
            x0, y0, x1, y1 = vak
            fouten.append(f"blok ({x0}, {y0})-({x1}, {y1}) heeft maar "
                          f"{deuren} deur")

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
