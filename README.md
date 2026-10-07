# GÅSEN — Trelleborg på riktigt

**Laseruppdatering 2026-10-07:** verklig laserdata är importerad. 265 byggnadshöjder härleds, 12 tak klarar enkelplansanpassning och vegetation får lokala höjdprover. [Resultat och begränsningar](docs/LASER-2026-10-07.md). Äldre statusnoteringar nedan beskriver tidigare lägen.

En reproducerbar **geodata → Blender → tile**-pipeline för en framtida flygupplevelse från en gåsrygg. Verkliga data bestämmer makrogeometrin; procedurgenerering tillför detaljer. Ingen GIS-panel byggs in i upplevelsen.

**Öppna data 2026-10-07:** piloten använder nu **1 m markmodell i RH2000**, hämtad utan konto från Mapterhorns Lantmäteriet-arkiv, samt Sentinel-2 RGB för markfärg. 212 enkla byggnader har modellerade sadeltak. Scenen är öppnad och sparad i Blender 5.2.2 med materialvisning. [Aktuellt resultat och ombyggnad](docs/OPEN-DATA-2026-10-07.md). 47 tester passerar. Äldre leveransnoteringar nedan beskriver tidigare underlag.

**Leverans 2026-10-06:** inventering av hela NBS-repot, kontrollerade källor, vald kilometer vid Smygehuk, fungerande Python-pipeline, Blender-byggare, Geometry Nodes-instancing, tre terräng-LOD, GLB-export och överföringsverktyg. Kedjan har körts med riktiga pilotpolygoner och raster i Blender 4.5.3 LTS. Detta är en verifierad teknisk grund, **inte en färdig fotorealistisk värld**. Lantmäteriets skyddade originaldata och kommunens återanvändningsvillkor återstår.

**Uppdatering 2026-10-07:** kedjan är nu körd i Windows/Python 3.13 och Blender **5.2.2 LTS**. Windows-hashfel är rättat, säker datapaketsåterställning och ortofotoimport är implementerade, och offline-ombyggnad ger identiska tilehashar. Se [aktuell leverans och körguide](docs/DELIVERY-2026-10-07.md). [Tidigare körguide](docs/TOMORROW.md) finns kvar som bakgrund.

**Miljön först:** [kustuppdateringen](docs/COAST-2026-10-07.md) ersätter NMD:s grova havskant med en fryst OSM-kustlinje för piloten. Havspolygonen omprövas mot råkällan vid varje bygge; saknade segment och motsägande riktningar stoppas. UI, gås och flygning väntar tills miljön håller rätt kvalitet.

## Kör en första värld

Python 3.11–3.13 och Git behövs. Blender 4.5+ används separat; inga GIS-paket behöver installeras i Blender.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
python scripts/prepare_tomorrow.py --source ../nbs-goosen-pinned --job pilot --osm --blender /full/path/to/blender
```

Om källmappen saknas klonas det privata källrepot med din befintliga Git-behörighet och låses till den inventerade revisionen. Ett befintligt checkout ändras aldrig automatiskt. Utan Blender på datorn blir geodatapaketet klart för senare import. Saknad privat Git-behörighet behöver lösas lokalt. Inga lösenord läggs i kommandofilerna.

`--osm` väljer uttryckligen OSM som tillfällig kompletteringskälla. Kommunala footprints ersätter den rollen när användningsrätten är klar. Standardbyggaren använder för närvarande tekniska preview-assets; `--preview` ger **inte** tillstånd att använda data med oklar användningsrätt.

## Det som finns

- Full filförteckning med SHA-256 för **1 031 källfiler**; audit av **810 rasterfiler / 17 lagerfamiljer**.
- Kontrollerad återanvändning av NMD 2023, kommunavgränsning och befintlig tileinfrastruktur.
- WFS-hämtning av årsbestämda skiften/block, ArcGIS-hämtning med verifierade ID-batcher, LM STAC-discovery och behörighetsstyrd filhämtning.
- Lokala meter i Blender från SWEREF99 TM; explicita höjddatum; inga tysta Z-konverteringar.
- Terräng, byggnadsvolymer med riktiga footprints, draperade vägar, vattenpolygoner, riktiga skiftesgränser och instanser. Korsande byggnader har en ägare och klipps inte till falska fasader.
- Fristående rådata, SHA-låsta kataloger och lokal överföringsfil. Ingen rå LiDAR i Blender eller Git.
- Testad Blender-scen och GLB per tile, plus separata instanslistor och återanvändbara växtprototyper.

## Läs vidare

| Dokument | Innehåll |
|---|---|
| [TOMORROW](docs/TOMORROW.md) | Installation, körning, överföring och exakt åtkomst som behövs |
| [INVENTORY](docs/INVENTORY.md) | Vad som finns i ursprungsrepot och vad som kan återanvändas |
| [SOURCES](docs/SOURCES.md) | Verifierade externa källor, licenser, aktualitet och begränsningar |
| [PILOT](docs/PILOT.md) | Den valda kilometern och faktiska datafynd |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Koordinater, kontrakt, prioriteringar, Blender och runtime |
| [GAPS](docs/GAPS.md) | Vad som återstår innan världen kan godkännas |
| [VALIDATION](docs/VALIDATION.md) | Utförda tester, rendering och benchmarkens gränser |
| [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) | Datavillkor och attribution |

Ingen färdig gås, flygkontroll, webbruntime eller kommunomfattande rekonstruktion påstås vara levererad. Referensbilden styr känslan; verklig geografi styr placeringar, avstånd och siluetter.
