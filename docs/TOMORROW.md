# Körguide inför 7 oktober 2026

Allt nedan körs från repots rot. Använd ett nytt jobbnamn för varje byggning så att en fungerande leverans inte skrivs över. Rådata och Blender-resultat ligger utanför Git. Den första genomförda körningen är dokumenterad i [VALIDATION](VALIDATION.md).

## 1. Installera och lås källrepot

Krav: Python 3.11/3.12, Git med åtkomst till det privata NBS-repot, Blender 4.5 eller senare (kört med 4.5.3 LTS). Ingen installation av Pythonbibliotek inuti Blender behövs.

```bash
git clone https://github.com/Jtensetti/first-person-gooser.git
cd first-person-gooser
python -m venv .venv
```

Aktivera miljön med `source .venv/bin/activate` på Linux/macOS eller `.venv\Scripts\Activate.ps1` i PowerShell. Installera sedan:

```bash
python -m pip install -e '.[dev]'
pytest -q
```

Om NBS-repot redan finns med pågående ändringar, skapa en separat läsbar revision. Kommandot ändrar inte arbetskopians filer:

```bash
git -C ../nbs-sandbox-trelleborg fetch origin
git -C ../nbs-sandbox-trelleborg worktree add --detach ../nbs-goosen-pinned 8263aa2f583170fc3a6a6bf6f3f174a7c8ac4322
```

Alternativt låter nästa skript klona till en ännu ej existerande mapp. Använd befintlig Git/gh-inloggning; privata repobehörigheter följer inte med en kopia av detta offentliga repo.

## 2. Kör hela kedjan

Linux/macOS, exempel (byt Blender-sökvägen):

```bash
python scripts/prepare_tomorrow.py --source ../nbs-goosen-pinned --job pilot --osm --blender /opt/blender/blender
```

PowerShell, exempel (byt versionsmapp vid behov):

```powershell
python scripts/prepare_tomorrow.py --source ../nbs-goosen-pinned --job pilot --osm --blender 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe'
```

Skriptet låser rätt källrevision, flyttar relevanta NMD-/previewhöjdtiles, bevarar relevanta ursprungsskript, hämtar 2025-skiften och valda OSM-kompletteringar, genererar fyra tiles, kör QA och startar Blender om programmet hittas. Internet behövs för nya WFS-/OSM-uttag. OSM är uttryckligt reservunderlag; ingen kommunal källa antas licensierad bara för att den går att nå.

Resultat:

| Sökväg | Innehåll |
|---|---|
| `data/pilot/catalog.json` | Låsta källfiler, hash, CRS, evidens och grödkoder |
| `data/pilot/transfer-plan.json` | Urval och kontrollsummor från NBS |
| `data/pilot/nbs/upstream/` | Relevanta ursprungsskript, kommungräns och NMD-metadata |
| `build/pilot/manifest.json` | Tilelista, gap och geografisk referens |
| `build/pilot/qa.json` | Strukturkontroller |
| `build/pilot-blender/goosen-pilot.blend` | Öppningsbar Blender-scen |
| `build/pilot-blender/*-lod0.glb` | Fyra tilelokala basmesh-exporter |
| `build/pilot-blender/*-instances.json` | Kompakta instanser, inte realiserad växtgeometri |
| `build/pilot-blender/inspection.png` | Teknisk kontrollrendering |

Utan Blender körs Python-delen färdigt. Starta sedan Blender separat:

```bash
blender -b --factory-startup --python-exit-code 1 -P blender/build_world.py -- --world build/pilot --output build/pilot-blender --allow-preview --export-glb --render
```

Välj `--lod 1` eller `--lod 2` och **en annan outputmapp** för alternativa terräng-LOD. Byggaren använder återanvändbara prototype-assets, inte färdiga fotorealistiska växter. `--allow-preview` behövs eftersom underlaget inte uppfyller slutkraven.

## 3. Flytta över data som redan är hämtade

För att undvika nya liveuttag på nästa dator:

```bash
python scripts/pack_inputs.py --catalog data/pilot/catalog.json --output build/handoff/pilot-inputs.zip
```

Paketet har en SHA-256 per fil, separat hash för ZIP-filen och licensstatusar. Det tar med tillhörande metadata och låsta upstreamreferenser. Kopiera ZIP-filen och hashfilen till avsedd arbetsdator eller godkänd datalagring. Packa upp till `data/pilot/`, verifiera katalogen genom att köra `prepare`, och behåll relativa sökvägar. Paketet är **inte** automatiskt godkänt för offentlig publicering.

```bash
goosen prepare --catalog data/pilot/catalog.json --output build/pilot-transfer --preview
goosen qa --world build/pilot-transfer
```

Nedladdningskatalog, referensbilder och framtida assetbibliotek ska ha egna tillståndsposter. Publicera inte stora råfiler genom att ta bort `.gitignore`. Objektlagring kan väljas senare; inga molnkonton eller behörigheter skapas av denna leverans.

## 4. Ersätt den grova previewhöjden med LM-data

Detta är nästa viktigaste förbättring. De verifierade filreferenserna är förberedda i `configs/lm-dtm.asset.json` och `configs/lm-lidar.asset.json`: cirka 175 MB DTM + 539 MB LiDAR före lokalt urval. Kör ny discovery om katalogen har ändrats:

```bash
goosen discover --output data/discovery-2026-10-07
```

**Kontoinnehavaren behöver först** ordna GeoTorget-åtkomst till Markhöjdmodell nedladdning och Laserdata nedladdning, skog, samt godkänna produkternas aktuella villkor. Filanropet svarade 401 här. Det publika metadata-API:t räcker alltså inte för filhämtning.

Kopiera `configs/permission.example.json` till `configs/lm-permission.local.json`. Registrera faktisk licens, dokumenterat beslut/villkorsreferens, `use_status: authorized` och de exakta asset-URL:erna i `allowed_sources`. Mallen är inte ett juridiskt godkännande. Behåll `redistribution_status: review` tills vidareleverans är utredd.

Sätt `LM_USER` och `LM_PASSWORD` som lokala miljövariabler med de produktuppgifter tjänsten kräver. Använd en säker lokal inmatning/credential manager; klistra inte in dem i repot eller här i chatten. Därefter:

```bash
goosen fetch-lm --asset configs/lm-dtm.asset.json --permission configs/lm-permission.local.json --output data/pilot/lm-dtm.tif
goosen fetch-lm --asset configs/lm-lidar.asset.json --permission configs/lm-permission.local.json --output data/pilot/lm-lidar.copc.laz
python scripts/adopt_lm.py --catalog data/pilot/catalog.json --dtm data/pilot/lm-dtm.tif --lidar data/pilot/lm-lidar.copc.laz --output data/pilot/catalog-lm.json
goosen prepare --catalog data/pilot/catalog-lm.json --output build/pilot-lm --preview
```

Geometrin blir bättre, men tak, ortofoto, kust och färdiga assets måste fortfarande godkännas. Den vanliga strikta byggvägen avvisar kända gap. Den här versionens vegetation-/materialpass är uttryckligen ofärdigt och ger därför inte ett slutgodkännande ens med alla höjdfiler.

## 5. Kommunens data och bättre vägar

Bekräfta återanvändningsrätt för kommunala footprints, 3D-byggnader, markmodell och ortofoto, inklusive eventuell rätt att baka och distribuera härledda tiles. Bekräfta dessutom RH2000 för 3D-lagrets Z. Lägg tillståndet i en separat lokal permission-fil och kör, när det faktiskt är klart:

```bash
goosen fetch-municipal --layer buildings --permission configs/municipal-permission.local.json --output data/pilot/municipal-buildings.json
goosen fetch-municipal --layer buildings3d --permission configs/municipal-permission.local.json --output data/pilot/municipal-buildings3d.json
```

Byt ut katalogens `buildings`-post mot den verifierade 2D-källan; behåll inte både OSM och kommunen utan deduplicering. 3D-multipatch-hämtningen är förberedd, men en importerare som bevarar taktopologin återstår. Vattenlinjer är inte färdiga vattenpolygoner. Väglinjer utan attribut ger inte automatiskt rätt vägstandard.

För officiell väg-/järnvägsgeometri: ordna Lastkajen-uttag för pilotboxen och begär bredd/klass/bro/tunnel/spår. Normalisera till dokumenterat GeoJSON-kontrakt innan körning. Ingen sådan åtkomst fanns i denna session.

## 6. Satellit och fortsättning

Satellit behövs inte för att testa Blender-kedjan. Vid verkligt behov, installera `python -m pip install -e '.[earthengine]'`, använd ett behörigt Earth Engine-projekt och autentisera lokalt. Exempel:

```bash
python scripts/fetch_satellite.py --product alphaearth --year 2024 --project YOUR_AUTHORIZED_PROJECT --output data/alphaearth-2024
python scripts/fetch_satellite.py --product ndvi --year 2025 --project YOUR_AUTHORIZED_PROJECT --output data/ndvi-2025
```

Skriptet är förberett och syntaktiskt kontrollerat; det har inte körts mot ett autentiserat Earth Engine-konto här. Årsdata ersätts inte tyst när de saknas. Originalets felaktiga collection-ID används inte.

Nästa arbetsordning: LM DTM/LiDAR → kommunala footprints/3D → riktig kust och vägbredd → ortofoto → artspecifika assets/LOD → visuell granskning → runtimebenchmark → gås och flygning. Se [GAPS](GAPS.md) för acceptanskriterier och verkliga återstående implementationer.
