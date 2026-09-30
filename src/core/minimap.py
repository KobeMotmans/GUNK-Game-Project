"""
minimap.py - Wat de speler op de minimap heeft gezien

De minimap tekent de hele level, maar alleen de tegels die de speler ook echt
heeft gezien. Zicht komt uit een flood-fill vanaf de tegel waar de speler
staat:

  - een muur is zelf zichtbaar, maar verspreidt het zicht niet verder, dus je
    ziet nooit door een muur heen;
  - de verspreiding stopt na ZICHT_TEGELS stappen, zodat je niet het hele
    level in een oogopslag ziet;
  - de verspreiding blijft binnen de kijkhoek van de speler, want dit is een
    raycaster en je kunt niet om je eigen as kijken.

Wat je gezien hebt blijft onthouden in `gezien`, wat je nú ziet staat in
`zichtbaar`. Vijanden komen daarom alleen in `zichtbaar` terecht: die moet je
echt voor je neus staan. Uitgang, keycard en pickups volstaan in `gezien`:
daarvan hoef je alleen te weten dát ze ergens zijn.

Bij het wisselen van level wordt alles vergeten. Dat herkennen we aan het
kaartobject en niet aan het levelnummer, want bij zelfhosten draait de server
in een draadje in hetzelfde proces en deelt hij de singleton M. Daardoor
loopt M.map_level vooruit op het moment dat de client iets te tekenen krijgt.
`M.MAP` is bij elke level een verse lijst (png_to_list_fast), dus vergelijken
met `is` is waterdicht.
"""

import math
from collections import deque

from .config import FOV, TILE_SIZE

# De drie standen die de knop in Instellingen laat zien.
UIT = 0
GEZIEN = 1
VOLLEDIG = 2

STANDEN = (UIT, GEZIEN, VOLLEDIG)

# Standaard zichtbereik in tegels. De knop in het thema (minimap.view_radius)
# kan dit per pack overschrijven.
ZICHT_TEGELS = 7

_STAPPEN = ((1, 0), (-1, 0), (0, 1), (0, -1))


class Minimap:
    """Onthoudt welke tegels van de huidige level de speler heeft gezien.

    `update()` is het enige dat iets verandert; daarna zijn `gezien` en
    `zichtbaar` sets van (x, y)-tegeltuples. De tekening in Menu.py leest ze
    alleen.
    """

    def __init__(self, zicht_tegels=ZICHT_TEGELS):
        self.zicht_tegels = zicht_tegels
        self.kaart = None
        self.breedte = 0
        self.hoogte = 0
        self.gezien = set()
        self.zichtbaar = set()
        # Geteld op zodra `gezien` verandert, zodat de tekening weet dat de
        # onthouden laag opnieuw getekend moet worden. Bij een levelwissel
        # verandert de kaart immers van vorm, en dat merk je hieraan.
        self.versie = 0

    def _vergeet(self):
        self.gezien = set()
        self.zichtbaar = set()
        self.versie += 1

    def _bind(self, kaart, breedte, hoogte):
        """Zet de kaart waarvoor dit exemplaar geldt.

        Een ander kaartobject betekent een ander level, en dan moet de
        onthouden kaart weg. Dezelfde lijst nogmaals aanbieden doet niets, dus
        de speler die honderden frames per minuut dezelfde kaart tekent
        vergeet er niets door.
        """
        if kaart is not self.kaart or breedte != self.breedte or hoogte != self.hoogte:
            self.kaart = kaart
            self.breedte = breedte
            self.hoogte = hoogte
            self._vergeet()

    def update(self, kaart, breedte, hoogte, px, py, hoek, stand=UIT):
        """Werk `zichtbaar` bij en onthoud wat erbij hoort.

        px en py zijn wereldpixels, hoek is in radians. De stand komt uit de
        instelling: UIT onthoudt niets, VOLLEDIG toont alles zonder te
        onthouden, en GEZIEN doet het echte werk.
        """
        self._bind(kaart, breedte, hoogte)
        if stand == UIT:
            # Uitgezet wordt er niets onthouden. Wie de kaart later aanzet
            # begint dus vanaf waar hij dan staat, in plaats van met een
            # kaart van alles wat er inmiddels is verkend.
            self.zichtbaar = set()
            return self.zichtbaar
        if stand == VOLLEDIG:
            # De cheatstand. `gezien` laten we ongemoeid, zodat terugschakelen
            # naar GEZIEN meteen weer de echte, ontdekte kaart geeft.
            self.zichtbaar = {(x, y) for y in range(hoogte) for x in range(breedte)}
            return self.zichtbaar
        tx = int(px // TILE_SIZE)
        ty = int(py // TILE_SIZE)
        self.zichtbaar = self._verzpreiding(tx, ty, hoek)
        nieuw = self.zichtbaar - self.gezien
        if nieuw:
            self.gezien |= nieuw
            self.versie += 1
        return self.zichtbaar

    def is_zichtbaar(self, px, py):
        """Staat dit punt op een tegel die de speler nu ziet?"""
        return (int(px // TILE_SIZE), int(py // TILE_SIZE)) in self.zichtbaar

    def is_gezien(self, px, py):
        """Staat dit punt op een tegel die de speler ooit heeft gezien?"""
        return (int(px // TILE_SIZE), int(py // TILE_SIZE)) in self.gezien

    def _in_kegel(self, tx, ty, sx, sy, hoek):
        """Ligt deze tegel binnen de kijkhoek van de speler?"""
        dx = (tx + 0.5) - (sx + 0.5)
        dy = (ty + 0.5) - (sy + 0.5)
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            return True
        afstand = math.hypot(dx, dy)
        # Een tegel telt mee zodra ook maar een stukje ervan in de kegel
        # wijst, niet alleen wanneer het midden erin ligt. Anders valt de
        # tegel naast je tegen de klip weg terwijl je er nog op staat.
        half = FOV / 2 + math.atan2(0.5, afstand)
        verschil = math.atan2(dy, dx) - hoek
        verschil = abs((verschil + math.pi) % (2 * math.pi) - math.pi)
        return verschil <= half

    def _verzpreiding(self, sx, sy, hoek):
        """De tegels die de speler vanaf (sx, sy) ziet."""
        kaart, breedte, hoogte = self.kaart, self.breedte, self.hoogte
        if not (0 <= sx < breedte and 0 <= sy < hoogte):
            # Op een plek buiten de kaart. Kan net na een levelwissel, voor
            # de teleport is afgerond: dan is er niets te zien.
            return set()
        zichtbaar = {(sx, sy)}
        diepte = {(sx, sy): 0}
        rij = deque([(sx, sy)])
        while rij:
            x, y = rij.popleft()
            if diepte[(x, y)] >= self.zicht_tegels:
                continue
            if kaart[y][x] == 1:
                # De muur zelf is zichtbaar, wat erachter ligt niet.
                continue
            for dx, dy in _STAPPEN:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < breedte and 0 <= ny < hoogte):
                    continue
                if (nx, ny) in zichtbaar:
                    continue
                if not self._in_kegel(nx, ny, sx, sy, hoek):
                    continue
                zichtbaar.add((nx, ny))
                diepte[(nx, ny)] = diepte[(x, y)] + 1
                rij.append((nx, ny))
        return zichtbaar
