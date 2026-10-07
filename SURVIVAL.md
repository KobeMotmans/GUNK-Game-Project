# Survival

Survival gamemode met een constante, geleidelijk oplopende stroom vijanden.
Dit is het ontwerpdossier: wat er moet komen,
wat er al is en welke keuzes nog openstaan, zodat een verse context (nieuwe
sessie, nieuwe hulp) in één keer op de hoogte is en niet alles opnieuw hoeft
uit te zoeken.

Bijgewerkt op 2026-10-07.

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

`config.GAMEMODES["survival"]` draagt nu ook `"map"` en `"start_angle"`,
naast `start_health`/`health_cap` 100, `start_ammo` 300, `ammo_cap` 400, en
`level_progression`, `uses_elevator`, `run_timer` en `save_pb` allemaal
`False`. Zie "Koppelen aan de mode" verderop voor hoe de kaart eruit komt.

Nog **niet** gedaan, en dat is de rest van dit document:

- de vijandenstroom (incrementeel, zie hieronder)
- karakter-/spec-keuze
- een keuzemenu voor de gamemode (nu alleen via de dev-console:
  `gamemode survival`, of `reset_game(gamemode=...)`; in multiplayer mag
  alleen de server hem zetten, via `lobby_options`)

---

## De kaart

### Waar kaarten vandaan komen

Kaarten zijn **PNG's van één pixel per tegel**, niet tekstbestanden.
`config.MAP_PATH` wijst naar `assets/textures/floor/floor_5.png` t/m
`floor_0.png` (vijf levels; de naam "floor" is verwarrend — het zijn de
kartaart-PNG's, niet de vloertexturen). `map_loader.png_to_list_fast(path)`
zet zo'n PNG om in een 2D-lijst plus een `spawns`-dict.

Let op: **één pixel per tegel en `TILE_SIZE = 100`**, dus een 32×32 PNG is
een wereld van 3200×3200 px.

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

### Het grondplan: 32×32, ring en kruis

Indoor, zes kamers, twee gangen die elkaar in het midden kruisen.

- **Buitenmuur** op de rand.
- **Ring-corridor** van twee tegels breed: x en y in 1-2 en 29-30. Loopt rondom.
- **Scheidingsmuur** (x=3, x=28, y=3, y=28) tussen ring en binnenblok.
- **Kruisgang**: verticaal x=15,16 en horizontaal y=15,16, doorlopend van de
  ring tot de ring. Hij breekt op vier plekken door de scheidingsmuur, zodat
  het kruis de ring raakt.
- **Kamermuren** lopen door (x=14, x=17, y=14, y=17), zodat de gangen nergens
  in een kamer lekken.
- **Twee extra kamers** door NW te splitsen op x=8 en SE op y=22: zes kamers
  in totaal.

**Eis: elke kamer heeft minstens twee doorgangen.** Geen doodlopende cellen,
anders zit een speler in survival vast in een hoek. Eén deur naar de
kruisgang, één naar de ring of naar een buurkamer.

Het skelet is opgebouwd en gevalideerd (rand overal muur, precies één `@`,
flood-fill bereikbaarheid, vijandspawn niet dichter dan 5 tegels bij de
speler). De huidige ASCII:

```
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
```

20 `X`, 8 `A`, 6 `H`, één `@` op (16,16). Geen `E`, `K` of `B`: survival
heeft geen lift, dus geen uitgang en geen keycard.

Verdeling die nu klopt:

- `X` in de ring (hoeken en zijden) en in de armen van de kruisgang — ruim
  weg van de speler, zodat de eerste vijanden niet meteen op je staan.
- `A` één per kamer plus twee in de ring: ammo is een beloning voor het
  verkennen van de kamers.
- `H` vier in de ringhoeken (leuk: je moet ervoor de rand op) en twee in de
  gangen.

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
de `lobby_info`-handler, zodat de twee niet uiteenlopen. De dev-console
`gamemode survival` roept nu `reset_game(gamemode=...)` aan: alleen de stats
omdraaien zou half werk zijn, want de mode bepaalt ook welke kaart er ligt en
of er een uitgang is.

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

## Vijandenstroom (nog niet gebouwd)

**Geen afgebakende waves met pauzes ertussen, maar een incrementele,
constante stroom** die naarmate de run vordert steeds zwaarder wordt. Er is
dus geen "wave X begint", geen aftelling en geen moment waarop de map leeg
is — er komt simpelweg meer.

De druk is dus een functie van de tijd (of de score):

- **Hoeveel** er tegelijk in leven zijn, loopt op mét een plafond. Zonder
  dat plafond stapelen ze op tot de map vol is en loopt de boel vast.
- **Hoe vaak** er een nieuwe bijkomt, neemt af naarmate de run duurt.
- **De mix** verschuift: eerst makkelijke types, later zwaardere en meer.
- De hele regeling hoort als een eigen blok in `config.GAMEMODES`, niet als
  een modenaamcheck — precies zoals de rest van de gamemodes.

### Wat de kaart al moet leveren

- **Spawn-punten zijn de rode `X`-tegels.** Die komen nu al in
  `spawns["enemies"]` terecht en dienen als bronlijst voor de stroom. De 20
  in het grondplan liggen verspreid over ring, kruisgang en de armen, zodat
  vijanden niet allemaal uit dezelfde hoek komen en er altijd een bezet kan
  zijn zonder dat de volgende blijft hangen.
- Daarbij hoort `spawn_enemies_at_start = False`: er staat er geen meteen
  bij de start; de stroom brengt ze.

### Nog te bepalen

- de escalatiecurve en het plafond
- wat de speler wint (survival stopt niet vanzelf: `level_progression` is
  False, dus geen uitgang — overleefde tijd? score?)
- wat er gebeurt als alle spawns bezet zijn: wachten, of een plek vrijmaken

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

## Openstaande keuzes

1. **Trapmodel:** besloten om het *na* de rest te kiezen — zie "Stand —
   besloten op 2026-10-07". Alleen het `floor`-veld moet er meteen in.
2. **Health-kleur — beslist, oranje (255,128,0), id 8.** Die waarden
   stonden nergens anders in `color_to_number`, dus het bleef oranje. Dit
   punt blijft hier staan omdat `map_loader` ernaar verwijst; als de campaign
   die kleur ooit gaat gebruiken, kies dan hier eerst iets anders.
3. **Escalatie van de vijandenstroom:** curve, plafond en wat de speler
   wint. Zie "Vijandenstroom".

## Ver in de toekomst

- **Keybind mapping.** De gebruiker wil ooit een instellingenpagina waar
  toetsen toegewezen kunnen worden (nu zitten ZQSD/muisknop/spatie vast in
  de code, zie `handle_input()` en `handle_events()`). Nu niet aan beginnen,
  maar het hoort hier wel bij: zo'n scherm raakt dezelfde invoercode als de
  spatiebalk die er net bij kwam, dus houd `handle_input()` / `_try_fire()`
  leesbaar.
