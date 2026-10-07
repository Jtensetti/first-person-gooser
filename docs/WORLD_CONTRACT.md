# Utomhuskontrakt: GÅSEN

Build 3D Game Rooms används som kvalitetsstöd för skala, siluett, kameraupplevelse och spårbara assets. Detta är ett öppet geografiskt landskap, inte ett rum med dekorativa väggar, symmetri eller dörrschema. Makrogeometri kommer från källdata. Game Development Studios lokala `game-dev` saknades på denna dator; ingen provider, assetmarknad eller betald Meshy-körning används.

- **Syfte:** uppleva en verklig plats genom lugn segelflygning.
- **Huvudmotiv:** Trelleborgs landskap. Originalgås och fjädrar är närförgrund, med FPS-liknande kameraskala. Den senaste användarinstruktionen om ryggkamera gäller före äldre diskussion om följkamera.
- **Produktionskamera:** förstaperson på ryggen, mjuk banking, liten rörelse. Exakt objektstorlek/FOV väljs i senare kameraexperiment; aktuell kontrollkamera är inte flygkameran.
- **Rörelse/avgränsning:** framtida terrängkollision och flygbar höjd över mark. Ingen rörelse ut i oladdade tiles utan kontrollerad reserv. Det här leveranssteget innehåller ingen styrning.
- **UI:** ingen GIS-panel, klassning, proveniens, uppdrag eller poäng i flygvyn. Intern evidens finns i datakontrakt och QA.
- **Tillgångar:** enheter meter, markkontakt, korrekt framaxel, hash, licens, källa, versionslåsta LOD. För vegetation används instanser; ingen realisering till miljontals separata meshobjekt.
- **Kvalitetsordning:** geografi, skala/höjd, siluetter, vegetation/mark, material, mikrodetaljer, flygning.
- **Budget nu:** fyra 500 m-tiles, högst 150 000 terrängtrianglar per tile/LOD och 15 000 tekniska växtinstanser per tile. Detta är authoring-budget, inte ett FPS-löfte.
- **Godkännande:** tekniktester bevisar inte fotorealism. Function/Form/Runtime står fortfarande som inte granskade av människa. Exporterna är tekniska testartefakter inom det uttryckliga pipelineuppdraget, ingen publicerad spelvärld.

Granskning efter dataåtkomst ska omfatta översikt och kameror vid 20/80/250 m över mark samt frysta närbilder på kust, tak, väg och grödor. Fel rättas i generatorn. Betalda assets och slutlig runtimepublicering ingår inte i denna tekniska leverans.
