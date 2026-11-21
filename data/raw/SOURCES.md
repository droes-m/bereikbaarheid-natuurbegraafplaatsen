# Bronnenregistratie (`data/raw`)

## 1. Natuurbegraafplaatsen (ANB Belevingskaart — laag 55)

- **Bron:** Agentschap voor Natuur en Bos (ANB) — Belevingskaart (`?showlayerid=55`, laag `55` *Natuurbegraafplek* onder `300` *Voorzieningen*)
- **Webkaart:** https://belevingskaart.natuurenbos.be/?showlayerid=55
- **ArcGIS REST metadata:** https://gis-extern.natuurenbos.be/arcgis/rest/services/Belevingssite/Belevingssite/MapServer/55?f=pjson
- **Reproduceerbare query (WGS 84):** https://gis-extern.natuurenbos.be/arcgis/rest/services/Belevingssite/Belevingssite/MapServer/55/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=pjson
- **Reproduceerbare query (Lambert 72):** https://gis-extern.natuurenbos.be/arcgis/rest/services/Belevingssite/Belevingssite/MapServer/55/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=31370&f=pjson
- **Opgehaald op:** 2026-11-21
- **Aantal records:** 19 (`exceededTransferLimit: false`)
- **Geometrietype:** `esriGeometryPoint`
- **Origineel CRS:** `EPSG:31370` (Belge 1972 / Belgian Lambert 72) — daarnaast ook opgeslagen in `EPSG:4326` (WGS 84: `lon_wgs84`, `lat_wgs84`)
- **Stabiele ID:** `TerraId` (`terra_id`)
- **Bestanden:**
  - `data/raw/natuurbegraafplaatsen_anb_layer55.csv`
  - `data/raw/natuurbegraafplaatsen_anb_layer55.geojson`
- **Opmerkingen:**
  - In de ruwe ArcGIS-respons stonden twee letterlijke `"NULL"`-strings (`Goedkeuringsdatum` bij `TerraId=6737` en `Einddatum` bij `TerraId=5942`); deze zijn genormaliseerd naar leeg/`null`.
  - Let op bij OSRM-routering (sectie 4.1 van het uitvoeringsplan): de ANB-punten liggen mogelijk in het bos/natuurgebied en worden vóór de eindrun gecontroleerd op hun aansluiting (*snapping*) op het wegennet.

## 2. Vlaamse Landgebruikskaart 2025 (`lu_landgebruik_vlaa_2025_v3`)

- **Bron:** Departement Omgeving / MercatorNet — *Landgebruik - Vlaanderen - toestand 2025* (versie 3)
- **Catalogus / Metadata:** https://www.vlaanderen.be/datavindplaats/catalogus/landgebruik-vlaanderen-toestand-2025 (`afa000ea-114e-5ddb-81a6-b69a603fd90a`)
- **Download-URL (ZIP):** https://dataplatform.omgeving.vlaanderen.be/public/mercatornet/lu_landgebruik_vlaa_2025_v3
- **Publicatie / wijzigingsdatum:** gepubliceerd 2026-06-01, laatst gewijzigd 2026-06-18
- **Gedownload op:** 2026-11-21
- **Bestand:** `data/raw/landgebruik_2025/processed/lu_landgebruik_vlaa_2025_v3/lu_landgebruik_vlaa_2025_v3.tif`
- **CRS & resolutie:** `EPSG:31370`, 10 m × 10 m, vorm `(9200, 23700)`, `int32`
- **NoData-waarde:** `-9999`
- **Geverifieerde legenda-code (`lu_landgebruik_vlaa_2025_v3.sld`):** `1` = **Huizen en tuinen**

## 3. Vlaams Adressenregister (`GRAR_Adressen_Gpkg.zip`)

- **Bron:** Digitaal Vlaanderen — *Gebouwen- en adressenregister - Adressen* (product `10145`)
- **Productpagina:** https://download.vlaanderen.be/product/10145-gebouwen-en-adressenregister-adressen
- **Metadata:** https://metadata.vlaanderen.be/srv/dut/catalog.search#/metadata/9c8b57a1-3c9a-4813-926e-38bb0bd387a7
- **Versiedatum / publicatiedatum:** 2026-11-16
- **Gedownload op:** 2026-11-21 (Order `703947`, `GRAR_Adressen_Gpkg.zip`, 396 MB)
- **CRS:** `EPSG:31370` (Belge 1972 / Belgian Lambert 72)

## 4. OpenStreetMap wegennet (OSRM)

- **Bron:** Geofabrik — België (`belgium-latest.osm.pbf`, 667 MB)
- **Download-URL:** https://download.geofabrik.de/europe/belgium-latest.osm.pbf
- **Gedownload op:** 2026-11-21
- **Bestand:** `data/osrm/belgium-latest.osm.pbf`
- **Licentie / bronvermelding:** © OpenStreetMap contributors (ODbL)

## 5. Vlaamse gemeenten- en provinciegrenzen (VRBG 2025)

- **Bron:** Digitaal Vlaanderen — *Voorlopig referentiebestand gemeentegrenzen 2025* (`VRBG2025:Refgem`, 285 gemeenten; `VRBG2025:Refprv`, 5 provincies)
- **WFS-URL:** `https://geo.api.vlaanderen.be/VRBG2025/wfs`
- **Gedownload op:** 2026-11-21
- **CRS:** `EPSG:31370`
- **Bestanden:** `data/raw/vrbg2025_gemeenten.geojson`, `data/raw/vrbg2025_provincies.geojson`
