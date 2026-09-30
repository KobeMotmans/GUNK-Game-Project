# Installeren en de venv maken

Alles wat je hier leest is voor het **draaien van het spel uit de bron**. De
ingepakte versie (`dist/`, `GUNK.exe`) heeft hier niets mee te maken; die bouw
je met `build.ps1` en daar zit een eigen stukje tooling in dat je niet in een
venv hoeft te installeren.

Zie ook `Readme.md` voor het multiplayer-gedeelte en `requirements.txt` voor de
lijst met dependencies.

---

## 1. Python 3.10 nodig

Het spel draait op **Python 3.10**. Dat is belangrijk, want met een nieuwere
Python werken wij niet: sommige pygame-functies en de audio-initialisatie
doen het daar niet goed.

Controleer welke Python je hebt:

```
py -3.10 --version
```

Krijg je `Python 3.10.x`, goed. Krijg je `nothing found` of een ander versie,
dan staat Python 3.10 nog niet geïnstalleerd. Haal hem op van
[python.org/downloads/release/python-31011](https://www.python.org/downloads/release/python-31011/)
en vink bij het installeren **Add python.exe to PATH** aan.

> **Let op:** typ in de terminal gewoon `python` en je krijgt op sommige
> machines Python 3.14 of nieuwer, zonder pygame. Gebruik daarom overal
> `py -3.10`. In alle voorbeelden hieronder staat daarom `py -3.10` en niet
> `python`.

---

## 2. De venv aanmaken

Open een terminal **in de projectmap** (in VS Code: Terminal → Nieuwe
terminal; die start automatisch in de projectmap).

```
py -3.10 -m venv .venv
```

Dat maakt een map `.venv` met een eigen, lege Python-installatie. Alles wat je
daarna installeert komt daar alleen in te staan, en raakt je systeem-Python
niet aan. Dat is prettig: je kunt per project verschillende versies hebben
zonder dat ze elkaar in de weg zitten.

## 3. De dependencies installeren

```
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

De eerste regel werkt de pip in de venv zelf bij, de tweede leest
`requirements.txt` en installeert pygame, numpy en Pillow.

## 4. Het spel starten

```
.\.venv\Scripts\python.exe game.py
```

Dat is alles. De server draai je op dezelfde manier:

```
.\.venv\Scripts\python.exe run_server.py
```

En de tests:

```
.\.venv\Scripts\python.exe tests\mp_test.py
.\.venv\Scripts\python.exe tests\mp_test.py -v         # met tijden
.\.venv\Scripts\python.exe tests\mp_test.py elevator   # alleen de lift-tests
```

## 5. Of toch activeren

De voorbeelden hierboven roepen de Python in de venv telkens met het volledige
pad aan. Dat is het handigst omdat het ook werkt zonder dat je iets hoeft te
activeren. Wil je liever `python` gebruiken zonder dat hele pad, activeer dan
de venv één keer per terminal-sessie:

```
.\.venv\Scripts\Activate.ps1
```

Vanaf dat moment is `python` de venv-Python en werkt ook `python game.py`.

Werkt `Activate.ps1` niet met *"de uitvoering van scripts is uitgeschakeld op
dit systeem"* (komt vaak voor na een Windows-herinstallatie), dan heb je twee
opties:

- **Zet het aan voor je eigen account** (eenmalig, PowerShell sluiten en
  openen):

  ```
  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
  ```

- Of blijf gewoon `.\.venv\Scripts\python.exe` typen, wat per stap 4 ook
  prima werkt en niets aan je systeem verandert.

Kies in VS Code rechtsonder de Python-versie. Kies `.venv`, dan gebruiken de
knop om te starten en de terminal automatisch de venv.

---

## 6. Begin je opnieuw

Alles in de venv is weggooiwerk; hij is alleen een plek om je dependencies te
bewaren. Om een versie terug te draaien bij een probleem, gooi hem gewoon weg
en maak hem opnieuw:

```
Remove-Item -Recurse -Force .venv
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

(`Remove-Item` is PowerShell. Gebruik je een `cmd`-prompt, dan is het
`rmdir /s /q .venv`.)

De `.venv`-map staat in `.gitignore` en komt dus niet in de repository, net
als de andere build- en cachespuigjes.

---

## 7. Als er iets misgaat

**`ModuleNotFoundError: No module named 'pygame'`**
Je draait niet de Python uit de venv. Controleer met
`.\.venv\Scripts\python.exe -c "import pygame; print(pygame.version.ver)"`
of die pygame ziet. Komt daar een fout, dan is stap 3 niet (goed) gebeurd of
jouw pad klopt niet.

**`python` geeft een versie 3.12 of hoger**
Zoals hierboven: gebruik `py -3.10`.

**`No module named 'venv'`**
Python is niet compleet geïnstalleerd, of je gebruikt een Windows Store-versie
waarbij de venv-module ontbreekt. Installeer Python 3.10 opnieuw vanaf
python.org.

**`pip` klaagt over een versieconflict met Pillow of NumPy**
De venv zou dan al spullen moeten bevatten die er niet in horen. Gooi hem weg
en maak hem opnieuw volgens stap 6.

**Geluid of video doet het niet in een test**
De tests draaien headless en zetten daarom zelf `SDL_VIDEODRIVER` en
`SDL_AUDIODRIVER` op `dummy`. Dat is normaal gedrag, geen fout.
