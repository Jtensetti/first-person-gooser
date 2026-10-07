# Källor, villkor och attribution

Projektkod, rådata, härledda data, modeller, fotografier och material har skilda rättigheter. En källas publika API eller en teknisk byggning ger inte automatiskt rätt till vidarepublicering. Se [SOURCES](docs/SOURCES.md) för verifieringsdatum och primärkällor.

- **NBS-underlag:** återanvändning inom samma ägares projekt från `Jtensetti/nbs-sandbox-trelleborg@8263aa2f583170fc3a6a6bf6f3f174a7c8ac4322`. Relevanta råfiler och upstreamskript förs över lokalt med checksumma; privata molninställningar, tokens och miljöfiler kopieras inte.
- **NMD 2023 v2.1:** Naturvårdsverket, CC0 enligt produktbeskrivningen. Källnamn/version och klasskoder bevaras även när attribution inte är obligatorisk.
- **OpenStreetMap:** © OpenStreetMap contributors, [ODbL 1.0](https://www.openstreetmap.org/copyright). Attribution och tillämpliga databasvillkor måste följa med en publicerad distribution. OSM-fallback hålls spårbar.
- **AlphaEarth, när exporten används:** CC BY 4.0. “The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind.” Ange även källa och bearbetning. Datat används för semantik, inte exakta objekthöjder.
- **Sentinel-2:** Copernicus Sentinel-data under tillämpliga öppna villkor; ange ESA/EU/Copernicus och observationstid vid användning. Bearbetade index är inte originalortofoto.
- **SRTM-preview:** NASA/USGS SRTMGL1_003, år 2000, EGM96. Omprojekterad ythöjd; ingen uppmätt RH2000-terräng.
- **Lantmäteriet via Mapterhorn:** pilotens 1 m DTM hämtas från Mapterhorns öppna källarkiv, CC0 enligt arkiverad metadata och medföljande licens. Dessa sparas med rasterfilen. [Källkontroll och begränsningar](docs/OPEN-DATA-2026-10-07.md).
- **Lantmäteriet, andra produkter:** filprodukternas aktuella GeoTorget-villkor och användarens behörighet ska dokumenteras separat. CC BY-status för STAC-metadata får inte överföras till alla tillhörande filprodukter utan kontroll. Skyddade filprodukter har inte hämtats här.
- **Trelleborgs kommun:** dokumenterad återanvändningsrätt inväntas för footprints, multipatch, markmodell och ortofoto. Hämtbarhet är inte licensbevis.
- **Jordbruksverket:** offentlig WFS används för lokal pilotberedning enligt publicerad tjänst/öppna-data-information. Exakt återdistributionslicens för skiften är inte fastställd i denna leverans. Råpolygonerna finns inte i det offentliga Git-repot.
- **Skogsstyrelsen, Trafikverket, SMHI, SCB, RAÄ, JRC och Copernicus DEM:** utvärderade källor; varje faktiskt införd produkt behöver egen metadata/attribution. Ingen generell licens antas för alla deras produkter.
- **Procedurala Blender-prototyper:** egen enkel kodgenererad geometri, inte tredjepartsmodeller eller bokillustrationer. Ersättningsassets måste registreras med användnings-/distributionsrätt.

Tillämplig attribution ska kunna nås diskret via exempelvis eftertexter eller en informationssida. Inga analyslager eller provenancepaneler ska ligga över den egentliga flygupplevelsen. Referensbilden används som brief och har inte kopierats in i publicerade assets.
