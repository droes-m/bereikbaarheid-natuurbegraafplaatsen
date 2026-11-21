"""Gerichte synthetische tests volgens Uitvoeringsplan §6.

Dekking:
- rijhuis (uniek huisnummer, eigen coördinaat)
- meerdere busadressen op dezelfde coördinaat (exacte groepering + gewichtssom)
- adres zonder busnummer naast busadressen (zowel wanneer busadres wél als níet geselecteerd is)
- NoData en buiten-raster in de landgebruikskaart
- bestemming zonder route (null-cellen) + API-fouten apart van no_route
- gerapporteerde kilometers horen bij gekozen snelste reistijd (ook als andere bestemming korter in km is)
- deterministische tie-break op stabiele ID bij gelijke reistijd
- gewichten en exacte P90-definitie bij aggregatie per gemeente, inclusief gemeente zonder geldige routes
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import httpx
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point

from bereikbaarheid.addresses import filter_official_addresses
from bereikbaarheid.aggregate import aggregate_accessibility, compare_variants, weighted_quantile
from bereikbaarheid.config import CRS_LAMBERT72, RunConfig
from bereikbaarheid.destinations import load_destinations
from bereikbaarheid.landuse import sample_landuse
from bereikbaarheid.origins import build_origins
from bereikbaarheid.routing import route_origins_osrm, select_best_from_matrices


def _create_synthetic_raster(path: Path) -> Path:
    """Create a 4x4 10m Lambert72 raster:
    - col 0..1, row 0..1: code 1 (Huizen en tuinen)
    - col 2, row 0..1: code 5 (Transportinfrastructuur)
    - col 3, row 0..1: nodata (255)
    - rows 2..3: code 1
    Origin: x=150000, y=200040 (so x in [150000, 150040), y in (200000, 200040]).
    """
    data = np.array(
        [
            [1, 1, 5, 255],
            [1, 1, 5, 255],
            [1, 1, 1, 1],
            [1, 1, 1, 1],
        ],
        dtype=np.uint8,
    )
    transform = from_origin(150000.0, 200040.0, 10.0, 10.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs=CRS_LAMBERT72,
        transform=transform,
        nodata=255,
    ) as dst:
        dst.write(data, 1)
    return path


def test_real_anb_destinations_load_and_validate() -> None:
    csv_path = Path(__file__).resolve().parents[1] / "data" / "raw" / "natuurbegraafplaatsen_anb_layer55.csv"
    df, report = load_destinations(csv_path)
    assert report.total_rows == 19
    assert report.unique_destinations == 19
    assert report.duplicate_entrance_ids == []
    assert report.out_of_bbox_ids == []
    assert len(df) == 19


def test_addresses_landuse_and_origins_all_edge_cases(tmp_path: Path) -> None:
    raster_path = _create_synthetic_raster(tmp_path / "landgebruik.tif")

    # Synthetic Adressenregister in Lambert 72
    rows = [
        # 1. Rijhuis in gemeente A (selected, unique coord)
        {"adres_id": "A1", "status": "in gebruik", "officieel": True, "gemeente": "Antwerpen", "nis_code": "11002", "straatnaam_id": "S1", "huisnummer": "10A", "busnummer": None, "geometry": Point(150005.0, 200035.0)},
        # 2. Appartementsgebouw in gemeente A: 1 adres zonder bus + 3 busadressen op EXACT dezelfde coördinaat
        {"adres_id": "A2_nobus", "status": "in gebruik", "officieel": True, "gemeente": "Antwerpen", "nis_code": "11002", "straatnaam_id": "S1", "huisnummer": "12", "busnummer": "", "geometry": Point(150015.0, 200035.0)},
        {"adres_id": "A2_b1", "status": "in gebruik", "officieel": True, "gemeente": "Antwerpen", "nis_code": "11002", "straatnaam_id": "S1", "huisnummer": "12", "busnummer": "0001", "geometry": Point(150015.0, 200035.0)},
        {"adres_id": "A2_b2", "status": "in gebruik", "officieel": True, "gemeente": "Antwerpen", "nis_code": "11002", "straatnaam_id": "S1", "huisnummer": "12", "busnummer": "0002", "geometry": Point(150015.0, 200035.0)},
        {"adres_id": "A2_b3", "status": "in gebruik", "officieel": True, "gemeente": "Antwerpen", "nis_code": "11002", "straatnaam_id": "S1", "huisnummer": "12", "busnummer": "0003", "geometry": Point(150015.0, 200035.0)},
        # 3. Familie waarbij adres zonder bus WEL geselecteerd is (code 1), maar busadres in andere klasse valt (code 5):
        #    -> in busnummervariant blijft adres zonder bus BEHOUDEN omdat geen enkel busadres geselecteerd is!
        {"adres_id": "B1_nobus", "status": "in gebruik", "officieel": True, "gemeente": "Gent", "nis_code": "44021", "straatnaam_id": "S2", "huisnummer": "5", "busnummer": "", "geometry": Point(150005.0, 200025.0)},
        {"adres_id": "B1_bus_excl", "status": "in gebruik", "officieel": True, "gemeente": "Gent", "nis_code": "44021", "straatnaam_id": "S2", "huisnummer": "5", "busnummer": "1", "geometry": Point(150025.0, 200025.0)},
        # 4. NoData in landgebruikskaart
        {"adres_id": "ND1", "status": "in gebruik", "officieel": True, "gemeente": "Gent", "nis_code": "44021", "straatnaam_id": "S3", "huisnummer": "1", "busnummer": "", "geometry": Point(150035.0, 200035.0)},
        # 5. Buiten raster
        {"adres_id": "OOB1", "status": "in gebruik", "officieel": True, "gemeente": "Gent", "nis_code": "44021", "straatnaam_id": "S3", "huisnummer": "2", "busnummer": "", "geometry": Point(160000.0, 210000.0)},
        # 6. Niet-actief of niet-officieel adres (moet eruit bij stap 1)
        {"adres_id": "INACT1", "status": "gehistoreerd", "officieel": True, "gemeente": "Antwerpen", "nis_code": "11002", "straatnaam_id": "S1", "huisnummer": "99", "busnummer": "", "geometry": Point(150005.0, 200035.0)},
        {"adres_id": "UNOFF1", "status": "in gebruik", "officieel": False, "gemeente": "Antwerpen", "nis_code": "11002", "straatnaam_id": "S1", "huisnummer": "98", "busnummer": "", "geometry": Point(150005.0, 200035.0)},
    ]
    gdf = gpd.GeoDataFrame(rows, crs=CRS_LAMBERT72)

    valid_addr, dup_labels, addr_rep = filter_official_addresses(gdf)
    assert addr_rep.total_raw_rows == 11
    assert addr_rep.after_active_official_filter == 9
    assert len(dup_labels) == 0

    sampled, lu_rep = sample_landuse(valid_addr, raster_path, residential_code=1)
    assert lu_rep.selected_count == 6  # A1, A2_nobus, A2_b1..b3, B1_nobus
    assert lu_rep.excluded_landuse_count == 1  # B1_bus_excl
    assert lu_rep.excluded_nodata_count == 1  # ND1
    assert lu_rep.excluded_out_of_bounds_count == 1  # OOB1

    addr_map, origins, orig_rep = build_origins(sampled)
    # 6 selected addresses across 3 unique exact coordinates:
    # (150005, 200035) -> weight 1 (A1)
    # (150015, 200035) -> weight 4 (A2_nobus + 3 buses)
    # (150005, 200025) -> weight 1 (B1_nobus)
    assert orig_rep.selected_main_count == 6
    assert orig_rep.unique_origins_count == 3
    assert int(origins["weight_main"].sum()) == 6

    # No-bus variant: A2_nobus is dropped (because A2_b1..b3 ARE selected),
    # whereas B1_nobus is KEPT (because B1_bus_excl was NOT selected)!
    assert orig_rep.selected_no_bus_variant_count == 5
    assert orig_rep.dropped_in_no_bus_variant == 1
    assert bool(addr_map.loc[addr_map["adres_id"] == "A2_nobus", "in_no_bus_variant"].iloc[0]) is False
    assert bool(addr_map.loc[addr_map["adres_id"] == "B1_nobus", "in_no_bus_variant"].iloc[0]) is True


def test_select_best_duration_keeps_matching_distance_and_tiebreaks_deterministically() -> None:
    # Dest D2 is faster (600s) but LONGER in distance (15000m) than D1 (700s, 10000m).
    # Must pick D2 AND report 15000m (not 10000m)!
    # Origin 1: tie at 500s between D2 and D1 -> must deterministically pick D1 (< D2).
    # Origin 2: all null -> status='no_route'.
    res = select_best_from_matrices(
        durations=[
            [700.0, 600.0],
            [500.0, 500.0],
            [None, None],
        ],
        distances=[
            [10000.0, 15000.0],
            [8000.0, 9000.0],
            [None, None],
        ],
        destination_ids=["D1", "D2"],
        entrance_ids=["E1", "E2"],
        source_snap_distances=[12.5, 5.0, 40.0],
        dest_snap_distances=[3.0, 7.0],
    )
    assert res[0]["status"] == "ok"
    assert res[0]["best_destination_id"] == "D2"
    assert res[0]["duration_s"] == 600.0
    assert res[0]["distance_m"] == 15000.0

    assert res[1]["status"] == "ok"
    assert res[1]["best_destination_id"] == "D1"
    assert res[1]["distance_m"] == 8000.0

    assert res[2]["status"] == "no_route"
    assert np.isnan(res[2]["duration_s"])
    assert res[2]["best_destination_id"] is None


def test_osrm_batch_split_isolates_api_error_and_resumes_cache(tmp_path: Path) -> None:
    origins = pd.DataFrame(
        {
            "origin_id": ["o1", "o2", "o3"],
            "lon": [4.40, 4.41, 4.42],
            "lat": [51.20, 51.21, 51.22],
        }
    )
    destinations = pd.DataFrame(
        {
            "destination_id": ["D1"],
            "entrance_id": ["E1"],
            "lon": [4.50],
            "lat": [51.25],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        # Simulate failure whenever o2 (4.4100000) is part of the batch
        if "4.4100000" in str(request.url):
            return httpx.Response(500, json={"code": "ServerError", "message": "boom"})
        n_src = len(request.url.params["sources"].split(";"))
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "durations": [[600.0] for _ in range(n_src)],
                "distances": [[9500.0] for _ in range(n_src)],
                "sources": [{"distance": 4.2} for _ in range(n_src)],
                "destinations": [{"distance": 8.1}],
            },
        )

    transport = httpx.MockTransport(handler)
    cfg = RunConfig(batch_size=3, dest_chunk_size=10)

    with httpx.Client(transport=transport) as client:
        res, metrics = route_origins_osrm(origins, destinations, cfg, tmp_path / "cache", client=client)

    assert metrics.ok_count == 2
    assert metrics.api_error_count == 1
    assert metrics.no_route_count == 0
    assert res.loc[res["origin_id"] == "o2", "status"].iloc[0] == "api_error"
    assert res.loc[res["origin_id"] == "o1", "status"].iloc[0] == "ok"

    # Second call should load 100% from cache (0 newly routed)
    with httpx.Client(transport=transport) as client:
        res2, metrics2 = route_origins_osrm(origins, destinations, cfg, tmp_path / "cache", client=client)
    assert metrics2.cached_origins == 3
    assert metrics2.newly_routed_origins == 0
    assert len(res2) == 3


def test_weighted_aggregation_p90_and_empty_municipality() -> None:
    # Exact P90 definition check
    assert weighted_quantile(np.array([10.0, 20.0, 30.0]), np.array([1, 8, 1]), 0.90) == 20.0
    assert weighted_quantile(np.array([10.0, 20.0, 30.0]), np.array([1, 7, 2]), 0.90) == 30.0

    # 10 bus addresses at o1 (10 min, 8 km) in GemA, 1 house at o2 (40 min, 35 km) in GemA,
    # 2 addresses at o3 (no_route) in GemB (so GemB has 0 valid routes!)
    addr_map = pd.DataFrame(
        [
            *[{"adres_id": f"a{i}", "origin_id": "o1", "nis_code": "10001", "gemeente": "GemA", "in_main_analysis": True, "in_no_bus_variant": i > 0} for i in range(10)],
            {"adres_id": "a10", "origin_id": "o2", "nis_code": "10001", "gemeente": "GemA", "in_main_analysis": True, "in_no_bus_variant": True},
            {"adres_id": "b1", "origin_id": "o3", "nis_code": "20002", "gemeente": "GemB", "in_main_analysis": True, "in_no_bus_variant": True},
            {"adres_id": "b2", "origin_id": "o3", "nis_code": "20002", "gemeente": "GemB", "in_main_analysis": True, "in_no_bus_variant": True},
        ]
    )
    origin_res = pd.DataFrame(
        [
            {"origin_id": "o1", "status": "ok", "duration_s": 600.0, "distance_m": 8000.0},
            {"origin_id": "o2", "status": "ok", "duration_s": 2400.0, "distance_m": 35000.0},
            {"origin_id": "o3", "status": "no_route", "duration_s": float("nan"), "distance_m": float("nan")},
        ]
    )

    fl_main, mun_main = aggregate_accessibility(addr_map, origin_res, variant="main")
    fl_var, _ = aggregate_accessibility(addr_map, origin_res, variant="no_bus_variant")

    # Flanders main: 13 selected, 11 valid (10 @ 10min, 1 @ 40min), 2 no_route
    row_fl = fl_main.iloc[0]
    assert row_fl["n_selected"] == 13
    assert row_fl["n_valid_route"] == 11
    assert row_fl["n_no_route"] == 2
    assert row_fl["routing_coverage_pct"] == pytest.approx(100.0 * 11 / 13)
    assert row_fl["mean_duration_min"] == pytest.approx((10 * 10 + 1 * 40) / 11)
    assert row_fl["median_duration_min"] == 10.0
    # 10 / 11 = 90.91% >= 90% -> P90 is 10.0 min!
    assert row_fl["p90_duration_min"] == 10.0
    assert row_fl["pct_within_15_min"] == pytest.approx(100.0 * 10 / 11)
    assert row_fl["pct_within_45_min"] == pytest.approx(100.0)

    # GemB: 0 valid routes -> NaN for travel time stats, 0% coverage
    row_b = mun_main.loc[mun_main["gemeente"] == "GemB"].iloc[0]
    assert row_b["n_selected"] == 2
    assert row_b["n_valid_route"] == 0
    assert row_b["n_no_route"] == 2
    assert row_b["routing_coverage_pct"] == 0.0
    assert np.isnan(row_b["mean_duration_min"])
    assert np.isnan(row_b["p90_duration_min"])

    # Variant comparison
    diff = compare_variants(fl_main, fl_var)
    assert diff.iloc[0]["n_addresses_changed"] == 1
