# TODO

## Minimap: ontdekken in plaats van alles zien

Uitgewerkt op 2026-09-30. De kaart staat in `src/core/minimap.py` (de
zichtberekening, zonder pygame) en in `Menu.draw_minimap` (de tekening).

### Wat het nu doet
- De minimap toont de **hele level** met de verhouding intact, in het vakje
  van 12% van `min(WIDTH, HEIGHT)`. De kaarten zijn 22 tot 40 tegels per kant,
  dus dat past ruim.
- Alleen de tegels die de speler heeft gezien staan erop. Gezien betekent
  onthouden: wegloopen maakt de kaart niet meer leeg, alleen donkerder.
- **Vijanden alleen als de speler ze nu echt ziet.** Ze verdwijnen dus weer
  zodra je je omdraait of een muur omloopt. Ze staan nooit door een muur heen.
- **Uitgang, keycard, ammo en health** verschijnen zodra je de tegel waar ze
  op liggen hebt gezien, en blijven daarna staan.
- **Teamgenoten** staan er altijd, ook door muren: het zijn je eigen mensen en
  je moet ze terug kunnen vinden als je ze kwijt bent.
- De kaart staat **standaard uit**, met drie standen in Instellingen:
  `MINIMAP: OFF` / `SEEN` / `ALL`. `ALL` is de cheatstand voor een lastig level.

### Hoe zicht werkt
Flood-fill vanaf de tegel van de speler, vier richtingen:
- een muur is zelf zichtbaar maar verspreidt het zicht niet verder;
- de verspreiding stopt na `minimap.view_radius` tegels (7);
- de verspreiding blijft binnen de kijkhoek van de speler (`FOV` uit
  `config.py`), want dit is een raycaster.

Die laatste twee zijn samen de "om de hoek"-regel: een gang die een stukje
omloopt zie je wel, want de tegels ervan liggen binnen de kegel en er staat geen
muur tussen. Een tegel recht achter je zie je niet.

### Waarom een eigen teller en geen `M.map_level`
Het onthouden wordt gewist zodra de kaart verandert, en dat wordt herkend aan
het kaartobject zelf (`M.MAP is niet de vorige lijst`), niet aan het
levelnummer. Bij zelfhosten draait de server in een draadje in hetzelfde
proces en deelt hij de singleton `M`, dus `M.map_level` loopt vooruit op het
moment dat de client iets te tekenen krijgt. Precies dezelfde valkuil als bij de
teleport in `apply_state`. `png_to_list_fast` maakt bij elke level een verse
lijst, dus de vergelijking is waterdicht — en het is ook meteen de enige plek
die een levelwissel hoeft af te handelen, in plaats van vier.

### Prestaties
De kaart bestaat uit twee oppervlakken van één pixel per tegel. De helder
getekende laag is statisch; de onthouden laag wordt alleen opnieuw getekend
als de speler écht nieuwe tegels heeft ontdekt (een `versie`-teller op de
tracker). In de stand `ALL` is er per frame geen enkel werk, en anders is het
één `copy()` plus één `set_at` per zichtbare tegel. `pygame.transform.scale`
doet het vergroten. Een level van 40x40 is anders 1600 `pygame.draw.rect`
aanroepen per frame.

Een cache zit bewust niet op de spelerpositie: die verandert elke frame, dus
dat zou de kaart steeds opnieuw herberekenen zonder winst. Het zicht is
goedkoop genoeg om elke frame te doen.

### Tests
`tests/mp_test.py`:
- `minimap_ziet_niet_door_muren`
- `minimap_ziet_altijd_de_tegel_waar_je_op_staat`
- `minimap_ziet_om_de_hoek_mar_niet_achter_je_rug`
- `minimap_onthoudt_tegels_die_je_al_gezien_hebt`
- `minimap_vergeet_alles_bij_een_nieuw_level`
- `minimap_groeit_met_waar_je_hebt_geloopen`
- `minimap_cheatstand_onthoudt_niets`
- `minimap_uit_onthoudt_niets`

Alle acht zijn langs een mutatierunner gehaald: elke regel van de
zichtberekening een voor een uitgezet, en elke keer werd minstens één test
rood. Die runner vond onder andere twee tests die ik zelf te makkelijk had
geouwd: een kaart van twintig tegels waarin het zichtbereik nooit de grens
haalt, en een "volgend level" dat identiek was aan het vorige, waardoor
onthouden niet te onderscheiden was van opnieuw zien.

De tekentest (`ui_lobby_joinscherm_en_hud_tekenen_zonder_fout`) doet hetzelfde
met de tekening en de instelling, en kijkt bovendien in de pixels: de onthouden
laag bevat precies de tegels uit `fog.gezien`, muren en vloeren hebben
verschillende kleuren, en met de kaart uit worden de lagen niet eens
opgebouwd. Let op: het echte schermbuffer niet vergelijken, de inhoud daarvan
is met de dummy videodriver niet betrouwbaar. De test zet daarom zelf een
eigen oppervlak onder `_cfg.SCREEN`, tekent daarop en leest de pixels daar
weer uit.

### Het pijltje van de speler
Het groene driehoekje stond een tijdje in het **midden** van het vakje, met een
commenta dat het daar moest: "makkelijker te vinden dan een groen puntje tussen
de muren". Dat klopt als de kaart een raampje om de speler is, maar niet meer
nu hij de hele level toont. Dan zegt een pijltje in het midden "hier ben ik"
terwijl de speler ergens anders op de kaart staat, en dat is misleidend zodra
je de kaart echt gebruikt om te navigeren.

Het gaat nu door dezelfde `to_mm` als alle andere markers, dus het staat op de
tegel waar de speler staat. De tekentest rekent die positie zelf na en kijkt of
er daar groen staat, en ook of er midden in het vakje géén groen staat — die
laatste assertie is belangrijk, want anders zou een pijltje dat halfweg
gepositioneerd is zomaar door de test heen glijden.

Twee dingen kwamen daaruit:
- een `return` in de tak "speler valt buiten de kaart" bleek de héle kaart te
  overslaan, want het oppervlak wordt pas op het laatste op het scherm
  gezet. Het is nu een voorwaarde om een blok heen;
- het pijltje kreeg een donkere rand eronder, anders valt het weg op een tegel
  die al bijna dezelfde kleur heeft.

### Valkuil bij het testen van tekening
Een mutatierunner die een bronbestand herschrijft kan zichzelf afschieten.
`open(pad, "w")` wordt in Python geëvalueerd vóór de `.replace()` die erin
moet staan, dus zodra die replace barst, staat het bestand al leeg. Terugzetten
in een `finally` helpt dan niet meer, want die staat pas ná de regel die het
bestand leegmaakte. De volgorde moet dus zijn: eerst de nieuwe inhoud in een
variabele zetten, dan pas het bestand openen.

`src/ui/Menu.py` was daardoor een keer 0 bytes en moest terug uit de commit.
Daarom is de fix op het pijltje meteen apart gecommit en niet pas aan het
einde.

### Nog niet gedaan
- De levelnaam staat niet op de kaart. Met vijf levels is dat handig om te weten
  waar je bent, maar het is een extra regel tekst die in het vakje moet passen.
- De minimap is niet zichtbaar in het meekijken-scherm (`spectating` tekent
  hem wel, maar dan met de positie van je eigen dode speler).
- Geen muisaanwijzer op de kaart.

