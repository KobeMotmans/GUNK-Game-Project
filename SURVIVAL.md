# Survival

Survival gamemode met een constante, geleidelijk oplopende stroom vijanden.
Dit is het ontwerpdossier: wat er moet komen,
wat er al is en welke keuzes nog openstaan, zodat een verse context (nieuwe
sessie, nieuwe hulp) in één keer op de hoogte is en niet alles opnieuw hoeft
uit te zoeken.

Bijgewerkt op 2026-10-08.

---

## Uitgangspunten

Deze gelden voor het hele project en survival in het bijzonder.

- **Alle gamemodes zijn gelijkwaardig.** Er is géén standaardgamemode en de
  code kiest nergens een mode als waarheid. Mode-specifieke waarden horen in
  `config.GAMEMODES` en worden gelezen via `gm()` / `config.gamemode()`.
  Een `if mode == "survival"` midden in de gameplay-code is een fout.
- **Drops zijn data-gedreven** (`config.DROPS`): wat een voorwerp oplevert
  staat op het voorwerp, niet in een aftakking in `objects.py`.
- **De campaign blijft ongewijzigd.** Survival mag bestaand campaingedrag
  niet veranderen; survival-eigenschappen komen er als extra kaas bovenop.
- **Tests bij grote refactors**, en af en toe een commit die expliciet
  meldt dat hij mogelijk unstable is.
- **Zichtbare uitleg**: wat niet in de code staat, hoort in een document
  zoals dit.

## Stand van zaken

Gedaan:

| commit | wat |
|---|---|
| `1fa6d7b` | `GAMEMODES`-tabel, `gm()`-lezer, data-gedreven `DROPS` |
| `b5402dc` | muurtextuurpijplijn (`WALL_TEXTURES`, `WALL_VALUES`, kolomstrips) |
| `28def8b` | spatiebalk als schietknop + één gedeeld vuurpad `_try_fire()` |
| `5796162` | `assets/textures/wall/beton.png` ligt er echt |
| `fbfd9e8` | survivalkaart + generator, health-kleur, `kaart_voor()`, en de mode in `game_start` |
| `79432bd` | terugval op de default bij een game_start zonder mode, plus de lift-test die eindelijk de bewaker bereikte |
| `097239c` | de vijandenstroom: `GAMEMODES["survival"]["stream"]`, `src/core/stroom.py`, cliént én server |
| `d5e93f5` | de run-afhandeling: `pb_bij`/`hud_score`, `_einde_run()`, en tijd én kills naast elkaar |
| `71937bb` | de run-timer die per ongeluk twee keer op het scherm stond |
| `1ae0d01` | geen MEEKIJKEN-knop als het leven gedeeld is |
| `dca5f8c` | het moduskeuzescherm bij SOLO en de modusknop in de lobby |

`config.GAMEMODES["survival"]` draagt nu ook `"map"` en `"start_angle"`,
naast `start_health`/`health_cap` 100, `start_ammo` 300 en `ammo_cap` 400.
`level_progression` en `uses_elevator` staan op `False`. Daarnaast dragen
`run_timer`, `save_pb`, `pb_bij` en `hud_score` de run-afhandeling en de
HUD — alle vier gelezen door de code, zie "De run is de klok". En er is
het `stream`-blok voor de vijandenstroom. Zie "Koppelen aan de mode" en
"Vijandenstroom" verderop.

Nog **niet** gedaan, en dat is de rest van dit document:

- karakter-/spec-keuze

Het **moduskeuzescherm is er wel** (afgerond 2026-10-08), zie "De
ingangen van een mode".

---

## De kaart

### Waar kaarten vandaan komen

Kaarten zijn **PNG's van één pixel per tegel**, niet tekstbestanden.
`config.MAP_PATH` wijst naar `assets/textures/floor/floor_5.png` t/m
`floor_0.png` (vijf levels; de naam "floor" is verwarrend — het zijn de
kartaart-PNG's, niet de vloertexturen). `map_loader.png_to_list_fast(path)`
zet zo'n PNG om in een 2D-lijst plus een `spawns`-dict.

Let op: **één pixel per tegel en `TILE_SIZE = 100`**, dus een 32×32 PNG is
een wereld van 3200×3200 px. De survivalkaart is 48×48 en is dus
4800×4800 px.

### Kleurentabel

`map_loader.color_to_number` is de enige plek die kleur naar tegelwaarde
vertaalt. `KeyError` bij een onbekende kleur — dus een generator die een
PNG maakt moet elke kleur precies treffen.

| teken | RGB | waarde | betekenis |
|---|---|---|---|
| `.` | 255,255,255 | 0 | leeg |
| `#` | 0,0,0 | 1 | muur |
| `E` | 0,255,0 | 2 | uitgang |
| `X` | 255,0,0 | 3 | vijand |
| `@` | 0,255,255 | 4 | spelerspawn |
| `K` | 0,0,255 | 5 | keycard |
| `A` | 255,255,0 | 6 | ammo |
| `B` | 255,0,255 | 7 | final boss |
| `H` | 255,128,0 | 8 | health |

De eerste acht bestaan; `H` is er inmiddels bij in `color_to_number` met een
`spawns["health"]`-tak in `png_to_list_fast`, en `create_objects()` pakt hem
op. `server_game.py` leest dezelfde functie, en omdat het allebei `M.SPAWNS`
is lopen de twee niet uiteen: er is één plaats die het doet.

Health op de kaart staat naast `HEALTH_CHANCE`, en dat bleek iets anders dan
het hier lang leek. Die kans is de kans dat een **dode vijand** een health-drop
nalaat (`game.py` en `server_game.py`, `_handle_enemy_death`), geen plaatsing
op de kaart. De `H`-tegel is dus de enige nieuwe plek waar health vandaan
komt: een kaart zonder `H` geeft een lege lijst en verandert verder niets.

### Het grondplan: 48×48, straten en zestien kamers

Indoor, zestien kamers van 7×7, straten van één tegel breed en een
ring-corridor van twee tegels breed die rondom loopt.

- **Buitenmuur** op de rand.
- **Ring-corridor** van twee tegels breed: x en y in 1-2 en 45-46. Loopt rondom.
- **Scheidingsmuur** (x=3, x=44, y=3, y=44) tussen ring en binnenblok.
- **Straten** van één tegel breed op x én y in 4, 14, 24 en 34. Ze lopen van
  scheidingsmuur tot scheidingsmuur en breken op alle zestien plekken door
  de scheidingsmuur heen, zodat er aan geen enkel uiteinde een doodlopend
  straatje overblijft.
- **Zestien kamers** van 7×7 tussen de straten: x én y in 6-12, 16-22, 26-32
  en 36-42. Geen enkele kamer raakt de ring; alle toegang loopt via de
  straten.

**Eis: elke kamer heeft minstens twee doorgangen.** Geen doodlopende cel,
anders zit een speler in survival vast in een hoek. Beide zijn inmiddels
validaties in de generator, niet alleen afspraken. West- en noorddeur
bestaan altijd, oost- en zuiddeur als er een straat achter zit: de negen
binnenkamers hebben er vier, de rand eromheen drie, en de rechtsonderkamer
heeft er twee.

De deuren staan niet alle vier op het midden van hun wand. Zouden ze dat
wel doen, dan vielen de deuren van vier kamers op één lijn en keek je van
straat tot straat door de hele kaart — precies de rechte zichtlijn die
kamers open trekt. Nu heeft elke deur zijn eigen hoek.

**Waarom 48 en niet 32** (keuze 2026-10-08): de gangen en kamers waren
ruim maar de wereld zelf klein. 32×32 is 1024 tegels, 48×48 is 2304. De
kamers gingen van tot ~10 breed naar 7 en de gangen van 2 naar 1, dus
dezelfde opmerking leverde twee keer zoveel vloer op.

Het skelet is opgebouwd en gevalideerd (rand overal muur, precies één `@`,
flood-fill bereikbaarheid, vijandspawn niet dichter dan 5 tegels bij de
speler, geen doodlopende cel). De huidige ASCII:

```
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
```

24 `X`, 12 `A`, 7 `H`, één `@` op (24,24). Geen `E`, `K` of `B`: survival
heeft geen lift, dus geen uitgang en geen keycard.

Verdeling die nu klopt:

- `X` (24): acht kamercentra, acht in de ring (hoeken en midden van de
  randen) en acht op de kruispunten van de straten — allemaal ruim weg van
  de speler, zodat de eerste vijanden niet meteen op je staan.
- `A` (12): één per kamer plus de vier kruispunten op de middenas. Ammo is
  een beloning voor het verkennen van de kamers.
- `H` (7): vier op de ringrand boven en onder (leuk: je moet ervoor de rand
  op) en drie op de kruispunten bij het midden.

### De generator

Thuis: `tools/gen_survival_map.py` met de ASCII als bron, validatie, en
PNG-output naar `assets/textures/floor/survival.png`.

**Let op de `.gitignore`:** daarin staat `/tools/`, bedoeld voor binaire
rommel zoals `upx.exe`. Als de generator daar ongewijzigd in belandt, is de
kaartbron onzichtbaar — precies de fout die erboven bij `game.spec` bij
staat beschreven. Oplossing: `/tools/*` in plaats van `/tools/`, plus
`!/tools/gen_survival_map.py`.

### Koppelen aan de mode

Gedaan. Er is één laadplek over: `config.kaart_voor(mode, level)` geeft
`(pad, hoek)`, en alles wat een kaart nodig heeft vraagt daaraan in plaats van
zelf `MAP_PATH[level]` te nemen. `GAMEMODES["survival"]` draagt `"map"` en
`"start_angle"`; survival negeert het levelnummer (er is er maar één) en een
onbekende modenaam valt terug op de campaign, net als `gamemode()` al deed.

Dat hoorde bij drie dingen die eromheen moesten:

- `create_enemies()` respecteert `spawn_enemies_at_start` — survival zet dus
  geen vijanden neer bij het begin; de stroom brengt ze.
- geen exit-object als `uses_elevator` False is. Zonder groene tegel blijft
  `spawns["end_point"]` op (0,0), dus anders staat er een lift die niets doet.
  Zowel `create_objects()` (client) als `server_game._setup_level()` (server)
  doen het, met `exit_pos = None` erbij — wat de elevator-tick en `get_state`
  al afvinkten.
- health uit `spawns["health"]`, in dezelfde `{"pos", "amount"}`-vorm als een
  drop, zodat de client het niet anders hoeft te behandelen. Ook hier weer op
  beide plekken.

Waar het mis kan gaan: de mode moet **vóór** het laden bekend zijn. In
multiplayer draait de server zijn eigen `gamemode`, en de client krijgt hem in
het `game_start`-pakket (`protocol.KEY_TO_ID["gamemode"] = 63`). Zou die
sleutel ontbreken, dan schrijft de encoder er `255` voor in — en dat is de
`TERMINATOR`: de decoder stopt midden in het pakket en `gamemode` komt stil
niet aan, terwijl de waarde er wél nog in staat. Valt de client terug op de
default, dan tekent hij een campaignkaart terwijl de server survival draait.

Daarom draagt `survival_generator_en_koppeling` een round-trip op precies die
sleutel, en `survival_werkt_in_multiplayer` de hele keten server → pakket →
cliënt. Verder draagt `lobby_options` `"gamemode"` zodat een net
binnengekomen client in de lobby al de juiste modus ziet, en past de client
hem op één plek toe — `_neem_lobby_options()`, zowel in `apply_state` als in
de `lobby_info`-handler, zodat de twee niet uiteenlopen.

Zegt het `game_start`-pakket niets — dan komt dat van een oudere server, want
`_game_start_packet` zet hem er altijd in — dan valt de client terug op de
default in plaats van de mode te bewaren die hier toevallig actief was. Die
kan survival zijn na een eerdere pot, en dan lagen de twee spelers op een
verschillende kaart zonder dat iemand het zag. Beide plekken doen het
zelfde; de test legt dat vast, want het verschil is alleen te zien als je
weet welke van de twee het laatst kwam. Zie "Openstaande keuzes" 4 voor de
volledige matrix.

De dev-console `gamemode survival` roept nu `reset_game(gamemode=...)` aan:
alleen de stats omdraaien zou half werk zijn, want de mode bepaalt ook welke
kaart er ligt en of er een uitgang is.

---

## Twee verdiepingen en de trap

Vraag: kan er een effectieve trap komen naar een tweede verdieping, die de
vijanden ook kunnen nemen?

### Wat de renderer nu is

De raycaster kijkt **één laag**. Er is één globaal grid: `M.MAP` in
`map_loader.py` (module-level `M`), en `hit_wall`, `will_collide`,
`wall_face`, `is_in_wall`, de minimap en de A* vragen daar allemaal aan.
Er is geen hoogte, geen plafondhoogte en de camera staat vast op ooghoogte.
Het plafond en de vloer zijn bewust egaal: getextureerd kostte ruim 5 ms per
frame en dat is te veel.

### Optie A — wisselen bij de trap (aanbevolen als startpunt)

Twee grids, waarvan er één actief in `M.MAP` staat. De traptixel op
verdieping 0 wisselt naar verdieping 1 en terug, met een korte vertraging
zodat je niet heen en weer flitst.

- **Renderen verandert niet.** Je ziet altijd de verdieping waarop je staat.
  Omdat het plafond egaal is en de camerahoogte vast, is er geen tweede
  niveau dat boven je opdoemt: de wissel is een harde overgang, eventueel
  met een fade. Als je dat wilt, is Optie B nodig.
- **Dit bestaat al als patroon.** Een level-wissel doet precies dit:
  `png_to_list_fast(...)` vervangt `M.MAP`, `M.SPAWNS`, `M.width/height` en
  zet `player.pos`. Er zijn meerdere plekken die dat doen (zie `MAP_PATH`).
- **Het echte werk zit niet in renderen maar in filteren.** Zodra speler en
  vijanden op verschillende verdiepingen kunnen zijn, moet élke vraag
  "raakt/ziet/jaagt die diegene?" filteren op verdieping: collision, damage,
  raycast-sprites, projectielen, drops, minimap, HUD, netwerk-state. Dat zijn
  veel kleine regels door de hele codebase — het soort verspreide kennis dat
  we bij de gamemodes juist hebben weggehaald. Eén nieuw begrip ("welke
  verdieping") duikt overal op, dus het hoort als centraal gegeven, niet als
  losse if.
- **Vijanden nemen de trap**: ieder entity krijgt `floor`, de padvinding
  gebruikt het grid van de eigen verdieping (nu globaal!), en bij de
  traptile wisselt de vijand mee. Let op dat de padvinding per-vijand het
  juiste grid moet nemen zolang `M.MAP` één ding is.

**Multiplayer is de harde kant.** De server heeft ook één `M.MAP`. Twee
richtingen:

1. **De hele groep wisselt samen** — het lift-patroon dat al bestaat
   (`elevator_waiting`, iedereen moet er zijn). Goedkoop, maar de trap is dan
   niet "van jou".
2. **Iedereen wisselt los** — dan moet de server per speler de juiste wereld
   nemen voor collision en damage. Dat is een echte ingreep.

### Optie B — twee lagen tegelijk zichtbaar

Dan moet de raycaster meer dan één hoogte tekenen: zuil-render met een
meerdere-hogtes-lag of een tweede pass met een z-buffer per kolom. Dat raakt
`dda()`, `draw_wall()` en de net gebouwde textuurpijplijn (kolomstrips,
lichtbanden, het bijsnijden bij hoge muren). Duur, risicovol, en niet nodig
als je alleen bij de trap wisselt.

### Stand — besloten op 2026-10-07

**Eerst zonder trap bouwen, daarna kiezen.** Survival komt op één
verdieping.

Wat daarbij hoort: **zet `floor` meteen op de speler en de vijanden** (nu
allemaal 0), zodat de trap later een kwestie wordt van "het tweede grid
laden" in plaats van een structuurrefactoring door alle entities heen.

De keuze tussen Optie A (gezamenlijk), Optie A (los) en Optie B komt pas
als de rest werkt. Wat al vastligt: Optie A met gezamenlijke wissel is het
goedkoopst en bouwt op het bestaande lift-patroon.

### Opmerkingen speler — 2026-10-07

Vier punten die na de analyse boven zijn binnengekomen:

1. **Twee verschillende indelingen.** Geen verdiepingen die elkaars plan
   herhalen: het moeten echt twee verschillende plattegronden zijn, anders
   is het "hetzelfde plan twee keer". Dat schrapt de besparing uit de
   analyse ("ontwerp de muren uitgelijnd, dan zijn beide grids identiek")
   als aanbeveling — die bleek de goedkoopste route, maar het mag de
   geloofwaardigheid niet kosten. De gevolgen die daaruit volgden —
   collision per laag, `M.MAP` dat niet meer één waarheid is, de raycaster
   die moet kiezen welke laag hij tekent — komen dus wél terug in beeld.
2. **Het gevoel van echt oplopen.** De illusie moet aanvoelen zoals in 3D,
   maar **zonder** dat de speler vrij omhoog en omlaag kan lopen: geen
   pitch-besturing, geen vrij kijkvlak. Dus: stijgen mag alleen op de trap,
   en de camera volgt dat gedwongen.
3. **45° omhoog bij de trap.** Idee: zodra je de trap op wilt, gaat de
   camera 45 graden omhoog, puur voor dat trap-gedeelte. Zo zou je de
   helling "tegenkomen" zonder dat de raycaster een vrij pitch-vlak hoeft
   te ondersteunen.
4. **Nog te beantwoorden:** wat die 45° in deze renderer precies kost en
   oplevert. De analyse daarvan was onderbroken en hoort hieronder
   bijgeschreven te worden voordat er iets gebouwd wordt: of het bij
   Optie A past, wat het met de vloerloze achtergrond doet (er is geen
   zichtbare vloerlijn die kan "omhoogschuiven"), en of het
   trap-gedeelte en het gewone kijkvlak met elkaar te rijmen zijn zonder
   een zichtbare knik.

---

## Vijand-AI

### Wat er nu is

Twee implementaties met dezelfde structuur:

- `src/entities/enemy_ai.py` — `EnemyAI` met `is_in_los()`, `move_towards()`,
  `has_target()` en `A_star()` (A* op `WALL_VALUES`, vier richtingen).
- `src/entities/enemies.py:71` — `find_path(player, game, ...)`, de
  client-variant: neemt **één** `player` aan.
- `src/network/server_game.py:290` — `get_nearest_player_pos(enemy)`,
  geroepen op `server_game.py:448` voor elke vijand per frame. Dat is in MP
  de leidende AI.

De prooi wordt gekozen als de **niet-dode speler met de kleinste `.norm()`**,
en `.norm()` is euclidisch: **vogelvlucht, muren worden genegeerd**. Dat is
dus al precies de "redelijk cheesy"-keuze die we willen.

De aggro-logica (beide plekken, `AGGRO_DIST = 1000`, `ATTACK_DIST = 43`,
`PATHFIND_INTERVAL = 20`, allemaal in `config.py`):

1. `is_in_los(prooi)` → zichtbaarheid en afstand.
2. `dist > AGGRO_DIST` → `spotted_player = False`.
3. met zicht → `spotted_player = True`, pad wissen, recht op af.
4. `spotted_player en dist < AGGRO_DIST en géén zicht` → pad opnieuw plannen
   (A*), elke `PATHFIND_INTERVAL` frames.
5. `dist <= ATTACK_DIST` met zicht → schade.

### Wat survival wil

- **Standaard aggro.** Geen `spotted_player`-poort: een vijand jaagt meteen
  op de dichtstbijzijnde persoon, ook als hij hem nooit gezien heeft. In
  survival wil je druk, niet stealth.
- **Dichtstbijzijnde persoon in vogelvlucht** als prooi-keuze. Dat bestaat
  al op de server; de client-variant (`find_path` neemt één `player`) moet
  hetzelfde leren.
- Niet-dode spelers, en in het oog houden dat een dode of spectater geen
  doel is.

Dit hoort **config-gedreven**, geen modenaamcheck: een waarde in
`GAMEMODES` (bijvoorbeeld `always_aggro` of een `aggro_mode`) die de
`spotted_player`-poort openzet, zodat de campaign er geen last van heeft en
een derde mode hetzelfde kan kiezen.

Praktisch: de poort zit op twee plekken (client en server). Als ze allebei
uit `config` lezen, blijven ze in sync.

### Vijanden en de trap

Als Optie A doorgaat: vijanden krijgen `floor`, kiezen hun pad op hun eigen
grid, en wisselen mee zodra ze de traptile raken. De prooi-keuze moet dan
ook filteren op verdieping — een speler op de verdieping erboven is in
vogelvlucht dichtbij maar niet bereikbaar.

---

## Vijandenstroom

**Geen afgebakende waves met pauzes ertussen, maar een incrementele,
constante stroom** die naarmate de run vordert steeds zwaarder wordt. Er is
dus geen "wave X begint", geen aftelling en geen moment waarop de map leeg
is — er komt simpelweg meer.

De druk is een functie van de tijd, en die staat nu in één blok:
`GAMEMODES["survival"]["stream"]`. Alle getallen daar, geen enkele
modenaamcheck in de gameplay-code.

| | begin | einde | over |
|---|---|---|---|
| gelijktijdig in leven | 4 | **16** (plafond) | 300 s |
| interval tussen spawns | 2,0 s | 8,0 s | 300 s |
| mix | 3 normal, 1 fast, 0 tank | 2 normal, 2 fast, 2 tank | 300 s |

- **Hoeveel** er tegelijk in leven zijn, loopt op mét een plafond. Het
  plafond staat op 16 terwijl er 24 spawns zijn: 8 plekken blijven vrij,
  zodat de stroom altijd ergens heen kan en er niets vastloopt.
- **Hoe vaak** er een nieuwe bijkomt, neemt af — de interval wordt juist
  *langer*. Het plafond bepaalt de druk, de interval voorkomt dat er per
  seconde drie bij komen zodra de kaart al vol is.
- **De mix** verschuift over dezelfde 300 seconden. Tanks staan op gewicht
  0 bij de start en komen er dus echt niet in de eerste minuten bij.

De regeling zelf staat één keer in `src/core/stroom.py`, en dat is
bewust: er zijn twee plekken die hem moeten draaien, `game.py` in solo en
`server_game.py` in multiplayer. Zou hij hier twee keer komen te staan,
dan heb je een tweede waarheid die pas opvalt als de twee uit elkaar
lopen — en dat merk je dan als de client een andere vijand verwacht dan
de server aanstuurt.

### Wat de kaart al levert

- **Spawn-punten zijn de rode `X`-tegels.** Die komen in
  `spawns["enemies"]` terecht en dienen als bronlijst voor de stroom. De 24
  in het grondplan liggen verspreid over ring, straten en de zestien kamers, zodat
  vijanden niet allemaal uit dezelfde hoek komen en er altijd een bezet kan
  zijn zonder dat de volgende blijft hangen. Ze staan in
  wereldcoördinaten (`map_to_cord(x) + TILE_SIZE/2`), net als `enemy.pos`,
  dus de afstandsberekening in `stroom.py` klopt direct.
- Daarbij hoort `spawn_enemies_at_start = False`: er staat er geen meteen
  bij de start; de stroom brengt ze.

### Besloten op 2026-10-07

- **Escalatiecurve en plafond:** tijd-gedreven, plafond 16, zoals de tabel
  hierboven. Bewust niet score-gedreven: dan zou de stroom in multiplayer
  voor iedereen iets anders betekenen, afhankelijk van wie er toevallig
  goed speelt.
- **Wat de speler wint:** beide naast elkaar. De klok ís de run en de tijd
  wordt bewaard; de kills staan ernaast als ranglijst. (Survival stopt niet
  vanzelf: `level_progression` is False, dus geen uitgang.)
- **Bezette spawns:** wachten. Er wordt pas gespawnd als er ergens een plek
  vrij is, dus nooit meer dan 20 in leven. De interval telt wél door, dus
  zodra er één vrij komt krijgt die meteen een vijand — anders zou een volle
  kaart de klok voorgoed stilzetten.

### De run is de klok

`run_timer`, `save_pb`, `pb_bij` en `hud_score` zijn de vier sleutels die
bepalen wat een run oplevert en wat je ervan ziet. Ze zijn bewust config
en geen `if gamemode == "survival"`: de campaign en de survival verschillen
hier alleen in hun waarden, niet in welke code er draait.

Eén plek handelt een beëindigde run af — `Game._einde_run(reden)` in
`game.py`, met `reden` = `"escape"` of `"death"`. Dat er daar één plek voor
is, maakt uit: er komen **drie** meldingen op die plek af, niet één.
Ontsnappen is er één, en overlijden wordt vanuit twee richtingen gemeld —
`handle_network()` voor de gezondheid die van de server komt, en de
hoofdlus voor `player.death`. Zouden die drie hun eigen kopie van
"klok stil + PB bewaren" hebben, dan was het een kwestie van hopen welke
van de drie het als eerste deed. Daarom is `_einde_run` idempotent: de
eerste melding wint.

De tweede reden voor één plek is het verschil tussen de modes. In de
campaign telt alleen een **uitgespeelde** run; een run die op de vloer
eindigt was geen volle run en levert dus geen PB op. In survival is er
geen uitgang om uit te komen, dus telt elke run — en die eindigt bij het
overlijden. Zou dat onderschap alleen bij de ontsnapping zitten, dan werd
in survival **nooit** iets opgeslagen en zou `save_pb: True` een leugen
zijn. Vandaar `pb_bij`: `"escape"` voor de campaign, `"death"` voor
survival.

Zie je tijdens het spelen:

- de **klok** rechtsboven (allebei de modes; `run_timer` zet hem uit), en
- eronder het aantal **kills** als `hud_score` aan staat — in survival
  `True`, in de campaign `False` zodat die HUD ongewijzigd blijft.

Beide komen ook samen op het **dodescherm**: `Score:N  00:00:00` naast
elkaar, op één regel zodat er niets bij de MENU-knop terechtkomt. Dat is
de keuze uit punt 3 van "Openstaande keuzes" — de klok ís de run, de kills
staan ernaast als ranglijst — en die regel geldt ook als je het verloren
hebt. Verschijnt er `NEW PB!` bij, dan is er daadwerkelijk een bewaard;
dat kan alleen bij een mode die dat wil, dus een campaigndood ziet dat
nooit. Op het **ontsnapscherm** veranderde er niets.

De tijdopmaak staat in `_formateer_tijd()` in `src/ui/Menu.py`. Die stond
voorheen vier keer ingebouwd (HUD, meekijken, ontsnappen, dodescherm) en
zou nu vijf keer kunnen staan — de test telt de ingebouwde varianten en
valt af als er naast de functie nog één bijkomt, want het verschil zou pas
opvallen als er twee verschillende tijden naast elkaar stonden.

**Test:** `run_timer_en_pb_volgen_de_mode` in `tests/mp_test.py` (64/64).
Hij draait in een eigen subprocess en buigt `_runs_path()` naar de
temp-map om — anders schrijft de test over `runs.json` naast `game.py` en
is het record van de speler weg. Wat hij bewijst: de vier sleutels bestaan
en verschillen per mode, `run_timer` zet de klok echt uit, een
survivaldood levert wél een PB op en een campaigndood niet (ook geen
bestand), een tweede melding verandert niets, en de tijdopmaak staat op
precies één plek.

---

## Karakter- en spec-keuze

Nog niet gebouwd. Moet in zowel solo als multiplayer, en hoort bij de start
van een run te gebeuren voordat de vijandenstroom begint. Er is al een
keuzestrucuur rond de lobby (`ready`, server settings) waar dit aan vast
kan hangen.

Ook nog niet gedaan: een **keuzemenu voor de gamemode** zelf. Nu kan alleen
de dev-console (`gamemode survival`) of `reset_game(gamemode=...)` de mode
zetten.

---

## De ingangen van een mode

Afgerond op 2026-10-08. Er zijn er twee, en geen van beide noemt de
modenaam in de code die hem aanroept — alles komt uit `GAMEMODES`.

**Solo.** De SOLO-knop begon met `reset_game("campaign")` ingebakken; die
roept nu `state = "mode_select"` aan. `Menu.draw_mode_select` tekent
vervolgens per mode één regel: de knop met de modenaam en daarnaast de
`omschrijving` uit de mode-config. Die omschrijving is verplicht in de
praktijk — een mode zonder uitleg is een knop die je niet durft te drukken,
en de test (`moduskeuze_start_de_juiste_mode`) laat dat vallen. BACK en
Escape gaan terug naar het hoofdmenu.

**Multiplayer.** De host kiest in de lobby, waar al `shared_health` en
`shared_ammo` stonden. De lijst heet nu `LOBBY_OPTIES` en elke regel draagt
een domein:

```python
LOBBY_OPTIES = (
    ("gamemode", "MODE", tuple(GAMEMODES)),
    ("shared_health", "Shared Health", None),
    ("shared_ammo", "Shared Ammo", None),
)
```

Zonder domein klapt de knop om (de twee schakelaars); met domein loopt hij
door de waarden heen. Dat `domein` staat er bewust in plaats van "als dit
een modenaam is": dan zouden we raden, en een gok zou de knop op een
onbekende naam kunnen zetten. Nu komt het uit dezelfde tabel als de rest
van het spel, en `_lobby_waarde()` is de enige plek die de terugval kent —
tekenen en klikken moeten het over dezelfde stand hebben.

De server wist dit al te accepteren (`set_lobby_option` in `network.py`
toetst `key == "gamemode" and value in GAMEMODES`), maar die tak was nog
nooit gestuurd: alleen de twee schakelaars. `lobby_zet_de_modus_van_de_server`
is de eerste die hem raakt — met een naam die niet bestaat, met een gast
die het niet mag, en met de mode die de servergame erop draait.

De dev-console werkt nog steeds; die is nu de derde ingang in plaats van de
enige.

---

## Openstaande keuzes

1. **Trapmodel:** besloten om het *na* de rest te kiezen — zie "Stand —
   besloten op 2026-10-07". Alleen het `floor`-veld moet er meteen in.
2. **Health-kleur — beslist, oranje (255,128,0), id 8.** Die waarden
   stonden nergens anders in `color_to_number`, dus het bleef oranje. Dit
   punt blijft hier staan omdat `map_loader` ernaar verwijst; als de campaign
   die kleur ooit gaat gebruiken, kies dan hier eerst iets anders.
3. **Escalatie van de vijandenstroom — beslist op 2026-10-07.** Tijd-gedreven
   met plafond 16, de klok is de run en de kills staan ernaast, en bij volle
   spawns wachten we. Zie "Vijandenstroom" voor de getallen. Afgerond op
   2026-10-08: de code leest `run_timer`/`save_pb` nu, de run-afhandeling
   zit in `_einde_run`, en tijd én kills staan naast elkaar op de HUD en
   op het dodescherm. Zie "De run is de klok". Wat er van deze keuze nog
   rest, is de karakter-/spec-keuze; het keuzemenu voor de mode zelf is
   er (zie "De ingangen van een mode").
4. **Gemengde versies — beslist op 2026-10-08: accepteren.** De gebruiker
   speelt nooit met oudere versies ("ik update altijd"), dus dit punt is
   hiermee afgehandeld en hoeft niet meer open te staan. De analyse eronder
   blijft staan als iemand het toch tegenkomt.

   Er is geen protocolversie;
   `discovery.VERSION` dekt alleen de LAN-broadcast-indeling en die is niet
   veranderd. `decode_packet` doet `ID_TO_KEY.get(kid, f"key_{kid}")`, dus
   een oudere client leest de nieuwe sleutel `gamemode` om tot `key_63` en
   negeert hem — decoderen stopt niet, alleen bij 255. Drie van de zes
   combinaties werken:

   | client \ server | oudere server | nieuwe, campaign | nieuwe, survival |
   |---|---|---|---|
   | oudere (1.0.12) | werkt | werkt (negeert `key_63`) | **kaart mismatch** |
   | nieuwe | werkt | werkt | werkt |

   De nieuwe client valt zonder `gamemode` terug op de default
   (`_start_multiplayer_client` en `_neem_lobby_options` doen hetzelfde),
   en dat is precies wat een oudere server draait.

   Alleen de rechterbovenhoek is kapot: een oudere client die bij een
   nieuwe survivalserver komt, tekent de campaignkaart. Niet te verhelpen
   vanaf deze kant — die client is al uitgeleverd en leest de sleutel
   simpelweg niet. **Gekozen: accepteren.** `discovery.VERSION` opschroeven
   zou de drie werkende cellen ook breken, en een capaciteitsafspraaak is
   protocolwerk dat niemand nodig heeft zolang er geen gemengde versies
   bestaan.

## Ver in de toekomst

- **Keybind mapping.** De gebruiker wil ooit een instellingenpagina waar
  toetsen toegewezen kunnen worden (nu zitten ZQSD/muisknop/spatie vast in
  de code, zie `handle_input()` en `handle_events()`). Nu niet aan beginnen,
  maar het hoort hier wel bij: zo'n scherm raakt dezelfde invoercode als de
  spatiebalk die er net bij kwam, dus houd `handle_input()` / `_try_fire()`
  leesbaar.
