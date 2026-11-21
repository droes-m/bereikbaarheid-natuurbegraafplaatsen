"""Address family busnummer-variant flagging and exact-coordinate origin grouping."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

from bereikbaarheid.config import CRS_WGS84


@dataclass(frozen=True)
class OriginsBuildReport:
    total_active_addresses: int
    selected_main_count: int
    selected_no_bus_variant_count: int
    dropped_in_no_bus_variant: int
    families_with_mixed_bus_and_nobus: int
    unique_origins_count: int
    dedup_ratio: float


def _coord_origin_id(x: float, y: float) -> str:
    """Deterministic stable origin_id from exact IEEE-754 float representation (no rounding)."""
    raw = f"{float(x)!r},{float(y)!r}".encode("ascii")
    return hashlib.sha256(raw).hexdigest()[:16]


def build_origins(
    addresses_with_landuse: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, OriginsBuildReport]:
    """Build address->origin mapping (with main & no-bus variant flags) and unique origins table.

    Rules (Uitvoeringsplan §3.3-3.5):
    - Family key: (nis_code, gemeente, straatnaam_id, huisnummer).
    - Mark families having BOTH an active address without busnummer AND >=1 active address with busnummer.
    - Main analysis: all addresses with selection_status == 'selected'.
    - No-bus variant: drops selected addresses with busnummer == '' ONLY IF at least one
      selected address in the same family has busnummer != ''.
    - Group selected addresses on EXACT identical (x, y) coordinates (no rounding).
    - Sum of origin weights equals count of selected unique addresses.
    """
    if addresses_with_landuse.crs is None:
        raise ValueError("GeoDataFrame mist CRS.")

    df = addresses_with_landuse.copy()
    df["busnummer"] = df["busnummer"].fillna("").astype(str).str.strip()
    df["has_bus"] = df["busnummer"] != ""
    df["no_bus"] = ~df["has_bus"]
    df["is_selected"] = df["selection_status"] == "selected"

    family_cols = ["nis_code", "gemeente", "straatnaam_id", "huisnummer"]

    # Family-level flags across active addresses (fully vectorized — fast on 4M rows)
    fam_active = df.groupby(family_cols, dropna=False, sort=False).agg(
        fam_has_bus=("has_bus", "any"),
        fam_has_nobus=("no_bus", "any"),
    )
    fam_active["family_mixed_bus_nobus"] = fam_active["fam_has_bus"] & fam_active["fam_has_nobus"]

    # Family-level flag: is at least one bus address ALSO selected in this family?
    df["selected_bus"] = df["is_selected"] & df["has_bus"]
    fam_sel_bus = (
        df.groupby(family_cols, dropna=False, sort=False)["selected_bus"]
        .any()
        .rename("family_has_selected_bus")
    )

    df = df.merge(
        fam_active[["family_mixed_bus_nobus"]],
        left_on=family_cols,
        right_index=True,
        how="left",
    )
    df = df.merge(
        fam_sel_bus,
        left_on=family_cols,
        right_index=True,
        how="left",
    )

    selected = df.loc[df["is_selected"]].copy().reset_index(drop=True)
    selected["in_main_analysis"] = True
    selected["in_no_bus_variant"] = ~(
        (~selected["has_bus"]) & selected["family_has_selected_bus"]
    )

    xs = selected.geometry.x.to_numpy(dtype=np.float64)
    ys = selected.geometry.y.to_numpy(dtype=np.float64)
    selected["coord_x"] = xs
    selected["coord_y"] = ys

    # Exact coordinate grouping (no rounding)
    unique_coords = (
        selected[["coord_x", "coord_y"]]
        .drop_duplicates()
        .sort_values(["coord_x", "coord_y"])
        .reset_index(drop=True)
    )
    unique_coords["origin_id"] = [
        _coord_origin_id(x, y)
        for x, y in zip(unique_coords["coord_x"], unique_coords["coord_y"], strict=True)
    ]

    if str(addresses_with_landuse.crs) != CRS_WGS84:
        transformer = Transformer.from_crs(addresses_with_landuse.crs, CRS_WGS84, always_xy=True)
        lon, lat = transformer.transform(
            unique_coords["coord_x"].to_numpy(),
            unique_coords["coord_y"].to_numpy(),
        )
        unique_coords["lon"] = np.asarray(lon, dtype=np.float64)
        unique_coords["lat"] = np.asarray(lat, dtype=np.float64)
    else:
        unique_coords["lon"] = unique_coords["coord_x"]
        unique_coords["lat"] = unique_coords["coord_y"]

    selected = selected.merge(
        unique_coords[["coord_x", "coord_y", "origin_id"]],
        on=["coord_x", "coord_y"],
        how="left",
        validate="many_to_one",
    )

    # Aggregate weights per origin
    weights = (
        selected.groupby("origin_id", sort=False)
        .agg(
            weight_main=("in_main_analysis", "sum"),
            weight_no_bus_variant=("in_no_bus_variant", "sum"),
        )
        .reset_index()
    )
    origins = unique_coords.merge(weights, on="origin_id", how="left", validate="one_to_one")
    origins["weight_main"] = origins["weight_main"].astype(np.int64)
    origins["weight_no_bus_variant"] = origins["weight_no_bus_variant"].astype(np.int64)

    # Strict invariant check
    assert int(origins["weight_main"].sum()) == len(selected), (
        f"Som van gewichten ({origins['weight_main'].sum()}) != aantal geselecteerde adressen ({len(selected)})"
    )
    assert int(origins["weight_no_bus_variant"].sum()) == int(selected["in_no_bus_variant"].sum())

    address_origin_map = selected[
        [
            "adres_id",
            "origin_id",
            "nis_code",
            "gemeente",
            "straatnaam_id",
            "huisnummer",
            "busnummer",
            "landuse_code",
            "selection_status",
            "selection_reason",
            "family_mixed_bus_nobus",
            "in_main_analysis",
            "in_no_bus_variant",
        ]
    ].copy()

    n_main = len(selected)
    n_var = int(selected["in_no_bus_variant"].sum())
    n_origins = len(origins)

    report = OriginsBuildReport(
        total_active_addresses=len(df),
        selected_main_count=n_main,
        selected_no_bus_variant_count=n_var,
        dropped_in_no_bus_variant=n_main - n_var,
        families_with_mixed_bus_and_nobus=int(fam_active["family_mixed_bus_nobus"].sum()),
        unique_origins_count=n_origins,
        dedup_ratio=(n_main / n_origins) if n_origins > 0 else 0.0,
    )
    return address_origin_map, origins, report
