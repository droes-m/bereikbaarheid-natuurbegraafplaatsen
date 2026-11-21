# Methodenotitie: bereikbaarheid van natuurbegraafplaatsen in Vlaanderen

**Datum uitvoering:** 2026-11-21  
**Analyse-eenheid:** vermoedelijke woonadressen (officiële actieve adressen uit het Vlaamse Adressenregister binnen landgebruiksklasse *Huizen en tuinen*)

---

## 1. Gebruikte bronnen en versies

| Bron | Versie / peildatum | CRS | Omvang / opmerking |
|---|---|---|---|
| **ANB Belevingskaart — laag 55 (*Natuurbegraafplek*)** | Opgehaald 2026-11-21 (`Belevingssite/MapServer/55`) | `EPSG:31370` & `EPSG:4326` | 19 unieke locaties (`TerraId` als stabiele ID), geen duplicaten. |
| **Vlaams Adressenregister (`GRAR_Adressen.gpkg`)** | 2026-11-16 (`Latest_event_id: 142126457`, product `10145`) | `EPSG:31370` | 4.627.123 ruwe rijen → 3.876.738 actieve (`InGebruik`) officiële (`offtoegknd='T'`) adressen. |
| **Vlaamse Landgebruikskaart 2025 (`lu_landgebruik_vlaa_2025_v3.tif`)** | Versie 3 (gepubliceerd 2026-06-01, gewijzigd 2026-06-18) | `EPSG:31370` | 10 m × 10 m raster (`9200 × 23700`, `int32`), NoData = `-9999`, code `1` = *Huizen en tuinen* (geverifieerd uit officiële `.sld`). |
| **OpenStreetMap / OSRM (`belgium-latest.osm.pbf`)** | OSM-timestamp `2026-11-20T21:21:21Z` (Geofabrik) | `EPSG:4326` | `ghcr.io/project-osrm/osrm-backend:v6.0.0` (`arm64`), standaard `car.lua` zonder actuele verkeersinfo, Contraction Hierarchies (`ch`). |
| **VRBG 2025 gemeenten- en provinciegrenzen** | 2025 (`VRBG2025:Refgem` & `Refprv`, WFS) | `EPSG:31370` | 285 Vlaamse gemeenten (100% NIS-match met Adressenregister). |

---

## 2. Selectie van vermoedelijke woonadressen en vertrekpunten

1. **Adressenregister-filtering:** uit `4.627.123` ruwe rijen blijven `3.876.738` actieve officiële adressen over (`0` dubbele `adresid`'s, `0` ontbrekende geometrieën, `0` MultiPoints met >1 punt, `0` dubbele actieve adreslabels).
2. **Landgebruikssampling (exacte cel):**
   - **Geselecteerd (`1` = Huizen en tuinen):** **`2.974.685`** vermoedelijke woonadressen (76,73%).
   - Uitgesloten andere landgebruiksklasse: `902.015` (grootste klassen: Diensten `298.442`, Industrie `161.585`, Commercieel `143.135`, Transportinfrastructuur `93.963`).
   - Uitgesloten `NoData` (`-9999`): `38`; buiten raster: `0`.
   - **Diagnostiek ruimtelijke tolerantie (±1 cel / 10 m):** van de `902.015` uitgesloten adressen grenst `421.968` (46,8%) binnen 1 cel aan *Huizen en tuinen* (o.a. gemengde panden met handel/diensten op het gelijkvloers en adrespunten op perceelsranden of straatzijde). Conform het uitvoeringsplan gebruikt de hoofdanalyse uitsluitend de exacte celwaarde.
3. **Exacte coördinaatgroepering:** de `2.974.685` geselecteerde adressen vallen op **`2.263.537`** exact unieke coördinaatparen (`origin_id`, deduplicatieratio `1,314×`), zonder ruimtelijke afronding. De som van de gewichten is exact gelijk aan `2.974.685` (zowel voor Vlaanderen als opgeteld over alle 285 gemeenten).

---

## 3. Pilot, looptijden en technische controles

Uitgevoerd op een Apple Silicon-machine (24 GB RAM, 10 cores, native `arm64` OSRM `v6.0.0`):

| Fase | Omvang | Gemeten duur | Piek-RAM / doorvoer |
|---|---|---:|---|
| **Bronverwerking** (`prepare-addresses`) | 4,63M rijen + 218M rastercellen + tolerantie | **18,3 s** | < 3 GB RAM |
| **OSRM-voorbereiding** (`extract` + `contract`) | `belgium-latest.osm.pbf` (667 MB) | **131 s** (34 s + 97 s) | Piek 3,82 GB (`extract`), 0,89 GB (`contract`); schijf `data/osrm`: 1,4 GB |
| **Pilot** (`--pilot-n 10000`, gestratificeerd over 285 gemeenten) | 10.000 adressen → 9.945 unieke vertrekpunten | **1,47 s** (1 worker) | 6.782 vertrekpunten/s; 100% dekking |
| **Volledige eindrun** (heel Vlaanderen, 6 HTTP-workers) | 2.974.685 adressen → 2.263.537 unieke vertrekpunten (9.945 uit pilot-cache hergebruikt) | **54,2 s** | **41.583 vertrekpunten/s**; 100,00% dekking (`0` `no_route`, `0` `api_error`) |

Totale schijfruimte voor het volledige project (incl. ruwe downloads en OSRM): **3,9 GB** (`data/raw`: 2,2 GB; `data/osrm`: 1,4 GB; `data/interim`: 251 MB; `data/processed`: 72 MB; `outputs`: 6,5 MB).

### Uitgevoerde kwaliteitscontroles
- **Bestemming-snapping (OSRM `/nearest`):** alle 19 ANB-locaties sluiten correct aan op lokale wegen (`6,2 m` tot `153,9 m`, opgeslagen in `outputs/destination_snapping_check.csv`). Geen enkele locatie snapt op een autosnelweg of onlogische achterliggende weg; ingangscorrecties (`overrides`) waren niet nodig.
- **Vertrekpunt-snapping:** mediaan `17,2 m`, P90 `26,1 m`, P99 `63,1 m`, P99,9 `231,0 m`, max `1.462,7 m`. Met een signaleringsgrens van `250 m` betreft dit slechts `1.921` unieke vertrekpunten (`0,085%`).
- **Pilot vs. eindrun:** de 10.000-adressen pilot voorspelde de volledige populatie zeer nauwkeurig (gemiddelde `30,15` vs. `30,26 min`; mediaan `22,80` vs. `22,80 min`; P90 `64,86` vs. `65,18 min`; ≤ 30 min `65,32%` vs. `64,57%`).
- **Geautomatiseerde tests (`pytest`):** 5/5 geslaagd voor rijhuis, busadressen op identieke coördinaat, gemengde huisnummerfamilies (wel/niet geselecteerd busadres), NoData & buiten-raster, `no_route` vs. `api_error` met batch-splitsing, matching kilometers bij snelste reistijd, deterministische tie-break en gemeente-aggregatie met exacte P90-definitie.

---

## 4. Gevoeligheidsanalyse: busnummervariant

In heel Vlaanderen bevatten `206.535` huisnummerfamilies zowel een actief adres zonder busnummer als minstens één actief busadres. Wanneer binnen zo'n familie het adres zonder busnummer wordt weggelaten *indien minstens één busadres ook geselecteerd is*, vallen **`140.560` adressen** weg (`2.974.685` → `2.834.125`, −4,73%).

Het effect op de Vlaamse bereikbaarheidscijfers is verwaarloosbaar klein:
- Gemiddelde autorijtijd: **`+0,119 min`** (+7 seconden)
- P90 autorijtijd: **`+0,050 min`** (+3 seconden)
- Aandeel binnen 30 minuten: **`−0,482 procentpunt`** (`64,57%` → `64,09%`)

---

## 5. Interpretatie en bronbeperkingen

1. **Vermoedelijke woonadressen (proxy):** het Vlaamse Adressenregister koppelt adressen niet rechtstreeks aan woonfunctie, en de Landgebruikskaart (10 m) classificeert perceels-/celniveau, niet individuele appartementen. Gemengde panden (bv. appartementen boven handelszaken) kunnen daardoor buiten *Huizen en tuinen* vallen, terwijl niet-residentiële adressen binnen een woonperceel kunnen meegenomen worden.
2. **Geen actuele verkeersinformatie:** OSRM berekent theoretische vrije-doorstromingsrijtijden op basis van OSM-wegtypes en snelheidslimieten (`car.lua`). In spitsuren of rond ringwegen (Antwerpen R1, Brussel R0) liggen werkelijke rijtijden hoger.
3. **Grensoverschrijdende routes (`belgium-latest.osm.pbf`):** het Geofabrik-extract van België dekt 100% van alle 285 Vlaamse gemeenten inclusief de enclaves van Baarle-Hertog (mediaan `17,9 min` naar Merksplas Kolonie). Voor de exclave **Voeren** (4.300 inwoners) dwingt een puur Belgisch wegennet de route naar *Isaekshoef (Rekem)* via Belgisch grondgebied (~`45 min`, ~`36 km`), terwijl in de praktijk via Maastricht (NL) korter gereden kan worden. Op Vlaamse schaal (<0,1% van de adressen) is het effect verwaarloosbaar; voor een specifieke studie van Voeren kan een gecombineerd België+NL-Limburg OSM-netwerk gebruikt worden.
4. **Statbel Census 2021:** werd in deze eerste uitvoering niet als afzonderlijke sectortelling gekoppeld; alle controles op adresselectie en ruimtelijke spreiding zijn uitgevoerd op de officiële GRAR 2026-11-16 en Landgebruik 2025 distributies.
