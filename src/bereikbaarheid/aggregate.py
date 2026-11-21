"""Weighted accessibility aggregation for Flanders, provinces, municipalities, and destinations."""

from __future__ import annotations

import numpy as np
import pandas as pd

NIS_PREFIX_TO_PROVINCE: dict[str, str] = {
    "1": "Antwerpen",
    "2": "Vlaams-Brabant",
    "3": "West-Vlaanderen",
    "4": "Oost-Vlaanderen",
    "7": "Limburg",
}


def province_from_nis(nis_code: str) -> str:
    s = str(nis_code).strip()
    return NIS_PREFIX_TO_PROVINCE.get(s[:1], "Onbekend")


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """First value where cumulative weight reaches at least q * total_weight (Uitvoeringsplan §6)."""
    if len(values) == 0:
        return float("nan")
    total_w = float(np.sum(weights))
    if total_w <= 0:
        return float("nan")
    order = np.argsort(values, kind="mergesort")
    v_sorted = values[order]
    w_sorted = weights[order]
    cum_w = np.cumsum(w_sorted, dtype=np.float64)
    threshold = q * total_w - 1e-12
    idx = int(np.searchsorted(cum_w, threshold, side="left"))
    idx = min(idx, len(v_sorted) - 1)
    return float(v_sorted[idx])


def _aggregate_group(df: pd.DataFrame, weight_col: str) -> dict:
    """Compute accessibility metrics for one group (Flanders, province, or municipality)."""
    n_selected = int(df[weight_col].sum())
    ok_mask = df["status"] == "ok"
    no_route_mask = df["status"] == "no_route"
    api_err_mask = df["status"] == "api_error"

    n_valid = int(df.loc[ok_mask, weight_col].sum())
    n_no_route = int(df.loc[no_route_mask, weight_col].sum())
    n_api_error = int(df.loc[api_err_mask, weight_col].sum())
    coverage_pct = (100.0 * n_valid / n_selected) if n_selected > 0 else float("nan")

    if n_valid == 0:
        return {
            "n_selected": n_selected,
            "n_valid_route": 0,
            "n_no_route": n_no_route,
            "n_api_error": n_api_error,
            "routing_coverage_pct": coverage_pct,
            "mean_duration_min": float("nan"),
            "median_duration_min": float("nan"),
            "p90_duration_min": float("nan"),
            "pct_within_15_min": float("nan"),
            "pct_within_30_min": float("nan"),
            "pct_within_45_min": float("nan"),
            "mean_distance_km": float("nan"),
            "median_distance_km": float("nan"),
            "top_destination_id": None,
            "top_destination_share_pct": float("nan"),
        }

    ok = df.loc[ok_mask]
    w = ok[weight_col].to_numpy(dtype=np.float64)
    dur_min = ok["duration_s"].to_numpy(dtype=np.float64) / 60.0
    dist_km = ok["distance_m"].to_numpy(dtype=np.float64) / 1000.0

    valid_dist = np.isfinite(dist_km)
    mean_dist = (
        float(np.average(dist_km[valid_dist], weights=w[valid_dist]))
        if np.any(valid_dist)
        else float("nan")
    )
    median_dist = (
        weighted_quantile(dist_km[valid_dist], w[valid_dist], 0.50)
        if np.any(valid_dist)
        else float("nan")
    )

    top_dest_id: str | None = None
    top_dest_share = float("nan")
    if "best_destination_id" in ok.columns and ok["best_destination_id"].notna().any():
        by_dest = ok.groupby("best_destination_id", sort=True)[weight_col].sum()
        # Deterministic tie-break on destination_id (index sorted ascending)
        max_w = by_dest.max()
        top_dest_id = str(by_dest[by_dest == max_w].index[0])
        top_dest_share = 100.0 * float(max_w) / n_valid

    return {
        "n_selected": n_selected,
        "n_valid_route": n_valid,
        "n_no_route": n_no_route,
        "n_api_error": n_api_error,
        "routing_coverage_pct": coverage_pct,
        "mean_duration_min": float(np.average(dur_min, weights=w)),
        "median_duration_min": weighted_quantile(dur_min, w, 0.50),
        "p90_duration_min": weighted_quantile(dur_min, w, 0.90),
        "pct_within_15_min": 100.0 * float(np.sum(w[dur_min <= 15.0])) / n_valid,
        "pct_within_30_min": 100.0 * float(np.sum(w[dur_min <= 30.0])) / n_valid,
        "pct_within_45_min": 100.0 * float(np.sum(w[dur_min <= 45.0])) / n_valid,
        "mean_distance_km": mean_dist,
        "median_distance_km": median_dist,
        "top_destination_id": top_dest_id,
        "top_destination_share_pct": top_dest_share,
    }


def _prepare_merged_weights(
    address_origin_map: pd.DataFrame,
    origin_results: pd.DataFrame,
    variant: str,
) -> pd.DataFrame:
    if variant == "main":
        subset = address_origin_map.loc[address_origin_map["in_main_analysis"]]
    elif variant == "no_bus_variant":
        subset = address_origin_map.loc[address_origin_map["in_no_bus_variant"]]
    else:
        raise ValueError(f"Onbekende variant: {variant!r}. Gebruik 'main' of 'no_bus_variant'.")

    mun_origin_weights = (
        subset.groupby(["nis_code", "gemeente", "origin_id"], dropna=False)
        .size()
        .reset_index(name="weight")
    )

    cols = ["origin_id", "status", "duration_s", "distance_m"]
    if "best_destination_id" in origin_results.columns:
        cols.append("best_destination_id")

    merged = mun_origin_weights.merge(
        origin_results[cols],
        on="origin_id",
        how="left",
        validate="many_to_one",
    )
    merged["status"] = merged["status"].fillna("api_error")
    merged["provincie"] = merged["nis_code"].map(province_from_nis)
    return merged


def aggregate_accessibility(
    address_origin_map: pd.DataFrame,
    origin_results: pd.DataFrame,
    variant: str = "main",
    destinations_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute Flanders-wide and per-municipality accessibility tables for 'main' or 'no_bus_variant'."""
    merged = _prepare_merged_weights(address_origin_map, origin_results, variant)

    dest_name_map: dict[str, str] = {}
    if destinations_df is not None and {"destination_id", "name"}.issubset(destinations_df.columns):
        dest_name_map = dict(
            zip(
                destinations_df["destination_id"].astype(str),
                destinations_df["name"].astype(str),
                strict=True,
            )
        )

    flanders_row = {"scope": "Vlaams Gewest", "variant": variant, **_aggregate_group(merged, "weight")}
    flanders_row["top_destination_name"] = dest_name_map.get(str(flanders_row["top_destination_id"]), "")
    flanders_df = pd.DataFrame([flanders_row])

    mun_rows: list[dict] = []
    for (nis_code, gemeente), grp in merged.groupby(["nis_code", "gemeente"], dropna=False, sort=True):
        stats = _aggregate_group(grp, "weight")
        mun_rows.append(
            {
                "nis_code": nis_code,
                "gemeente": gemeente,
                "provincie": province_from_nis(str(nis_code)),
                "variant": variant,
                **stats,
                "top_destination_name": dest_name_map.get(str(stats["top_destination_id"]), ""),
            }
        )
    municipalities_df = pd.DataFrame(mun_rows)
    return flanders_df, municipalities_df


def aggregate_by_province(
    address_origin_map: pd.DataFrame,
    origin_results: pd.DataFrame,
    variant: str = "main",
) -> pd.DataFrame:
    """Compute weighted accessibility statistics per Flemish province."""
    merged = _prepare_merged_weights(address_origin_map, origin_results, variant)
    rows: list[dict] = []
    for prov, grp in merged.groupby("provincie", sort=True):
        rows.append({"provincie": prov, "variant": variant, **_aggregate_group(grp, "weight")})
    return pd.DataFrame(rows).sort_values("median_duration_min", na_position="last").reset_index(drop=True)


def aggregate_by_destination(
    address_origin_map: pd.DataFrame,
    origin_results: pd.DataFrame,
    destinations_df: pd.DataFrame,
    variant: str = "main",
) -> pd.DataFrame:
    """Compute catchment size (address count, share, median duration/distance) per destination."""
    merged = _prepare_merged_weights(address_origin_map, origin_results, variant)
    ok = merged.loc[merged["status"] == "ok"].copy()
    total_valid = int(ok["weight"].sum())

    rows: list[dict] = []
    for _, drow in destinations_df.iterrows():
        did = str(drow["destination_id"])
        sub = ok.loc[ok["best_destination_id"].astype(str) == did]
        n_addr = int(sub["weight"].sum())
        if n_addr > 0:
            w = sub["weight"].to_numpy(dtype=np.float64)
            dur = sub["duration_s"].to_numpy(dtype=np.float64) / 60.0
            dist = sub["distance_m"].to_numpy(dtype=np.float64) / 1000.0
            med_dur = weighted_quantile(dur, w, 0.50)
            p90_dur = weighted_quantile(dur, w, 0.90)
            med_dist = weighted_quantile(dist, w, 0.50)
        else:
            med_dur = p90_dur = med_dist = float("nan")

        rows.append(
            {
                "destination_id": did,
                "name": str(drow["name"]),
                "n_addresses_fastest": n_addr,
                "share_of_valid_pct": (100.0 * n_addr / total_valid) if total_valid > 0 else 0.0,
                "median_duration_min": med_dur,
                "p90_duration_min": p90_dur,
                "median_distance_km": med_dist,
            }
        )
    return pd.DataFrame(rows).sort_values("n_addresses_fastest", ascending=False).reset_index(drop=True)


def compare_variants(flanders_main: pd.DataFrame, flanders_var: pd.DataFrame) -> pd.DataFrame:
    """Compare main analysis vs no-bus variant (Uitvoeringsplan §5)."""
    m = flanders_main.iloc[0]
    v = flanders_var.iloc[0]
    return pd.DataFrame(
        [
            {
                "n_selected_main": int(m["n_selected"]),
                "n_selected_no_bus_variant": int(v["n_selected"]),
                "n_addresses_changed": int(m["n_selected"] - v["n_selected"]),
                "mean_duration_diff_min": float(v["mean_duration_min"] - m["mean_duration_min"]),
                "p90_duration_diff_min": float(v["p90_duration_min"] - m["p90_duration_min"]),
                "pct_within_30_min_diff": float(v["pct_within_30_min"] - m["pct_within_30_min"]),
            }
        ]
    )
