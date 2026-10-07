# Smygehuk – fördjupad miljö, 7 oktober 2026

Pilotområdet är fortfarande 1 × 1 km, uppdelat i fyra 500-metersrutor i SWEREF99 TM/RH2000. Detta är en förbättrad, reproducerbar miljö, inte godkänd fotorealism eller hela Trelleborgs kommun.

## Geometri som nu kommer från lasern

Alla 281 footprints i indata inklusive buffert analyseras. 170 klarar en ny robust tvåplansmodell för sadeltak; 12 klarar den tidigare enkelplansmodellen. Nockläge, lutning och höjd anpassas till verkliga punkter. Footprintens riktningar begränsar sökningen. Minst 85 % av punkterna ska ligga inom 35 cm från modellen, minst 80 % av en undanhållen femtedel ska också klara gränsen och inlier-RMSE ska vara högst 20 cm. Båda taksidorna behöver rumsligt stöd. Det är en intern konsistenskontroll, inte oberoende verifiering mot foto.

**255 byggnader berör själva pilotrutan och byggs i scenen:** 163 tvåplanstak, 10 enkelplanstak, 41 modellerade sadeltak och 41 förenklade volymer med olöst tak. Skillnaden mot 281 beror på bufferten. Höjd har fortfarande härletts för 265 byggnader i hela indata.

Komplexa tak, valmade tak, skorstenar och små tillbyggnader rekonstrueras inte tillförlitligt ännu. Unclassified laserpunkter kan innehålla vegetation. Godkänd matematisk anpassning är inte bevis på byggnadens identitet.

## Vegetation, mark och material

- 5 427 vegetationskandidater härleds från lasern med höjdvariation, grannstöd och avstånd mellan toppar. Byggnader, vägar, vatten och jordbruksskiften undantas. Kandidaterna är inte en verifierad trädräkning; höjd/centrum är härledda och art/krona modellerade.
- En karterad OSM-häck ger ytterligare 49 modellerade växtinstanser längs sin linje. Totalt 5 476 träd-/häckinstanser och 12 585 grödklungor: **18 061 instanser**. Klungorna använder delad geometri via Geometry Nodes.
- Grödor följer SJV:s polygoner och kodtabell 2025. Cirkelformade previewfläckar har ersatts av klungor över polygonernas inre. Kategori kommer från koden; plantform, höjd och utvecklingsstadium är fortfarande modellerade. 4,5 m klungavstånd är en förhandsvisningsoptimering, inte jordbrukets faktiska plantavstånd.
- 32 kompletterande OSM-objekt har hämtats. 27 ytpolygoner används, plus häcken. Övriga objekt saknar tillämplig generator eller ligger utanför använd yta. Tre öppna icke-häcklinjer avvisas i importen och sluts inte godtyckligt.
- Gångstigar, servicevägar och större vägar får olika modellerade standardbredder där mått saknas. Kända ytmaterial prioriteras. Huvudvägen får modellerad mittlinje. Det finns ingen oberoende verifiering av markeringarnas utförande.
- Takpaletten domineras av grått/kolgrått och kompletteras av dämpat tegel/brunt. Originalgenererade, upprepningsbara 512-pixelstexturer ger färg och normaler för tak, tegel och puts. Materialtilldelning är deterministisk men inte uppmätt per hus. Fönster, entrépaneler och 10 cm taktjocklek är modellerade.
- Strandens fyra meter breda materialzon på landsidan är en modellerad detalj längs kustlinjen. Den är inte en uppmätt strandklassificering. Havsnivån är fortsatt modellerad nollnivå.
- Användarens referensbilder är inte inlagda som texturer, digitaliserade byggnadsdata eller filer i Git. Materialen är egen procedurgenerering.

## Körning

```powershell
python scripts/fetch_context.py --config configs/pilot-open.json --catalog data/pilot/catalog-laser.json --output data/pilot/catalog-environment.json
python -m goosen.cli prepare --config configs/pilot-open.json --catalog data/pilot/catalog-environment.json --output build/environment --preview
python -m goosen.cli qa --world build/environment
& 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe' -b --factory-startup --python-exit-code 1 -P blender/build_world.py -- --world build/environment --output build/environment-blender --allow-preview --isolate-scene --export-glb --render
& 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe' -b build/environment-blender/goosen-pilot.blend --python-exit-code 1 -P blender/review_views.py -- build/environment-blender
```

Använd det frysta katalogpaketet vid återuppbyggnad; hämta inte OSM igen om du vill ha identiska data. `--isolate-scene` döljer befintliga objekt utanför GOOSEN utan att radera dem, så att Blender-startkub och standardljus inte följer med i kontrollrenderingen. Utan flaggan påverkas inte objekt utanför projektkollektionen.

## Verifiering och praktiska gränser

60 tester passerar. Tester omfattar bland annat roterade tak med känd nock, brus, vegetation/plan/sparsitet som ska avvisas, byggnadshål, vegetationsuteslutning, markytor vid byggnad/vatten, smala gångvägar och GLB-rensning. Ruff passerar. Korsande vägpolygoner delas i ytor utan överlapp, med större vägklass först; ett test verifierar både noll överlapp och bevarad total vägyta. Ett regressionstest med sadelformad terräng kontrollerar att hela marktrianglar, även vid klippta kanter och hål, ligger exakt 3 cm över terrängens faktiska trianglar. Markytor, vägar och åkrar använder nu samma triangulering som LOD0-terrängen; bilinjär interpolation och oberoende grova ytor gav tidigare genomskärningar. Ytskikten behöver motsvarande LOD-anpassning innan en runtime växlar terräng-LOD.

Blender 5.2.2 LTS bygger och renderar scenen. Alla fem GLB-filer passerar Khronos-validatorn med noll fel och noll varningar. Normalmappade material får exporterade tangenter; onödiga tangentattribut på andra material tas bort, vilket undviker exportörens nolltangenter vid mycket små kusttrianglar. Binär geometri och nödvändiga normalmapptangenter bevaras. GLB behåller färg-/normaltexturer för byggnader; vissa procedurmaterial för mark och vatten återges enklare än i Blender. Instanser levereras separat och ska inte realiseras till miljontals unika meshobjekt.

Återställning av 45 datafiler i en ny mapp och ombyggnad ger identiska hashvärden för samtliga fyra tilepaket och fyra marktexturer. Bilder och material är packade i Blenderfilen. Rådata eller exakt härledd lasergeometri har inte publicerats i GitHub.

**Återstående visuellt hinder:** markbilden är fortfarande Sentinel-2 på 10 m. Trädgårdar, uppfarter och mark nära kameran kan därför inte få verkligt fotograferad detalj. Vi inväntar beviljad ortofotoåtkomst. Fasader, färger per hus, komplexa tak, lokala trädarter, årstidsmodell och vatten behöver vidare kontroll. Ingen runtimeprestanda eller fotorealistisk acceptans har påståtts.

Källor: [laserpost](https://api.lantmateriet.se/stac-hojd/v1/collections/dsm-skoglig-copc/items/25a001-613_39), [OSM:s licens](https://www.openstreetmap.org/copyright), [Overpass-frågespråk](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL). Tidigare källor och inventering finns i projektets övriga dokumentation.
