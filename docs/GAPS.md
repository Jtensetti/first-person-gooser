# Gap och acceptans

**Senaste uppdateringen:** [öppen 1 m DTM är hämtad och använd](OPEN-DATA-2026-10-07.md). Sentinel-2 ger markfärg; 212 modellerade sadeltak förbättrar siluetten. Verkliga tak, LiDAR och högupplöst ortofoto saknas fortfarande.

Uppdatering 2026-10-07: ortofotoimport med metrisk UV och hashkontroll är implementerad och syntetiskt testad; riktiga godkända bilder och oberoende visuell validering saknas fortfarande. OSM-kust är nu importerad, topologiskt kontrollerad och renderad. Aktuella NVDB-data ska i första hand sökas via Datautbytesportalen. Se [leveransen](DELIVERY-2026-10-07.md), [kustuppdateringen](COAST-2026-10-07.md) och [källkontrollen](SOURCE-UPDATE-2026-10-07.md).

Prioriteringen är geografi → skala/höjd → siluetter → vegetation/mark → material → mikrodetaljer → flygning. En lyckad build är aldrig samma sak som godkänd rekonstruktion.

| Prioritet | Gap | Nästa konkreta åtgärd | Acceptans / begränsning |
|---|---|---|---|
| P0 | Klassad LiDAR och oberoende DTM-kontroll saknas | 1 m RH2000-DTM är hämtad via Mapterhorn; fortsätt med laserkälla och oberoende kontroll | Markmodell finns; mätår och absolut noggrannhet är ännu inte verifierade |
| P0 | Kommunala användningsvillkor saknas | Bekräfta footprints, 3D, ortofoto, markmodell och tillåten vidareleverans | Dokumenterad rätt för respektive källa, inte en tom copyright-rad |
| P0 | Exakt SJV-licens för offentlig vidareleverans oklar | Kontrollera produktspecifik metadata/medgivande | Ingen rå-/härledd offentlig dataleverans innan detta är klart |
| P1 | Riktiga tak saknas | Prioritera kommunal multipatch-import om licens/Z är klara; annars flerplans-LiDAR | Jämför taknock/takfot och siluetter; flat previewvolym räcker inte |
| P1 | OSM-kust saknar oberoende lägeskontroll och vattennivå | Jämför mot officiella vatten-/landpolygoner och ortofoto; fastställ kajer och vattennivå | Topologi passerar; lägesnoggrannhet och vertikal anslutning är inte godkända |
| P1 | Vägbredd/klass från officiell källa saknas | NVDB via Datautbytesportalen eller licensierad kommunal vägyta | Rätt sträckning, bredd, bro-/tunnelnivå; körfält/trottoarer där attribut finns |
| P1 | NMD är för grovt för enskilda träd och häckar | LiDAR + Skogsstyrelsen/NMD-tillägg + tillåtet ortofoto | Skogsbryn och lokala kronhöjder, rimlig täthet; ingen påstådd inventering av varje träd |
| P2 | Grödhöjd och utvecklingsstadium modellerade | Års-/säsongsdata, NDVI och transparent modell; artassets | Verifierad grödkategori per skifte, inga växter i hus/väg/vatten, rimlig närbild |
| P2 | Riktigt ortofoto och materialbakning saknas | Anslut godkänd RGB-bild/år till färdig import; utvärdera skuggor och bake | Matcha ortofoto utan dubbla byggnader/skuggor; inga satellitpixlar presenterade som ortofoto |
| P2 | Assets är ursprungliga teknikprototyper | Licensierade skånska träd, gräs, grödor och buskar, med tre LOD | Närbild på faktisk vegetation, kvalitet på siluett/material, mät minne och instansbudget |
| P2 | Blandade terräng-LOD kan spricka | Implementera kantstitchning/skirt efter vald runtime | Inga glipor vid LOD-byte; nu är bara samma LOD:s delade höjd verifierad |
| P2 | Runtime är inte benchmarkad | Jämför GLB-instancing/Three.js WebGL2/WebGPU och 3D Tiles | Dokumenterade enheter, P50/P95 frametime, streaming och minne; inga FPS-löften ännu |
| P3 | Ingen gås/flygupplevelse | Bygg efter att pilotvärlden godkänts | Mjuk segelflygning, ryggkamera, vind och originell gåsgestalt |
| P3 | Ingen kommunomfattande produktion | Schemalagda små jobb, manifest och objektlagring | Samma generator fungerar på flera representativa rutor innan full batch |

## Systematisk kontroll inför godkännande

1. **CRS/skaltest:** kontrollpunkter i minst tre spridda lägen, avstånd i meter och dokumenterat höjddatum. Fastställ toleranser från respektive källas kvalitet; nyckeltalet 0,1 m i en produktmetadata är inte en egen mätning.
2. **Makrogeometri:** överlagra footprints, vägar, skiften och kust mot godkänt ortofoto/kartdata. Kontrollera även hela byggnader på tilegränser och polygonhål.
3. **Vertikal kontroll:** jämför DTM mot klassade markpunkter; rapportera median/P95-residual och täckningsgrad. Separera kontrollpunkter från anpassningspunkter. Tak med otillräckligt stöd får ingen uppmätt etikett.
4. **Vegetation:** kontrollera skogsbryn, fördelning av höjd/kronstorlek samt sådd/skörd i vald säsong. Avslöja modellbrister genom generatorjustering, inte handplacerade undantag i piloten.
5. **Visuell kontroll:** fasta kameror på cirka 20, 80 och 250 m över mark, både närbild och horisont, jämför mot lagligen tillgängliga referenser. Beakta skuggor och tidsförskjutning mellan källor.
6. **Runtime:** reproducibelt kameraspår med kall/varm cache, tile-/LOD-byte och stressad instansmängd. Tid för Python eller offline-Cycles är inte realtids-FPS.

Implementerat nu: struktur-, hash-, CRS-, nodata-, polygon-, paginerings-, kustklippnings- och determinismtester. **Inte genomfört:** oberoende ortofoto-/LiDAR-validering, numerisk mätning av verklig geografisk residual, äkta takrekonstruktion eller spelbar browserbenchmark.
