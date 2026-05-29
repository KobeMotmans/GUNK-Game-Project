"""
generate_skins.py - E nmalige generatie van 6 gekleurde player PNG varianten.
Draai: python generate_skins.py
"""
import os, sys

try:
    import pygame
except ImportError:
    # maybe python 3.10 has it
    sys.path.insert(0, os.path.dirname(sys.executable))
    import pygame

pygame.init()
os.environ["SDL_VIDEODRIVER"] = "dummy"
pygame.display.set_mode((1, 1))

SRC = "assets/player.png"
OUT_DIR = "assets/players"
os.makedirs(OUT_DIR, exist_ok=True)

COLORS = [
    (0,   "Blue",    (100, 150, 255)),
    (1,   "Red",     (255, 80,  80)),
    (2,   "Green",   (80,  200, 80)),
    (3,   "Yellow",  (255, 220, 80)),
    (4,   "Purple",  (200, 80,  255)),
    (5,   "Orange",  (255, 160, 50)),
]

original = pygame.image.load(SRC).convert_alpha()
w, h = original.get_size()

for idx, name, color in COLORS:
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    surf.blit(original, (0, 0))
    for x in range(w):
        for y in range(h):
            r, g, b, a = surf.get_at((x, y))
            gray = int(0.299 * r + 0.587 * g + 0.114 * b)
            nr = gray * color[0] // 255
            ng = gray * color[1] // 255
            nb = gray * color[2] // 255
            surf.set_at((x, y), (min(nr,255), min(ng,255), min(nb,255), a))
    out_path = os.path.join(OUT_DIR, f"player_{idx}.png")
    pygame.image.save(surf, out_path)
    print(f"  {out_path} ({name})")

print("Done! 6 skins gegenereerd.")
