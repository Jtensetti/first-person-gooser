# Pilot: Smygehuk och västra Smygehamn

En verklig kvadrat på **1 000 × 1 000 meter**:

| Egenskap | Värde |
|---|---|
| SWEREF99 TM, EPSG:3006 | E 395500–396500, N 6133500–6134500 |
| Sydvästra hörnet, lon/lat | 13.3524784364, 55.3367358842 |
| Nordöstra hörnet, lon/lat | 13.3678676622, 55.3459296327 |
| Första indelning | 4 × 500 m tiles |
| Terräng-LOD | 2, 4 och 10 m vertexavstånd |
| Databuffert | 30 m; ökas när stora korsande objekt behöver större stöd |
| Jordbruksår | 2025 |
| Gestaltningsdatum | 2025-07-15, sommarscen; inte historiskt väderbevis |

Området förenar kust/hamnmiljö, bostäder, väg 9, åker-/betesmark och trädbestånd. Det är lättare att kontrollera siluetter och övergångar här än i en homogen ruta. Den slutliga kvaliteten ska bedömas mot korrekt ortofoto och LiDAR, inte mot referensbildens exakta komposition.

Verifierade pilotfynd 2026-10-06:

- Jordbruksverkets 2025-tjänst returnerar **10 skiften** för den obuffrade urvalsboxen och **12** med 30 m hämtbuffert. Urvalet är en bbox-intersektion: polygoner som fortsätter utanför rutan bevaras.
- Det buffrade urvalets huvudkoder: 50 × 4, 52 × 2, 318 × 2, samt 2, 45, 46 och 20 en vardera. Kategorierna har verifierats mot rätt års kodtabell. Kod 318 behandlas som blommande blandning, inte raps. Artsort, skördedatum och höjd kan inte avläsas ur huvudkoden.
- OSM-kompletteringen innehåller 281 byggnadspolygoner, 154 väg-/gångvägsobjekt och 3 vattenpolygoner i utdraget. **255** byggnadsvolymer ägs av de fyra pilottiles som faktiskt byggdes. Räknarna betyder inte att kommunens byggnadsinventering är komplett.
- Kommunens `TreD/Byggnader_3D_250407/FeatureServer/0` ger **667 multipatch-features** i pilotfrågan. Dessa är inte nödvändigtvis 667 byggnader; byggnadsdelar och LOD behöver sorteras. Återanvändningsrätten och Z-referensen måste bekräftas före import.
- LM:s aktuella STAC anger 1 m markmodell och COPC-punktmoln med insamlingsintervall 14–19 februari 2025 för den större leveransrutan. Det är metadata, inte en egen kvalitetsmätning av pilotområdet.

Åkrar klipps mot tilegränser för byggandet, medan oförändrad källpolygon finns kvar i insatsdata. Växter maskas bort från byggnader, vägkorridorer och vatten. Motstridiga årgångar blir därmed synliga i QA i stället för växter genom hus.

Pilotgränsen är ett arbetsurval, inte en ny geografisk källa. Ingen illustration används för att bestämma var hamnen, vägarna eller åkrarna ligger.
