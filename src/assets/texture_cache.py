"""
texture_cache.py - Centrale texture cache met pack-aware preloading
"""

import pygame

_cache = {}


def get(path, scale=None):
    """Load texture via cache. scale=(w,h) resizes and caches the scaled version."""
    key = (path, scale)
    if key not in _cache:
        img = pygame.image.load(path).convert_alpha()
        if scale:
            img = pygame.transform.scale(img, scale)
        _cache[key] = img
    return _cache[key]


def clear():
    _cache.clear()


def preload(paths, progress_callback=None):
    """
    Batch-preload textures.
    paths: list of str (no scale) or (str, (w,h)) tuples.
    progress_callback(ratio) called after each file.
    """
    total = len(paths)
    for i, entry in enumerate(paths):
        if isinstance(entry, str):
            get(entry)
        else:
            get(entry[0], entry[1])
        if progress_callback:
            progress_callback((i + 1) / total)
