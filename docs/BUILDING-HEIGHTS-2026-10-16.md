# Rättade hushöjder – 16 oktober 2026

Användarens lokalkännedom påvisade att flera hus såg ut som flervåningshus. Granskningen fann två fel i reservmodellen: höga laserpunkter användes även när ingen takmodell kunde verifieras, och fasadgeneratorn skapade våningsrader automatiskt från väggens höjd. Trädinblandning är en sannolik felkälla för små stugor med tidigare uppskattade höjder över 10 meter; detta är inte verifierade hushöjder.

Markreferensen är konsistent: jämförelsen mellan markklassade laserpunkter och terrängen ger medianavvikelsen −0,001 m och 95-percentilen av absolutavvikelsen 0,081 m. Ingen generell höjdförskjutning har gjorts.

## Ändring

- Pilotens uttryckliga reservmodell använder 3,0 m takfot, eller 2,4 m för små uthus/stugor, plus modellerad takresning. Detta är en lokal modelleringsregel, inte en uppgift om varje hus eller hela kommunen.
- Regeln används endast när godkänd laserbaserad takgeometri saknas, för valda byggnadstyper med högst 600 m² footprint. Fyr och större/särskilda byggnadstyper undantas. Byggnadspolygoner bevaras.
- Konkava småhuspolygoner får ett förenklat valmat tak med låg takfot runt hela polygonen, i stället för en hög platt låda. Exakt utformning av vinkeltak är fortfarande modellerad. Footprints och eventuella hål bevaras.
- Fasadfönster får en modellerad våningsrad som standard; takhöjd är inte evidens för flera våningar. Inredd vind eller exakta fönster är inte rekonstruerade.
- 80 byggnaders reservgeometri ändrades. Samtliga 173 accepterade laserbaserade tak är geometriskt oförändrade. Terräng, vägar, vegetation och ortofoto är oförändrade. Flygningens hinderhöjder byggs om från de nya modellerna.

## Leverans och kontroll

Den korrigerade lokala flygversionen finns i `outputs/goosen-laga-hus-2026-10-16` och startas med STARTA_GASEN.cmd. Den nya lokala adressen är http://127.0.0.1:4177/. Blender-scenen och tre kontrollvyer finns i `outputs/smygehuk-laga-hus-2026-10-16`. Föregående leverans är bevarad.

62 Python-tester passerar, inklusive regressionsfall där orimliga lasermaxima inte får påverka reservhusens höjd och ett konkavt footprint behåller sin area. Geometrisk QA passerar, och fem GLB-filer validerar utan fel eller varningar. `blender/check_facades.py` verifierar i Blender att väggar från 2,65 till 15 meter inte automatiskt får fler fönstervåningar. Lokalt finns jämförelsen per ändrad byggnad under `outputs/hushojder-kontroll-2026-10-16/height-comparison.json`.

Reproduktion följer ortofotoguiden med `build/lowrise-final-world`, `build/lowrise-final-runtime-world` och den nya Blender-utkatalogen. Konfigurationen är fortsatt `configs/pilot-orthophoto.json`. Staga även om omgivningen med samma ortofoto. Bygg sedan runtime och paketera med denna guide. Rådata och genererad värld publiceras inte i Git.

Kontrollerade laserplan kan fortfarande ha lokala fel, och reservhusens exakta höjd behöver ytterligare data. Korrigeringen innebär inte att samtliga hus nu är individuellt uppmätta eller fotogrammetriskt rekonstruerade.
