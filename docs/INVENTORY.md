# Inventering av NBS-repot

Inventerad revision: `Jtensetti/nbs-sandbox-trelleborg@8263aa2f583170fc3a6a6bf6f3f174a7c8ac4322` (2026-10-06).

Hela Git-trädet rekonstruerades och stämdes av: **1 031 filer, 0 saknade**. Alla filer har storlek och SHA-256 i [repository-files.csv](evidence/inventory/repository-files.csv). Samtliga 810 indexerade rasterfiler öppnades, georeferering och band-1-värden granskades: [sammanfattning](evidence/inventory/repository-audit.json), [rasterförteckning](evidence/inventory/raster-files.json). PCA-containrarnas bandinventering finns i rapporten; statistikens min/max gäller det första TIFF-bandet, inte alla komponenter. Detta är en fullständig maskinell filinventering med fördjupad granskning av geodataflödena, inte ett påstående om manuell läsning av varje UI-komponent.

## Faktiska fynd

- **750 filer med ändelsen `.tif` är ZIP-filer**, ofta med ett TIFF per band. Bara de 60 nya kommunala NMD-/lutningsfilerna är direkta GeoTIFF. Importören känner igen innehållet i stället för att lita på filändelsen.
- Legacy-lagren är geografiska raster med ungefär **17 × 30 m** cellstorlek vid Trelleborg. Ett filnamn med `10m` eller en skärmzoom gör inte den levererade datan till 10-metersdata.
- Legacyutbredningen `[13.0,55.25,13.5,55.5]` saknar norra kommundelar. De nya kommunala rastren använder `[12.95,55.10,13.55,55.55]` och täcker även havsdelen.
- Totalt är rasterfilerna 11 464 418 byte. Kompaktheten beror bland annat på grov upplösning och kompression; det är inte ett komplett högupplöst 3D-underlag.
- Höjdvärden, NDVI och temperatur får inte tolkas utan enhet/skalfaktor/nodata. Canopy och jordkol har värdet 255; vattenfrekvens har −128; NDVI når 7 280 och LST 14 376.23. Dessa råtal får inte direkt bli vegetationshöjd, NDVI eller grader Celsius.
- Ingen levererad originalkub med 64 AlphaEarth-band finns i de 17 rasterindexen. `pca_3band` är ingen satellitbild eller ortofoto.

## Bedömning per lagerfamilj

| Lager | Filer | Ursprung / lämplighet | Beslut för GÅSEN |
|---|---:|---|---|
| `nmd2023_landcover` | 30 | NMD2023 v2.1, 10 m, bevarade klasskoder | Återanvänd som semantiskt basskikt; inte objektkonturer |
| `elevation` | 50 | SRTM, cirka 30 m, år 2000, EGM96 | Endast explicit teknisk preview; ersätt med LM DTM |
| `canopy_height` | 50 | Namn pekar på ETH 2020 10 m; leverans grövre, 255 behöver utredas | Karantän tills enheter/nodata verifierats; LM prioriteras |
| `biomass` | 50 | Grov leverans; biomassaprodukt är ingen krongeometri | Utvärdera senare för beståndstäthet |
| `pca_3band` | 50 | 3 separata TIFF i ZIP, ofullständig bake-proveniens | Arkivera; ny verifierad AE-export om semantik behövs |
| `ndvi` | 50 | Råskalning och bakning måste fastställas | Ny säsongsbestämd Sentinel-2-export |
| `water_freq` | 50 | JRC-liknande frekvensprodukt, 30 m-källa | Kontrollunderlag; ingen kustgräns |
| `municipal_slope` | 30 | Härledd från Copernicus DSM GLO-30 | Återanvänd som kontroll; aldrig som DTM |
| `slope` | 50 | Legacy-SRTM-lutning | Behövs inte när DTM finns |
| `landcover` | 50 | CORINE 2018, källupplösning 100 m | Ersätt med befintlig NMD |
| `builtup` | 50 | GHSL-klasser/historik 1975–2014 | Inte footprints eller tak; utelämna |
| `hand` | 50 | Relativ höjd mot dränering | Inte markhöjd; utelämna ur geometri |
| `lst` | 50 | MODIS råvärden och temperaturstatistik | Ingen tydlig första visuell nytta |
| `soc` | 50 | Jordkol, råvärden/skalfaktorer | Ingen första visuell nytta |
| `nightlights` | 50 | Grov radians | Inte placering av gatlyktor |
| `population` | 50 | Befolkningsraster | Ingen första visuell nytta |
| `precipitation` | 50 | Ofullständig proveniens/enheter | Karantän; SMHI vid senare behov |

## Återanvändning av kod och gränser

| Befintlig del | Fortsättning |
|---|---|
| `scripts/prepare-municipal-rasters.py` | Bevara källadresser, NMD-koder och selektiv ZIP-hämtning. Hämta inte om hela NMD-arkivet för en kilometer |
| `scripts/prepare-municipal-boundary.py` | Bevara avgränsningsflödet och dess källor |
| `src/lib/geo/municipality-boundary.json` | Återanvänd statistisk kommunavgränsning; inte fastighetsgräns eller exakt strandlinje |
| `public/data/municipal_sources.json` | Bevara NMD-version, SHA, källupplösning och klasslista |
| Rasterindex och bbox-konvention | Läs befintliga index och flytta bara relevanta, godkända filer |
| Kommunal byggnadshämtning | Återanvänd principen ID-uppräkning + verifierade batcher; native EPSG:3008, uttrycklig reprojektion |
| `bake/bake_ee.py` | Anpassat exportmönster i `scripts/fetch_satellite.py`; separata, oförändrade upstreamfiler sparas lokalt vid överföring |
| Webbapp, GIS-paneler, Supabase och AI-funktioner | Ingen kopiering till flygupplevelsen; irrelevant infrastruktur följer inte med |

Kommunbyggnaderna är ett live-lager, inte en fullständig levererad byggnadsdatabas. STATUS 1 och 4 filtreras bort i den återanvända hämtningen. API-svar verifierar hämtning, inte att alla verkliga byggnader finns.

Kommungränsen kommer från sammanslagna SCB RegSO 2025-områden, inklusive havsutbredning. Pilotkontrollen använder denna avgränsning, men ytornas geometri kommer från respektive källa.

Ett konkret fel i den befintliga Earth Engine-baken är collection-ID:t `GOOGLE/SATELLITE/EMBEDDING/V1/ANNUAL`. Det officiella ID:t är `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`. Dokumentationens `--year` matchar inte originalskriptets `--years`. Det nya skriptet rättar sin egen implementation; ursprungsrepot ändras inte.

Överföringsplanen låser filhashar mot inventeringen och kräver rätt källrevision. Den tar inte med miljöfiler, autentisering eller molnkonfiguration. Originalskript sparas under `data/.../nbs/upstream/` för spårbar återanvändning.
