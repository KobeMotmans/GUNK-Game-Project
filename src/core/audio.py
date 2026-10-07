"""
audio.py - De mixer opstarten, ook als de machine geen geluid heeft

pygame.init() initialiseert de mixer mee met alle andere subsystemen, maar
vangt de fout af: als er geen bruikbaar audio-apparaat is gaat het spel
gewoon door met een niet-geinitialiseerde mixer. Er komt geen melding, en
de eerste aanroep die het merkt is pygame.mixer.Sound() in de wapens - die
bij het opstarten gemaakt wordt. Vandaar een traceback meteen bij het
opstarten, en alleen op machines zonder geluidsuitgang.

Deze module opent de mixer op precies Ã©Ã©n plek, vÃ³Ã³r er een wapen gemaakt
wordt, en probeert een keten van instellingen zolang de vorige niet werkt:

  1. wat er al is – als pygame.init() het al gered heeft is dit klaar;
  2. opnieuw met de standaardparameters;
  3. met bredere parameters (22050/1024) – apparaten die 44100 Hz met een
     buffer van 512 weigeren zijn precies het verschil tussen "werkt bij de
     een" en "werkt bij de ander";
  4. met de dummy-driver van SDL: er is dan wÃ©l een mixer, dus elk Sound-
     object, elk kanaal en mixer.stop() blijven werken, alleen klinkt er
     niets. Dit is de stand die een machine zonder geluidsuitgang redt;
  5. helemaal niets – dan levert load() een stille lookalike, zodat het
     spel verder kan in plaats van te crashen.

status houdt bij in welke stand we terechtgekomen zijn, detail waarom. Beide
staan in gunk.log, zodat "geen geluid" niet een onverklaarbare ervaring is.
"""

import os

import pygame

from .logger import log as _log

# "apparaat"  – de eigen audio-uitgang doet het
# "dummy"     – er is een mixer, maar er klinkt niets
# "geen"      – zelfs een stille mixer lukte niet
status = None
detail = ""

# De dummy-driver is een terugval, geen keuze: alleen gebruiken als de
# normale weg gefaald heeft, anders speelt een machine met geluid niets af.
_DUMMY = "dummy"


class SilentSound:
    """Wat pygame.mixer.Sound terug zou geven als die niet bestond.

    Alle methodes die de rest van het spel op een Sound aanroept zitten erop,
    zodat wapens, pickups en muziek niets hoeven te weten van de stand waarin
    de audio zit. play() returnt None: game.py bewaart dat kanaal en vraagt er
    get_busy() aan, wat ook nergens op slaat als er niets speelt.
    """

    def play(self, *args, **kwargs):
        return None

    def stop(self):
        pass

    def pause(self):
        pass

    def unpause(self):
        pass

    def fadeout(self, *args, **kwargs):
        pass

    def set_volume(self, value):
        pass

    def get_volume(self):
        return 0.0

    def get_length(self):
        return 0.0

    def get_busy(self):
        return False


def _note(msg):
    global detail
    detail = f"{detail}; {msg}" if detail else msg


def init():
    """Start de mixer en houdt bij wat er gebeurde. Idempotent."""
    global status, detail

    if pygame.mixer.get_init():
        status = "apparaat"
        detail = f"{pygame.mixer.get_init()[0]} Hz, standaardapparaat"
        return status

    first_error = ""
    for step, kwargs in (
        ("standaard", {}),
        ("22050 Hz, buffer 1024", {"frequency": 22050, "size": -16,
                                   "channels": 2, "buffer": 1024}),
    ):
        try:
            pygame.mixer.init(**kwargs)
            status = "apparaat"
            detail = f"{step}apparaat"
            _log(f"Audio: mixer open via {step}")
            return status
        except pygame.error as e:
            if not first_error:
                first_error = str(e)

    # Geen bruikbaar apparaat. SDL leest de driver opnieuw bij het volgende
    # init()-poging, dus deze ene regel is genoeg om verder te komen.
    os.environ["SDL_AUDIODRIVER"] = _DUMMY
    try:
        pygame.mixer.init()
        status = "dummy"
        detail = f"geen audio-uitgang ({first_error}); stille mixer"
        _log(f"Audio: geen audio-uitgang, verder met de dummy-driver – "
             f"eerste fout: {first_error}")
        return status
    except pygame.error as e:
        status = "geen"
        detail = f"geen mixer ({first_error}; dummy: {e})"
        _log(f"Audio: geen mixer mogelijk – {detail}")
        return status


def load(path):
    """Laad een geluid, of geef een stille terug als dat niet kan."""
    if status is None:
        init()

    if status == "geen":
        return SilentSound()

    try:
        return pygame.mixer.Sound(path)
    except (pygame.error, OSError) as e:
        # Ook als één geluid het probleem is hoort het spel door te gaan:
        # een geluid mist, een spel dat niet opstart mist alles. De stand
        # blijft zoals die was - de mixer doet het immers nog steeds, alleen
        # dit ene bestand lukt niet.
        _note(f"kon {os.path.basename(path)} niet laden: {e}")
        _log(f"Audio: {detail}")
        return SilentSound()


def stop_all():
    """Sluit alle kanalen af, zonder te klagen als er geen mixer is."""
    if pygame.mixer.get_init():
        pygame.mixer.stop()


def pause():
    if pygame.mixer.get_init():
        pygame.mixer.pause()


def unpause():
    if pygame.mixer.get_init():
        pygame.mixer.unpause()
