"""Landgebruikskaart 2025 GeoTIFF sampling and spatial tolerance diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

# Default code for "Huizen en tuinen" in Vlaamse Landgebruikskaart (verify against raster metadata/legend!)
DEFAULT_RESIDENTIAL_CODE = 1


@dataclass(frozen=True)
class LanduseSamplingReport:
    raster_path: str
    raster_crs: str
    nodata_value: float | int | None
    residential_code: int
    total_points: int
    selected_count: int
    excluded_landuse_count: int
    excluded_nodata_count: int
    excluded_out_of_bounds_count: int
    class_counts: dict[int, int]


def sample_landuse(
    addresses: gpd.GeoDataFrame,
    raster_path: Path,
    residential_code: int = DEFAULT_RESIDENTIAL_CODE,
) -> tuple[gpd.GeoDataFrame, LanduseSamplingReport]:
    """Sample Landgebruikskaart GeoTIFF directly at each address point in raster CRS.

    Adds columns:
      - landuse_code (Int64, nullable for NoData / out-of-bounds)
      - landuse_in_bounds (bool)
      - landuse_is_nodata (bool)
      - selection_status: 'selected' | 'excluded_landuse' | 'excluded_nodata' | 'excluded_out_of_bounds'
      - selection_reason: human-readable reason string
    """
    if addresses.crs is None:
        raise ValueError("Adressen GeoDataFrame heeft geen CRS ingesteld.")

    with rasterio.open(raster_path) as src:
        raster_crs = src.crs
        if raster_crs is None:
            raise ValueError(f"Raster {raster_path} heeft geen CRS.")
        nodata = src.nodata
        transform = src.transform
        height, width = src.height, src.width
        band = src.read(1)

    xs = addresses.geometry.x.to_numpy(dtype=np.float64)
    ys = addresses.geometry.y.to_numpy(dtype=np.float64)

    if str(addresses.crs) != str(raster_crs):
        transformer = Transformer.from_crs(addresses.crs, raster_crs, always_xy=True)
        xs_r, ys_r = transformer.transform(xs, ys)
        xs_r = np.asarray(xs_r, dtype=np.float64)
        ys_r = np.asarray(ys_r, dtype=np.float64)
    else:
        xs_r, ys_r = xs, ys

    inv_transform = ~transform
    cols_f, rows_f = inv_transform @ (xs_r, ys_r)
    cols = np.floor(cols_f).astype(np.int64)
    rows = np.floor(rows_f).astype(np.int64)

    in_bounds = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)

    raw_vals = np.full(len(addresses), np.nan, dtype=np.float64)
    if np.any(in_bounds):
        raw_vals[in_bounds] = band[rows[in_bounds], cols[in_bounds]]

    if nodata is not None and not (isinstance(nodata, float) and np.isnan(nodata)):
        is_nodata = in_bounds & (raw_vals == float(nodata))
    else:
        is_nodata = in_bounds & np.isnan(raw_vals)

    valid_val_mask = in_bounds & (~is_nodata)
    is_selected = valid_val_mask & (raw_vals == float(residential_code))

    status = np.full(len(addresses), "excluded_landuse", dtype=object)
    reason = np.full(len(addresses), "andere_landgebruiksklasse", dtype=object)

    status[~in_bounds] = "excluded_out_of_bounds"
    reason[~in_bounds] = "buiten_raster"

    status[is_nodata] = "excluded_nodata"
    reason[is_nodata] = "raster_nodata"

    status[is_selected] = "selected"
    reason[is_selected] = "huizen_en_tuinen"

    codes_int = np.where(valid_val_mask, raw_vals, 0).astype(np.int64)
    codes_nullable = pd.arrays.IntegerArray(codes_int, mask=~valid_val_mask)

    out = addresses.copy()
    out["landuse_code"] = codes_nullable
    out["landuse_in_bounds"] = in_bounds
    out["landuse_is_nodata"] = is_nodata
    out["selection_status"] = status
    out["selection_reason"] = reason

    valid_codes = raw_vals[valid_val_mask].astype(np.int64)
    unique_c, counts_c = np.unique(valid_codes, return_counts=True)
    class_counts = {int(c): int(n) for c, n in zip(unique_c, counts_c, strict=True)}

    report = LanduseSamplingReport(
        raster_path=str(raster_path),
        raster_crs=str(raster_crs),
        nodata_value=nodata,
        residential_code=residential_code,
        total_points=len(addresses),
        selected_count=int(is_selected.sum()),
        excluded_landuse_count=int((status == "excluded_landuse").sum()),
        excluded_nodata_count=int(is_nodata.sum()),
        excluded_out_of_bounds_count=int((~in_bounds).sum()),
        class_counts=class_counts,
    )
    return out, report


def check_spatial_tolerance(
    sampled_addresses: gpd.GeoDataFrame,
    raster_path: Path,
    residential_code: int = DEFAULT_RESIDENTIAL_CODE,
    radius_cells: int = 1,
) -> dict[str, int | float]:
    """Diagnostic: check how many excluded-by-landuse points have residential_code within +/- radius_cells."""
    excluded = sampled_addresses.loc[
        sampled_addresses["selection_status"] == "excluded_landuse"
    ]
    if len(excluded) == 0:
        return {
            "excluded_landuse_checked": 0,
            "would_match_with_tolerance": 0,
            "pct_of_excluded_landuse": 0.0,
            "radius_cells": radius_cells,
        }

    with rasterio.open(raster_path) as src:
        raster_crs = src.crs
        transform = src.transform
        height, width = src.height, src.width
        band = src.read(1)

    xs = excluded.geometry.x.to_numpy(dtype=np.float64)
    ys = excluded.geometry.y.to_numpy(dtype=np.float64)
    if str(excluded.crs) != str(raster_crs):
        transformer = Transformer.from_crs(excluded.crs, raster_crs, always_xy=True)
        xs, ys = transformer.transform(xs, ys)
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)

    cols_f, rows_f = (~transform) @ (xs, ys)
    cols = np.floor(cols_f).astype(np.int64)
    rows = np.floor(rows_f).astype(np.int64)

    # Vectorized check over all (dr, dc) offsets in [-radius_cells, +radius_cells]
    is_res = band == residential_code
    matched_mask = np.zeros(len(rows), dtype=bool)
    for dr in range(-radius_cells, radius_cells + 1):
        rr = rows + dr
        r_ok = (rr >= 0) & (rr < height)
        for dc in range(-radius_cells, radius_cells + 1):
            cc = cols + dc
            ok = r_ok & (cc >= 0) & (cc < width)
            if np.any(ok):
                matched_mask[ok] |= is_res[rr[ok], cc[ok]]
    matched = int(matched_mask.sum())

    return {
        "excluded_landuse_checked": len(excluded),
        "would_match_with_tolerance": matched,
        "pct_of_excluded_landuse": round(100.0 * matched / len(excluded), 3),
        "radius_cells": radius_cells,
    }
