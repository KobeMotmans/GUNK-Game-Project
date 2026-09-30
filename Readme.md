```
https://github.com/KobeMotmans/GUNK-Game-Project
Om het spel te runnen, voer game.py uit
Python 3.10
Project Software en AI:
Kobe Motmans, Andreas Meuwissen en, Ruben Verreth IR3-1   
  ________ ____ __________   ____  __.                                                                                  
 /  _____/|    |   \      \ |    |/ _|                                                                                  
/   \  ___|    |   /   |   \|      <                                                                                    
\    \_\  \    |  /    |    \    |  \                                                                                   
 \______  /______/\____|__  /____|__ \                                                                                  
        \/                \/        \/                                                                                  
 ____  __.    ___.               _____          __                                                                      
|    |/ _|____\_ |__   ____     /     \   _____/  |_  _____ _____    ____   ______                                      
|      < /  _ \| __ \_/ __ \   /  \ /  \ /  _ \   __\/     \\__  \  /    \ /  ___/                                      
|    |  (  <_> ) \_\ \  ___/  /    Y    (  <_> )  | |  Y Y  \/ __ \|   |  \\___ \                                       
|____|__ \____/|___  /\___  > \____|__  /\____/|__| |__|_|  (____  /___|  /____  > /\                                   
        \/         \/     \/          \/                  \/     \/     \/     \/  )/                                   
   _____              .___                                 _____                       .__                              
  /  _  \   ____    __| _/______   ____ _____    ______   /     \   ____  __ ____  _  _|__| ______ ______ ____   ____   
 /  /_\  \ /    \  / __ |\_  __ \_/ __ \\__  \  /  ___/  /  \ /  \_/ __ \|  |  \ \/ \/ /  |/  ___//  ___// __ \ /    \  
/    |    \   |  \/ /_/ | |  | \/\  ___/ / __ \_\___ \  /    Y    \  ___/|  |  /\     /|  |\___ \ \___ \\  ___/|   |  \ 
\____|__  /___|  /\____ | |__|    \___  >____  /____  > \____|__  /\___  >____/  \/\_/ |__/____  >____  >\___  >___|  / 
        \/     \/      \/             \/     \/     \/          \/     \/                      \/     \/     \/     \/  
 __________     ___.                   ____   ____                           __  .__                     
\______   \__ _\_ |__   ____   ____   \   \ /   /__________________   _____/  |_|  |__                  
|       _/  |  \ __ \_/ __ \ /    \   \   Y   // __ \_  __ \_  __ \_/ __ \   __\  |  \                 
|    |   \  |  / \_\ \  ___/|   |  \   \     /\  ___/|  | \/|  | \/\  ___/|  | |   Y  \                
|____|_  /____/|___  /\___  >___|  /    \___/  \___  >__|   |__|    \___  >__| |___|  /                  
 ```

## Multiplayer

### Server starten

De server draait in een apart venster, zonder venster:

```
python run_server.py
```

Bij het opstarten zoekt de server zelf uit hoe hij bereikbaar is en drukt
daarover het volgende af:

```
[SERVER] LAN       : 192.168.1.42:5555
[SERVER] Internet : 82.196.7.3   (via NAT-PMP)
```

- **LAN** werkt altijd, zolang alle spelers op hetzelfde netwerk zitten.
- **Internet** gaat via NAT-PMP (RFC 6886): de server vraagt je router om de
  poort naar buiten toe open te zetten en leest daarna je publieke IP op.
  Lukt NAT-PMP niet, dan wordt je publieke IP via STUN opgehaald. Dat opent
  niets, dus dan moet je de poort zelf openzetten in je router.

Opties:

| Optie | Wat het doet |
|---|---|
| `--port POORT` | andere poort (standaard 5555) |
| `--max-players N` | aantal spelers (standaard 6, max 16) |
| `--no-port-map` | geen routerpoging, alleen het IP opzoeken |
| `--gateway IP` | router expliciet opgeven, anders wordt x.x.x.1 geprobeerd |
| `--public-ip IP` | publiek adres overslaan en dit opgeven |

### Samen spelen

Elke speler kiest in het menu **JOIN SERVER** en vult het adres en de poort in
die de host heeft afgedrukt. Het spel start zodra iedereen op **READY UP** heeft
gedrukt; de host kan ook zelf op **START** drukken.

De lift vertrekt zodra alle levende spelers bij de uitgang staan. Houdt er
iemand vast, dan staat er boven in beeld hoeveel er nog moeten komen
(`Wacht op teamgenoten (4/6)`). Blijft dat te lang hangen, dan vertrekt de lift
na 30 seconden alsnog, zodat een level nooit vast kan blijven staan.

### Zelf hosten

Je hoeft geen tweede venster te openen. In **MULTIPLAYER** staat naast
**JOIN GAME** een **HOST SERVER**-knop: de server draait dan als een
achtergronddraadje in hetzelfde proces en je bent zelf meteen speler 0
(host). Sluit je het spel af, dan stopt de server weer.

In de lobby zie je dan welk adres gasten moeten invullen:

```
LAN: 192.168.1.42:5555
Internet: 82.196.7.3:5555
```

Werkt de poort niet vanaf internet, dan staat er `(poort nog niet open)`.
Dat betekent dat je router geen NAT-PMP kent. Dan moet de poort `5555/UDP`
handmatig in je router worden doorgestuurd; op een campus- of bedrijfsnetwerk
kan dat meestal niet, en dan speel je gewoon op het LAN-adres.

Let op bij een uitgepakte versie: Windows Firewall geeft toestemanding per
programma, niet per poort. Onder Python werkt het meteen, maar `GUNK.exe`
heeft een eigen regel nodig (Windows Firewall → Inbound rules → New rule →
Program).

### Servers zoeken op je netwerk

Iedere draaiende server zendt elke 2 seconden een aankondiging (75 bytes)
op de LAN. In het multiplayer-menu verschijnen die servers dan vanzelf in een
lijst onder **SERVERS IN JOUW NETWERK**; klik erop en je zit ernaartoe.

Dit werkt met UDP-broadcast en dus **niet** via NAT: broadcast gaat nooit
langs een router, wat precies de reden is dat het thuis wél werkt. Hetzelfde
geldt in de andere richting — een campus- of zakelijk WLAN houdt verkeer
tussen laptops tegen, dus daar blijft de lijst leeg. Dat is geen fout: vul
dan gewoon het IP van de host in.

### Dood en meekijken

Bij gedeeld leven doodgaan betekent het einde van de run voor iedereen.
Maakt de groep eerst **shared health = UIT**, dan kan een dode speler op
**MEEKIJKEN** klikken en de camera volgt een levende teamgenoot. Met
**Q** en **E** wissel je van persoon, **ESC** stopt het meekijken.

### Zelf testen

```
python tests/mp_test.py           # alles
python tests/mp_test.py -v        # met tijden
python tests/mp_test.py elevator  # alleen tests met 'elevator' in de naam
```

De tests draaien headless, starten zelf een echte server op 127.0.0.1 en praten
er nep-clients mee. Ze raken je eigen bestanden niet aan: mp_config.json en
server_skins/ worden na afloop teruggezet.