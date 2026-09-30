# TODO

## Minimap: ontdekken in plaats van alles zien

Uitgepraak op 2026-09-30, nog niet uitgevoerd.

Wensen:
- De minimap toont de **hele level** (22-40 tegels per kant past ruim in het
  huidige vakje van 12% van min(WIDTH, HEIGHT)), maar alleen de tegels die de
  speler al heeft gezien. De kaart vult zich dus op naarmate je verkent.
- **Vijanden alleen als je ze echt ziet**: geen punt op de kaart meer als er een
  muur tussen zit. Ze verdwijnen dus ook weer als je je omdraait.
- De **uitgang, keycard en andere objects** vallen onder dezelfde regel: pas
  tonen als je ze gezien hebt. Anders weet de speler alles vanaf het begin
  en is verkennen zinloos.
- De minimap staat **standaard uit**, met een setting om hem aan te zetten
  (net als de tutorial-toggle in het scherm Instellingen).

Huidige situatie in `src/ui/Menu.py` (`draw_minimap`, regel +-1584):
- `view_radius = 5`, dus een lokaal raampje van 10x10 tegels om de speler heen.
- Tegels worden getekend ongeacht of de speler ze kan zien: `M.MAP[y][x] == 1`
  bepaalt alleen muur of vloer.
- Vijanden (`minimap_show_enemies`) en objects (`minimap_show_objects`) worden
  getekend als ze binnen het raampje vallen, dwars door muren heen.

Nog uit te beslissen:
- Hoe ver ziet de speler per keer? Een flood-fill vanaf de tegel van de
  speler met een tegel-limiet geeft ook zicht om de hoek, wat waarschijnlijk
  beter voelt dan een kale stral per tegel. De berekening hoeft niet elke
  frame: hergebruik het resultaat zolang de speler op dezelfde tegel staat.
- Krijgt de speler een beetje "weeten" buiten de zichtlijn, of echt niets?
- Moet de instelling bestaan als "minimap aan/uit", of als drie standen
  (uit / alleen gezien / volledig)? De derde is handig om even te kunnen
  cheaten bij een lastig level.

Gereed: niets. `game.py:151-152` zet `minimap_show_enemies` en
`minimap_show_objects` op True; die vlaggen kunnen met de nieuwe regels weg.
