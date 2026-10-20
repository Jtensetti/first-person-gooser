# Smygehuk med ortofoto – 16 oktober 2026

Den lokala Blender-scenen och flygprototypen använder nu Lantmäteriets ortofoto över hela pilotkilometern. Fyra marktexturer på 3125 × 3125 pixlar behåller källans 16 cm/pixel. Den tidigare 10 m Sentinel-bilden har ersatts i pilotens markmaterial och karta.

## Starta flygningen

Dubbelklicka på STARTA_GASEN.cmd i det färdiga paketet, eller kör `python start.py`. Python 3 och en webbläsare med WebGL2 behövs. Servern använder endast den egna datorn och väljer en ledig port från 4174. En äldre version på samma port ersätts inte. På leveransdatorn är den nya versionen öppnad på http://127.0.0.1:4176/.

A/D svänger, W/S ändrar fart, E/Q ändrar höjd, Esc pausar. Musen styr; håll vänster knapp och dra om pekaren är fri. M öppnar kartan, P fotoläget. Hela paketet fungerar utan internet. Välj Lätt under Inställningar om datorn behöver lägre grafikbelastning.

## Verifierat underlag

- Fil: `o61325_3950_25_mr24.tif`, tillhandahållen av användaren efter beviljad Ortofoto Nedladdning-behörighet.
- Filstorlek: 616 377 978 byte, identisk med STAC-postens uppgift.
- SHA-256: `ca017280bc63c8b0544cd2e24505547508d5d59a3d7dba3be5e039d07f5bea4b`.
- EPSG:3006, utbredning `[395000, 6132500, 397500, 6135000]`, 15625 × 15625 pixlar, 0,16 m/pixel.
- Fyra uint8-band; filens egna färgtolkningar anger rött, grönt och blått för band 1–3. Det fjärde bandet används inte som synligt ljus.
- Bildinsamling enligt STAC: 21 maj 2024 kl. 14:24:36–14:50:41 UTC. Produktens tillverkningsdatum 2025 är inte fotograferingsåret.
- Pilot: `[395500, 6133500, 396500, 6134500]`, helt täckt utan luckor i de fyra framställda texturerna. Terrängens RH2000-höjder och laserbaserade byggnadsgeometri är oförändrade.

Produktkälla: https://dl1.lantmateriet.se/bild/data/orto/se0_16m_sweref/2024_A2/o61325_3950_25_mr24.tif

Ortofoto Nedladdning © Lantmäteriet, CC BY 4.0. Bilderna har beskurits, återprojicerats/samplats till projektets texturrutor och lagts på terränggeometri. För den grövre omgivningen används en nedskalad 2048 × 2048-bild över 2,5 km, cirka 1,22 m/pixel. Produkten omfattas också av det beviljade användningsändamålet och [villkoren för värdefulla datamängder som innehåller personuppgifter](https://www.lantmateriet.se/globalassets/geodata/geodataprodukter/anvandningsvillkor_for_vardefulla_datamangder_pu.pdf). Världs- och bildfilerna behålls lokalt; ingen ny publik datadistribution har gjorts.

## Hur material och geometri samverkar

Terräng, åkrar, draperade vägar och övriga markytor får samma geografiska UV-mappning. Generiska markfärger täcker därför inte längre fotograferade gräsmattor, parkeringar, uppfarter eller stranddetaljer. Modellerade vägmarkeringar döljs när ortofoto används. Vägarnas geometri och höjd följer fortfarande den befintliga rekonstruktionen. Byggnadernas fasader och tak behåller separata material; ett ortofoto är inte en fasadrekonstruktion. Havet använder fortfarande separat vattengeometri.

Omgivningens mark får också ortofotofärg, men är fortfarande en 20 m terrängmodell utan fullständiga 3D-byggnader. Det flygbara området är fortsatt 1 km². Flygkontrollerna är oförändrade.

## Reproduktion

Den exakta STAC-posten, flygbildsmetadata, villkor och källkvitto ligger lokalt under `data/win52/orthophoto/`. Den befintliga miljökatalogen är utökad till `data/win52/catalog-orthophoto.json`. Råfilen och katalogen ligger utanför Git.

```powershell
python scripts/adopt_orthophoto.py --catalog data/win52/catalog-environment.json --image data/win52/orthophoto/o61325_3950_25_mr24.tif --rgb-bands 1 2 3 --year 2024 --output data/win52/catalog-orthophoto.json
python -m goosen.cli prepare --config configs/pilot-orthophoto.json --catalog data/win52/catalog-orthophoto.json --output build/orthophoto-world --preview
python -m goosen.cli qa --world build/orthophoto-world
blender -b --factory-startup --python-exit-code 1 -P blender/build_world.py -- --world build/orthophoto-world --output build/orthophoto-blender --allow-preview --isolate-scene --export-glb
python scripts/stage_runtime.py --world build/orthophoto-world --scene build/orthophoto-blender --output build/orthophoto-runtime-world
python scripts/stage_horizon.py --terrain data/win52/open-dtm/61325_3950_25.tif --landcover ../nbs-sandbox-trelleborg/public/data/nmd2023_landcover_x03_y02.tif ../nbs-sandbox-trelleborg/public/data/nmd2023_landcover_x04_y02.tif --orthophoto data/win52/orthophoto/o61325_3950_25_mr24.tif --output build/orthophoto-runtime-world
```

Välj tomma målsökvägar för katalogadoption, staging och paketering. Placera staged world under `runtime/public/world` efter att tidigare innehåll har säkerhetskopierats. Kör `npm ci`, `npm test`, `npm run build` i runtime, sedan `python scripts/package_runtime.py --guide docs/ORTHOPHOTO-2026-10-16.md --output <tom-leveransmapp>` från repo-roten.

## Kvalitetskontroll och kvarvarande begränsningar

Filstorlek, SHA-256, koordinatsystem, upplösning, bandordning, täckning och texturdimensioner kontrolleras. Geometrins QA passerar; 60 Python-tester och fyra flygtester passerar. Blender 5.2.2 bygger scenen och renderar hamn, bostäder och takdetalj. Den lokala leveransen inkluderar separata rapporter och bilder från testning i webbläsare.

Ortofotot innehåller fotograferade skuggor, trädkronor och bilar; dessa kan se platta ut på marken och överlappar delvis den modellerade världen. Flygbilderna är från maj 2024 medan åkerklassificeringen är från 2025 och flera andra lager har egna datum. Ingen exakt samtidig årstidsrekonstruktion påstås. Husens färger och komplexa tak, vegetationens kvalitet samt kustens lokala avvikelser behöver fortsatt visuell granskning. Högupplöst markfärg betyder inte att hus och vegetation blivit fotogrammetriskt rekonstruerade.
