"""Vlaams Adressenregister loading, filtering, and quality checks."""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

# Common column aliases across Vlaams Adressenregister (GRAR GPKG/SHP) / GRB / Best-Address
DEFAULT_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "adres_id": ("adres_id", "adresid", "ADRES_ID", "ADRESID", "IDENTIFICATOR", "id", "object_id", "OIDN"),
    "status": ("status", "STATUS", "adresstatus", "ADRESSTATUS"),
    "officieel": (
        "officieel",
        "OFFICIEEL",
        "offtoegknd",
        "OFFTOEGKND",
        "officieel_toegekend",
        "officieelToegekend",
        "OFFTOEG",
        "officiele_toekenning",
    ),
    "gemeente": ("gemeente", "GEMEENTE", "gemeentenm", "GEMEENTENM", "gemeentenaam", "GEMEENTENAAM", "GMNM"),
    "nis_code": ("nis_code", "NIS_CODE", "gemeenteid", "GEMEENTEID", "niscode", "NISCODE", "gemeente_nis", "NIS"),
    "straatnaam_id": ("straatnaam_id", "STRAATNAAM_ID", "straatnmid", "STRAATNMID", "straat_id", "STRAATID"),
    "huisnummer": ("huisnummer", "HUISNUMMER", "huisnr", "HUISNR", "HN"),
    "busnummer": ("busnummer", "BUSNUMMER", "busnr", "BUSNR", "BN"),
}

ACTIVE_STATUS_VALUES = {"in gebruik", "ingebruik", "in_gebruik", "current", "actief"}
OFFICIAL_TRUE_VALUES = {"true", "t", "1", "ja", "j", "yes", "y", "officieel toegekend", "officieel"}


@dataclass(frozen=True)
class AddressFilterReport:
    total_raw_rows: int
    after_active_official_filter: int
    duplicate_adres_ids_removed: int
    missing_geometry_count: int
    multipoint_gt1_count: int
    valid_geometry_count: int
    duplicate_active_labels_count: int
    duplicate_active_label_groups: int


def _resolve_column(columns: pd.Index, canonical: str, overrides: dict[str, str] | None) -> str:
    if overrides and canonical in overrides:
        col = overrides[canonical]
        if col not in columns:
            raise KeyError(f"Opgegeven kolom '{col}' voor '{canonical}' niet gevonden in {list(columns)}")
        return col
    for candidate in DEFAULT_COLUMN_ALIASES[canonical]:
        if candidate in columns:
            return candidate
    raise KeyError(
        f"Kan kolom voor '{canonical}' niet automatisch vinden. Beschikbare kolommen: {list(columns)}"
    )


def _normalize_text_number(series: pd.Series) -> pd.Series:
    """Preserve house and bus numbers as clean strings, keeping letters and normalizing nulls to ''."""
    return (
        series.where(series.notna(), "")
        .astype(str)
        .str.strip()
        .replace({"nan": "", "None": "", "NULL": "", "<NA>": ""})
    )


def _is_active_status(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().isin(ACTIVE_STATUS_VALUES)


def _is_official(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.fillna("").astype(str).str.strip().str.lower().isin(OFFICIAL_TRUE_VALUES)


def _normalize_to_points(geom_series: gpd.GeoSeries) -> tuple[gpd.GeoSeries, int]:
    """Normalize Point / single-part MultiPoint geometries to Points cleanly (vectorized)."""
    geoms = geom_series.to_numpy()
    type_ids = shapely.get_type_id(geoms)
    # Type ID 0 = Point, 4 = MultiPoint
    is_mp = type_ids == 4
    mp_gt1 = 0
    if np.any(is_mp):
        mp_geoms = geoms[is_mp]
        n_parts = shapely.get_num_geometries(mp_geoms)
        mp_gt1 = int(np.sum(n_parts > 1))
        first_pts = shapely.get_geometry(mp_geoms, 0)
        geoms = geoms.copy()
        geoms[is_mp] = first_pts
    return gpd.GeoSeries(geoms, index=geom_series.index, crs=geom_series.crs), mp_gt1


def filter_official_addresses(
    gdf: gpd.GeoDataFrame,
    column_map: dict[str, str] | None = None,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, AddressFilterReport]:
    """Filter Adressenregister to active, officially assigned addresses with 1 row per adres_id.

    Returns:
      - cleaned GeoDataFrame (only rows with valid non-empty Point geometry)
      - duplicate_labels DataFrame (active addresses sharing gemeente + straatnaam_id + huisnummer + busnummer across distinct adres_ids)
      - AddressFilterReport with counts for auditability
    """
    total_raw = len(gdf)
    resolved = {
        key: _resolve_column(gdf.columns, key, column_map)
        for key in (
            "adres_id",
            "status",
            "officieel",
            "gemeente",
            "nis_code",
            "straatnaam_id",
            "huisnummer",
            "busnummer",
        )
    }

    active_mask = _is_active_status(gdf[resolved["status"]]) & _is_official(
        gdf[resolved["officieel"]]
    )
    filtered = gdf.loc[active_mask]
    after_filter = len(filtered)

    out = gpd.GeoDataFrame(
        {
            "adres_id": filtered[resolved["adres_id"]].astype(str).str.strip(),
            "gemeente": filtered[resolved["gemeente"]].fillna("").astype(str).str.strip(),
            "nis_code": filtered[resolved["nis_code"]].fillna("").astype(str).str.strip(),
            "straatnaam_id": filtered[resolved["straatnaam_id"]].fillna("").astype(str).str.strip(),
            "huisnummer": _normalize_text_number(filtered[resolved["huisnummer"]]),
            "busnummer": _normalize_text_number(filtered[resolved["busnummer"]]),
        },
        geometry=filtered.geometry,
        crs=gdf.crs,
    )

    # Keep 1 row per stable adres_id
    before_dedup = len(out)
    out = out.drop_duplicates(subset=["adres_id"], keep="first").reset_index(drop=True)
    dup_ids_removed = before_dedup - len(out)

    # Check missing/empty geometries
    missing_geom_mask = out.geometry.isna() | out.geometry.is_empty
    missing_geom_count = int(missing_geom_mask.sum())
    valid = out.loc[~missing_geom_mask].copy().reset_index(drop=True)

    # Normalize MultiPoint -> Point
    norm_geom, mp_gt1 = _normalize_to_points(valid.geometry)
    valid = valid.set_geometry(norm_geom)

    # Detect duplicate active address labels with distinct adres_ids
    label_cols = ["nis_code", "gemeente", "straatnaam_id", "huisnummer", "busnummer"]
    dup_label_mask = valid.duplicated(subset=label_cols, keep=False)
    duplicate_labels = valid.loc[dup_label_mask, ["adres_id", *label_cols]].copy()
    dup_groups = (
        int(duplicate_labels.groupby(label_cols, dropna=False).ngroups)
        if len(duplicate_labels) > 0
        else 0
    )

    report = AddressFilterReport(
        total_raw_rows=total_raw,
        after_active_official_filter=after_filter,
        duplicate_adres_ids_removed=dup_ids_removed,
        missing_geometry_count=missing_geom_count,
        multipoint_gt1_count=mp_gt1,
        valid_geometry_count=len(valid),
        duplicate_active_labels_count=len(duplicate_labels),
        duplicate_active_label_groups=dup_groups,
    )
    return valid, duplicate_labels, report
