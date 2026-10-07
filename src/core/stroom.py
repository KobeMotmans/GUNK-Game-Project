"""De vijandenstroom: hoeveel tegelijk, hoe vaak, en wat voor soort.

Er zijn twee plekken die deze regeling moeten draaien: `game.py` in solo en
`server_game.py` in multiplayer. Zou ze hier twee keer komen te staan, dan
heb je een tweede waarheid die pas opvalt als de twee uit elkaar lopen - en
dat merk je dan als de client een andere vijand verwacht dan de server, of
als er in MP meer in leven zijn dan in solo op hetzelfde moment.

Dus: pure functies, geen staat, geen pygame, en alle getallen komen uit
`GAMEMODES[mode]["stream"]`. Een mode zonder dat blok (de campaign) heeft
geen stroom; `grenzen()` zegt dan meteen dat er nooit iets bij mag, in plaats
van te doen alsof er een standaardstroom bestaat.

Geen waves met pauzes ertussen: een constante stroom die zwaarder wordt.
Zie SURVIVAL.md, "Vijandenstroom".

Coördinaten: spawn-punten en `enemy.pos` zijn allebei wereldcoördinaten
(`png_to_list_fast` rekent tegels om naar `map_to_cord(x) + TILE_SIZE/2`),
dus hieronder zijn alle afstanden in pixels.
"""

import random

# Een spawn-punt geldt als bezet als er al een vijand op minder dan dit
# staat. Eén tegel: genoeg om niet op dezelfde tegel te stapelen, klein
# genoeg dat de twintig punten in een krappe arm toch allemaal gebruikt
# kunnen worden.
STANDAARD_STRAAL = 64.0


def _voortgang(verstreken, duur):
    """Hoe ver we door de opbouw zijn, 0.0 tot 1.0.

    Afgekapt en geclamd, want een run die langer duurt dan de opbouw hoort
    op de eindwaarde te blijven steken en niet door te lopen. En een
    verkeerde tijd (negatief, None) mag de regeling niet door de war
    brengen.
    """
    try:
        f = float(verstreken) / float(duur)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
    return min(1.0, max(0.0, f))


def _duur(stream):
    try:
        return max(float(stream.get("ramp_seconds", 1)), 0.001)
    except (TypeError, ValueError):
        return 0.001


def grenzen(stream, verstreken):
    """(max_levend, interval_seconden) op t = verstreken.

    Beide lijnen lopen lineair van de begin- naar de eindwaarde over
    `ramp_seconds`:

    * `max_levend` loopt op mét een plafond. Zonder dat plafond stapelen de
      vijanden zich op tot de map vol is en loopt de boel vast.
    * `interval` wordt juist *langer*, dus er komt er minder vaak een bij
      naarmate de run duurt. Dat is de tegenhanger van het oplopende
      aantal: het plafond bepaalt de druk, de interval voorkomt dat er
      per seconde drie bij komen zodra de kaart al vol is.

    Zonder stroomblok: (0, oneindig). De campaign heeft er geen, en dan
    hoort er ook niets bij te komen.
    """
    if not stream:
        return 0, float("inf")
    f = _voortgang(verstreken, _duur(stream))
    try:
        lo = float(stream.get("start_alive", 0))
        hi = float(stream.get("max_alive", lo))
        i_lo = float(stream.get("start_interval", 1.0))
        i_hi = float(stream.get("end_interval", i_lo))
    except (TypeError, ValueError):
        return 0, float("inf")
    # Vloeren i.p.v. afronden: het maximum mag gehaald worden maar niet
    # overschreden, en een oplopende reeks mag nooit een stap terug doen.
    return int(lo + f * (hi - lo)), i_lo + f * (i_hi - i_lo)


def kies_type(stream, verstreken, kiezer=None):
    """Het type dat er nu bij mag komen, of None als er niets te kiezen is.

    De mix verschuift van `start_mix` naar `end_mix` over dezelfde
    `ramp_seconds` als de rest: eerst makkelijke types, later zwaardere en
    meer. Als een type nergens in voorkomt, krijgt het gewicht 0 en kan het
    nooit getrokken worden - dus een beginmix zonder tanks betekent
    echt geen tanks in de eerste minuten.

    None terug bij een lege of kapotte mix. Liever een overgeslagen spawn
    dan een crash midden in een run; een lege stroom is zichtbaar, een
    stacktrace is dat niet.
    """
    if not stream:
        return None
    begin = stream.get("start_mix") or {}
    eind = stream.get("end_mix") or begin
    namen = list(dict.fromkeys(list(begin) + list(eind)))
    if not namen:
        return None
    f = _voortgang(verstreken, _duur(stream))
    gewichten = [begin.get(n, 0) * (1 - f) + eind.get(n, 0) * f for n in namen]
    if sum(gewichten) <= 0:
        return None
    return (kiezer or random).choices(namen, weights=gewichten, k=1)[0]


def vrije_spawns(spawns, vijanden, straal=STANDAARD_STRAAL):
    """De spawn-punten waar nog geen vijand staat.

    `vrij` in de zin van: op meer dan `straal` afstand van élk bestaand
    vijand. Bezetheid is een afstand en geen index, omdat vijanden na het
    spawnen gaan lopen - een "bezet"-vlag zou dan blijven staan op een plek
    waar niemand meer is, of vrij blijven op een plek waar net iemand
    naartoe gelopen is.

    Een lege lijst terug betekent dat alle bronnen bezet zijn. Dan wachten
    we (keuze in SURVIVAL.md): er wordt pas gespawnd als er ergens een plek
    vrij is, dus nooit meer vijanden dan er spawns zijn.
    """
    bezet = [(v.pos.x, v.pos.y) for v in vijanden
             if getattr(v, "pos", None) is not None]
    kwadraat = float(straal) ** 2
    vrij = []
    for s in spawns:
        try:
            x, y = float(s[0]), float(s[1])
        except (TypeError, ValueError, IndexError):
            continue
        if all((x - bx) ** 2 + (y - by) ** 2 >= kwadraat for bx, by in bezet):
            vrij.append((x, y))
    return vrij


def volgende_spawn(stream, verstreken, spawns, vijanden, laatste_spawn, nu,
                   straal=STANDAARD_STRAAL, kiezer=None):
    """Een (x, y) als de stroom er nu één mag geven, anders None.

    Drie voorwaarden, in de volgorde waarin ze het goedkoopst zijn:

    1. het plafond is nog niet bereikt;
    2. de interval is verstreken sinds de vorige spawn;
    3. er is ergens een vrij spawn-punt.

    Bij 3 wachten we - punt 2 is dan al voldaan en de volgende vrije plek
    krijgt de vijand meteen, in plaats van dat de stroom blijft haperen en
    permanent achterloopt. Zonder dat zou een volle kaart de klok voor goed
    stilzetten zodra er één vijand weggaat.
    """
    if not stream:
        return None
    max_levend, interval = grenzen(stream, verstreken)
    if max_levend <= 0 or len(vijanden) >= max_levend:
        return None
    if laatste_spawn is not None and (nu - laatste_spawn) < interval:
        return None
    vrij = vrije_spawns(spawns, vijanden, straal)
    if not vrij:
        return None
    return (kiezer or random).choice(vrij)
