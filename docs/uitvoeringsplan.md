# Uitvoeringsplan bereikbaarheid van natuurbegraafplaatsen in Vlaanderen

**Status: in uitvoering**

## 1. Opdracht

Bouw en voer lokaal een reproduceerbare analyse uit van de **autorijtijd vanaf vermoedelijke woonadressen in het Vlaamse Gewest naar de snelst bereikbare natuurbegraafplaats uit de aangeleverde lijst**. Bewaar ook de kilometers van de geselecteerde autoroute. Rapporteer de resultaten voor Vlaanderen en per gemeente.

Gebruik de officiële adrespunten uit het **Vlaamse Adressenregister** en de klasse **Huizen en tuinen** uit de **Landgebruikskaart 2025** om vermoedelijke woonadressen te selecteren. Gebruik **OSRM met OpenStreetMap** voor het wegennet en routering. Het Gebouwenregister en OSM-gebouwtags vallen buiten deze eerste uitvoering. Gebruik een vast autoprofiel zonder actuele verkeersinformatie.

De eenheid van analyse is het **unieke geselecteerde adres inclusief busnummer**. Dat is een praktische benadering van woonlocaties. De landgebruikskaart deelt geen afzonderlijke adressen of appartementen in naar woonfunctie. Gebruik in alle rapporten daarom de term **vermoedelijke woonadressen**.

## 2. Invoer en bronnen

| Invoer | Doel en minimale vereisten |
|---|---|
| **Natuurbegraafplaatsen van de opdrachtgever** | Opgehaald uit de ANB Belevingskaart (`showlayerid=55`, 19 locaties, `data/raw/natuurbegraafplaatsen_anb_layer55.csv` & `.geojson`, origineel CRS `EPSG:31370` + `EPSG:4326`). |
| **Vlaams Adressenregister** | Bulkextract van de adreslaag met stabiele adres-ID, status, aanduiding officiële toekenning, geometrie, gemeente/NIS-code, straatnaam-ID, huisnummer en busnummer. [Dataset](https://www.vlaanderen.be/datavindplaats/catalogus/gebouwen-en-adressenregister) · [Adresvelden](https://www.vlaanderen.be/digitaal-vlaanderen/onze-diensten-en-platformen/basiskaart-vlaanderen-grb/objectenhandboek-basiskaart-vlaanderen-grb/adres-uit-het-adressenregister-adres) |
| **Vlaamse Landgebruikskaart 2025** | GeoTIFF op 10 m resolutie (`lu_landgebruik_vlaa_2025_v3`, Lambert 72). Legenda voor **Huizen en tuinen** en NoData-waarde vastleggen. [Dataset](https://www.vlaanderen.be/datavindplaats/catalogus/landgebruik-vlaanderen-toestand-2025) · [Methodiek](https://indicatoren.omgeving.vlaanderen.be/indicatoren/landgebruik) |
| **OSM-extract voor routering** | Minstens België voor proefberekening; voor eindrun voldoende grensoverschrijdende dekking. [Geofabrik België](https://download.geofabrik.de/europe/belgium.html) |
| **Optioneel: Statbel Census 2021** | Woningtellingen per statistische sector ter controle van opvallende ruimtelijke verschillen. [Statbel](https://statbel.fgov.be/nl/open-data/census-2021-conventionele-woningen-naar-statistische-sector-en-bouwperiode) |

## 3. Woonadressen selecteren en vertrekpunten maken

1. Selecteer actieve officiële adressen in Vlaanderen (*in gebruik* + *officieel toegekend*), 1 rij per stabiele adres-ID, huis- en busnummers als tekst, rapporteer ontbrekende geometrieën en dubbele actieve adreslabels met verschillende ID's.
2. Sample Landgebruikskaart 2025 op exact punt in raster-CRS; NoData en buiten-raster apart bijhouden; selecteer **Huizen en tuinen**; test eventuele ruimtelijke tolerantie apart in de pilot.
3. Behoud het busnummer in de telling.
4. Markeer huisnummerfamilies (`straatnaam_id`, `gemeente`, `huisnummer`) met zowel een adres zonder bus als actieve busadressen. Hoofdanalyse: alle geselecteerde adressen. Variant: adressen zonder bus vallen weg als minstens één busadres in die familie ook geselecteerd is.
5. Groepeer exacte identieke coördinaten tot unieke `origin_id`'s zonder afronding; bewaar adres-naar-origin koppeling.

## 4. Lokaal routeren met OSRM

1. Valideer bestemmingen, controleer OSRM snapping op het wegennet, leg eventuele ingangscorrecties apart vast.
2. Lokale OSRM (Docker-image + CH + `car.lua`), verifieer `annotations=duration,distance`.
3. Matrixquery per batch `sources` vs alle `destinations` (WGS 84 `lon,lat`).
4. Kies laagste reistijd per vertrekpunt, neem afstand uit dezelfde cel, breek gelijke tijden deterministisch op stabiele ID.
5. Hou `null`-cellen, `no_route` en `api_error` strikt gescheiden; splits mislukte batches indien nodig; geen `fallback_speed`; bewaar snap-afstand.
6. Hervatbare batchopslag op stabiele `origin_id` + runconfiguratie.

## 5. Proefberekening en controles

- Rooktest met rijhuis, busadressen-groep en echte bestemmingen.
- Reproduceerbare, geografisch verspreide steekproef (~10.000 geselecteerde adressen).
- Tijd-, RAM-, schijf- en doorvoermetingen + extrapolatie naar heel Vlaanderen.
- Vergelijking hoofdanalyse vs. busnummervariant.

## 6. Resultaten en oplevering

- Gewogen gemiddelde, mediaan, P90 en aandeel binnen 15, 30 en 45 min + gemiddelde en mediaan rijafstand (km) voor Vlaanderen en per gemeente.
- Expliciete noemer = adressen met geldige route; rapporteer routedekking, `no_route` en `api_error` afzonderlijk.
- Reproduceerbare scripts (`uv` + Docker OSRM), controlebestanden (Parquet), samenvattingstabel, gemeentekaart (met disclaimer + © OpenStreetMap contributors), korte methodenotitie, en geautomatiseerde tests.
