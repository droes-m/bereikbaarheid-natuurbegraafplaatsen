"""Destination loading, validation, overrides, and OSRM snapping checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd
from pyproj import Transformer

from bereikbaarheid.config import CRS_LAMBERT72, CRS_WGS84

# Generous bounding box covering Flanders + border buffer in WGS 84
FLANDERS_BBOX_WGS84 = (2.4, 50.6, 6.0, 51.6)


@dataclass(frozen=True)
class DestinationValidationReport:
    total_rows: int
    unique_destinations: int
    unique_entrances: int
    duplicate_entrance_ids: list[str]
    out_of_bbox_ids: list[str]
    overrides_applied: int


def load_destinations(
    csv_path: Path,
    overrides_path: Path | None = None,
) -> tuple[pd.DataFrame, DestinationValidationReport]:
    """Load and validate destination points, optionally applying documented entrance overrides.

    Expected columns in ANB CSV:
      terra_id (or destination_id), naam (or name), lon_wgs84, lat_wgs84,
      optional entrance_id, optional x_lambert72, y_lambert72.
    """
    df = pd.read_csv(csv_path, dtype={"terra_id": str, "destination_id": str, "entrance_id": str})

    if "destination_id" not in df.columns:
        if "terra_id" in df.columns:
            df["destination_id"] = df["terra_id"].astype(str).str.strip()
        else:
            raise ValueError("Bestemmingsbestand mist een stabiele ID-kolom ('destination_id' of 'terra_id').")
    else:
        df["destination_id"] = df["destination_id"].astype(str).str.strip()

    if "name" not in df.columns:
        if "naam" in df.columns:
            df["name"] = df["naam"].astype(str).str.strip()
        else:
            df["name"] = df["destination_id"]

    if "entrance_id" not in df.columns:
        df["entrance_id"] = df["destination_id"]
    else:
        df["entrance_id"] = df["entrance_id"].fillna(df["destination_id"]).astype(str).str.strip()

    # Resolve WGS84 coordinates
    if {"lon_wgs84", "lat_wgs84"}.issubset(df.columns):
        df["lon"] = df["lon_wgs84"].astype(float)
        df["lat"] = df["lat_wgs84"].astype(float)
    elif {"lon", "lat"}.issubset(df.columns):
        df["lon"] = df["lon"].astype(float)
        df["lat"] = df["lat"].astype(float)
    elif {"x_lambert72", "y_lambert72"}.issubset(df.columns):
        transformer = Transformer.from_crs(CRS_LAMBERT72, CRS_WGS84, always_xy=True)
        lon, lat = transformer.transform(
            df["x_lambert72"].astype(float).to_numpy(),
            df["y_lambert72"].astype(float).to_numpy(),
        )
        df["lon"] = lon
        df["lat"] = lat
    else:
        raise ValueError("Bestemmingsbestand mist coördinaatkolommen (lon_wgs84/lat_wgs84 of x_lambert72/y_lambert72).")

    if df["destination_id"].isna().any() or (df["destination_id"] == "").any():
        raise ValueError("Bestemmingsbestand bevat lege destination_id's.")
    if df["lon"].isna().any() or df["lat"].isna().any():
        raise ValueError("Bestemmingsbestand bevat ontbrekende coördinaten.")

    df["orig_lon"] = df["lon"]
    df["orig_lat"] = df["lat"]
    df["override_reason"] = ""
    overrides_applied = 0

    if overrides_path is not None and overrides_path.exists():
        ov = pd.read_csv(
            overrides_path,
            dtype={"destination_id": str, "entrance_id": str, "reason": str},
        )
        for _, row in ov.iterrows():
            mask = df["entrance_id"] == str(row["entrance_id"]).strip()
            if mask.any():
                df.loc[mask, "lon"] = float(row["new_lon"])
                df.loc[mask, "lat"] = float(row["new_lat"])
                df.loc[mask, "override_reason"] = str(row.get("reason", ""))
                overrides_applied += int(mask.sum())

    dup_mask = df["entrance_id"].duplicated(keep=False)
    duplicate_entrance_ids = sorted(df.loc[dup_mask, "entrance_id"].unique().tolist())

    min_lon, min_lat, max_lon, max_lat = FLANDERS_BBOX_WGS84
    out_bbox_mask = ~(
        df["lon"].between(min_lon, max_lon) & df["lat"].between(min_lat, max_lat)
    )
    out_of_bbox_ids = df.loc[out_bbox_mask, "entrance_id"].tolist()

    # Deterministic order by (destination_id, entrance_id)
    df = df.sort_values(["destination_id", "entrance_id"]).reset_index(drop=True)

    report = DestinationValidationReport(
        total_rows=len(df),
        unique_destinations=int(df["destination_id"].nunique()),
        unique_entrances=int(df["entrance_id"].nunique()),
        duplicate_entrance_ids=duplicate_entrance_ids,
        out_of_bbox_ids=out_of_bbox_ids,
        overrides_applied=overrides_applied,
    )
    return df, report


def check_osrm_snapping(
    destinations: pd.DataFrame,
    osrm_base_url: str = "http://localhost:5000",
    timeout_s: float = 30.0,
) -> pd.DataFrame:
    """Query OSRM /nearest for each destination to inspect road snapping distance and road name."""
    records: list[dict] = []
    with httpx.Client(timeout=timeout_s) as client:
        for _, row in destinations.iterrows():
            url = f"{osrm_base_url.rstrip('/')}/nearest/v1/driving/{row['lon']:.7f},{row['lat']:.7f}"
            try:
                resp = client.get(url, params={"number": 1})
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") == "Ok" and data.get("waypoints"):
                    wp = data["waypoints"][0]
                    snapped_lon, snapped_lat = wp["location"]
                    records.append(
                        {
                            "destination_id": row["destination_id"],
                            "entrance_id": row["entrance_id"],
                            "name": row["name"],
                            "input_lon": row["lon"],
                            "input_lat": row["lat"],
                            "snapped_lon": snapped_lon,
                            "snapped_lat": snapped_lat,
                            "snap_distance_m": float(wp.get("distance", float("nan"))),
                            "snapped_road": wp.get("name", ""),
                            "status": "ok",
                        }
                    )
                else:
                    records.append(
                        {
                            "destination_id": row["destination_id"],
                            "entrance_id": row["entrance_id"],
                            "name": row["name"],
                            "input_lon": row["lon"],
                            "input_lat": row["lat"],
                            "snapped_lon": float("nan"),
                            "snapped_lat": float("nan"),
                            "snap_distance_m": float("nan"),
                            "snapped_road": "",
                            "status": f"osrm_{data.get('code', 'unknown')}",
                        }
                    )
            except (httpx.HTTPError, ValueError) as exc:
                records.append(
                    {
                        "destination_id": row["destination_id"],
                        "entrance_id": row["entrance_id"],
                        "name": row["name"],
                        "input_lon": row["lon"],
                        "input_lat": row["lat"],
                        "snapped_lon": float("nan"),
                        "snapped_lat": float("nan"),
                        "snap_distance_m": float("nan"),
                        "snapped_road": "",
                        "status": f"error:{type(exc).__name__}",
                    }
                )
    return pd.DataFrame(records)
