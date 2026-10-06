# Genomförd verifiering, 2026-10-06

Detta är resultat från exekverad kod, inte planerade kontroller. Mätningen gäller den dokumenterade tekniska previewn; inga resultat från saknad LM-data eller oberoende ortofoto påstås.

## Resultat

- 1 031 källfiler och 810 raster auditade, inga oläsbara indexerade raster.
- **19 automatiserade tester passerade**. CRS/axelordning, halvcellsförskjutning, ZIP-TIFF, nodata, klassraster, polygonhål, multipatch-avvisning, deterministiska instanser, LiDAR-stöd, komplett paginering, källhashar/licensstatus, årsblandning och end-to-end-byggning ingår.
- Lint och formatering kontrollerade för Python/Blender/scripts/tests. CI gör samma geometritester utan nätåtkomst till datakällor.
- Faktiska SJV-2025-skiften, NMD, SRTM-preview och uttrycklig OSM-komplettering byggdes till **4 tiles**, tre terräng-LOD, **255 byggnadsvolymer**, **8 765 växtinstanser**. 167 vägdelar, 13 skiftesdelar och 6 vattendelar är tilefragment, inte unika källobjekt.
- Strukturell QA passerade: checksummor, ändliga koordinater, faceindex, gemensamma LOD0-kanter och instansbudget.
- **Blender 4.5.3 LTS** kördes headless, skapade `.blend`, fyra LOD0-GLB, separata instanslistor, nio växtprototyper och en 1280×720 Cycles-kontrollrendering.
- Renderingen inspekterades. Ett faktiskt coplanärt överlapp i havet hittades och rättades genom polygonklippning av terrängen. Regressionstestet kontrollerar att landmesh och vatten inte överlappar i yta.
- Lokal handoff-ZIP skapades och integritetskontrollerades; filer verifieras dessutom med SHA-256. Ingen rådatabundle publicerades.

Den granskade renderingen visar fortfarande grov NMD-strandlinje, generiska plana tak, enkla växtprototyper och procedurala markfärger. Den är ett kontrollresultat, inte referensbildens fotorealism. Inga ortofoton, autentiserade LM-filer eller kommunala råbyggnader har smugit sig in i previewn.

## Tilebenchmark

Samma 1 km²-urval, gemensamma terrängsteg 2/10 m, identiska källfiler. Siffrorna är en enstaka körning på en delad Linux-arbetsmiljö; annan samtidig aktivitet förekom. Tider är observationsvärden, inte stabila hastighetsjämförelser eller förväntade tider på användarens dator. Antalet nära växtkluster ändras med tileindelningen, så total instansmängd är inte exakt konstant.

| Tile | Antal | Pythonförbehandling | Komprimerade tilepaket | Största LOD0-tile, trianglar |
|---|---:|---:|---:|---:|
| 250 m | 16 | 10.541 s | 5,296,674 byte | 33,215 |
| 500 m | 4 | 11.616 s | 4,431,432 byte | 131,289 |
| 1000 m | 1 | 9.045 s | 3,888,688 byte | 444,296 |

500 m behålls som första arbetsval för måttlig tilemängd och per-tile-geometri. 250 m ger mindre enheter för culling; 1 km ger större enskilda GPU-/streamingenheter. Inget val av Three.js, WebGPU eller 3D Tiles låses utifrån dessa CPU-siffror.

Blenders rapporterade tid för scenbyggning, export och kontrollrendering var **10.51 s** i denna miljö. Det är inte realtids-FPS. GLB exporterades med Blender; full extern glTF-validator och import i mål-runtime återstår.

## Reproduktion

```bash
pytest -q
ruff check src blender scripts tests
ruff format --check src blender scripts tests
goosen qa --world build/pilot
goosen benchmark --catalog data/pilot/catalog.json --output build/benchmark --preview
```

För exakt återkörning på Linux/Python 3.12 finns `constraints-tested-py312.txt`: installera med `python -m pip install -c constraints-tested-py312.txt -e '.[dev]'`. Det är ett versionsögonblick, inte ett plattformsoberoende lås. Miljöversionerna finns även i `evidence/environment.json`.

Fryst lokal katalog ger identiska tilechecksummor med samma verktygsversioner, konfiguration och källfiler. Ny hämtning från ett live-API kan ge ny data och ett nytt resultat. Därför sparas hämtningstid, källhash och handoffmanifest.

[Maskinrapporter](evidence/) innehåller källinventering, tilemanifestets kontrollvärden, QA, Blender-rapport och benchmark. Endast tekniska räknare/checksummor publiceras; de osäkert licensierade råpolygonerna och den härledda kontrollrenderingen stannar utanför det offentliga repot.

Återstår att köra med verklig LM-höjd, verifiera multipatch och ortofoto, jämföra oberoende höjdresidualer samt benchmarka en riktig runtime. Ingen automatisk testresultatrad markerar fotografisk/geografisk slutacceptans.
