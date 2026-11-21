"""Local OSRM Table API batch routing with deterministic selection and resumable checkpoints."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from tqdm import tqdm

from bereikbaarheid.config import RunConfig


@dataclass(frozen=True)
class RoutingRunMetrics:
    total_origins: int
    cached_origins: int
    newly_routed_origins: int
    ok_count: int
    no_route_count: int
    api_error_count: int
    elapsed_seconds: float
    origins_per_second: float


def select_best_from_matrices(
    durations: list[list[float | None]],
    distances: list[list[float | None]],
    destination_ids: list[str],
    entrance_ids: list[str],
    source_snap_distances: list[float | None],
    dest_snap_distances: list[float | None],
) -> list[dict]:
    """Select lowest duration per origin, taking distance from the exact same cell.

    Tie-breaking: deterministic on (destination_id, entrance_id).
    A row with all null/non-finite durations gets status='no_route'.
    """
    results: list[dict] = []
    for i, dur_row in enumerate(durations):
        dist_row = distances[i]
        best_dur: float | None = None
        best_dist: float | None = None
        best_dest_id: str | None = None
        best_ent_id: str | None = None
        best_dest_snap: float | None = None

        for j, raw_dur in enumerate(dur_row):
            if raw_dur is None:
                continue
            dur = float(raw_dur)
            if not np.isfinite(dur):
                continue

            d_id = destination_ids[j]
            e_id = entrance_ids[j]
            raw_dist = dist_row[j] if j < len(dist_row) else None
            dist = float(raw_dist) if raw_dist is not None and np.isfinite(float(raw_dist)) else float("nan")

            if best_dur is None or dur < best_dur or (
                dur == best_dur and (d_id, e_id) < (best_dest_id, best_ent_id)
            ):
                best_dur = dur
                best_dist = dist
                best_dest_id = d_id
                best_ent_id = e_id
                best_dest_snap = (
                    float(dest_snap_distances[j])
                    if j < len(dest_snap_distances) and dest_snap_distances[j] is not None
                    else float("nan")
                )

        src_snap = (
            float(source_snap_distances[i])
            if i < len(source_snap_distances) and source_snap_distances[i] is not None
            else float("nan")
        )

        if best_dur is None:
            results.append(
                {
                    "status": "no_route",
                    "duration_s": float("nan"),
                    "distance_m": float("nan"),
                    "best_destination_id": None,
                    "best_entrance_id": None,
                    "source_snap_distance_m": src_snap,
                    "dest_snap_distance_m": float("nan"),
                    "error_detail": "",
                }
            )
        else:
            results.append(
                {
                    "status": "ok",
                    "duration_s": best_dur,
                    "distance_m": best_dist,
                    "best_destination_id": best_dest_id,
                    "best_entrance_id": best_ent_id,
                    "source_snap_distance_m": src_snap,
                    "dest_snap_distance_m": best_dest_snap,
                    "error_detail": "",
                }
            )
    return results


def _query_osrm_table_chunk(
    client: httpx.Client,
    osrm_base_url: str,
    origins_chunk: pd.DataFrame,
    dests_chunk: pd.DataFrame,
) -> dict:
    """Execute a single OSRM Table API query with annotations=duration,distance (no fallback_speed)."""
    src_coords = [
        f"{lon:.7f},{lat:.7f}"
        for lon, lat in zip(origins_chunk["lon"], origins_chunk["lat"], strict=True)
    ]
    dst_coords = [
        f"{lon:.7f},{lat:.7f}"
        for lon, lat in zip(dests_chunk["lon"], dests_chunk["lat"], strict=True)
    ]
    n_src = len(src_coords)
    n_dst = len(dst_coords)

    coords_str = ";".join(src_coords + dst_coords)
    sources_param = ";".join(str(i) for i in range(n_src))
    dests_param = ";".join(str(n_src + j) for j in range(n_dst))

    url = f"{osrm_base_url.rstrip('/')}/table/v1/driving/{coords_str}"
    resp = client.get(
        url,
        params={
            "sources": sources_param,
            "destinations": dests_param,
            "annotations": "duration,distance",
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "Ok":
        raise RuntimeError(f"OSRM error code={payload.get('code')}: {payload.get('message', '')}")
    if "durations" not in payload or "distances" not in payload:
        raise RuntimeError(
            "OSRM response mist 'durations' of 'distances' (controleer annotations=duration,distance)."
        )
    return payload


def _route_batch_with_split(
    client: httpx.Client,
    osrm_base_url: str,
    origins_batch: pd.DataFrame,
    destinations: pd.DataFrame,
    dest_chunk_size: int,
) -> list[dict]:
    """Route an origin batch against all destination chunks, splitting recursively on API errors."""
    n_origins = len(origins_batch)
    merged: list[dict | None] = [None] * n_origins

    try:
        for d_start in range(0, len(destinations), dest_chunk_size):
            d_chunk = destinations.iloc[d_start : d_start + dest_chunk_size]
            payload = _query_osrm_table_chunk(client, osrm_base_url, origins_batch, d_chunk)
            src_snaps = [wp.get("distance") for wp in payload.get("sources", [])]
            dst_snaps = [wp.get("distance") for wp in payload.get("destinations", [])]
            chunk_res = select_best_from_matrices(
                durations=payload["durations"],
                distances=payload["distances"],
                destination_ids=d_chunk["destination_id"].tolist(),
                entrance_ids=d_chunk["entrance_id"].tolist(),
                source_snap_distances=src_snaps,
                dest_snap_distances=dst_snaps,
            )
            for i, cand in enumerate(chunk_res):
                cur = merged[i]
                if cur is None or (
                    cand["status"] == "ok"
                    and (
                        cur["status"] != "ok"
                        or cand["duration_s"] < cur["duration_s"]
                        or (
                            cand["duration_s"] == cur["duration_s"]
                            and (cand["best_destination_id"], cand["best_entrance_id"])
                            < (cur["best_destination_id"], cur["best_entrance_id"])
                        )
                    )
                ):
                    merged[i] = cand

        rows: list[dict] = []
        for origin_id, res in zip(origins_batch["origin_id"].tolist(), merged, strict=True):
            assert res is not None
            rows.append({"origin_id": origin_id, **res})
        return rows

    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        if n_origins == 1:
            return [
                {
                    "origin_id": origins_batch["origin_id"].iloc[0],
                    "status": "api_error",
                    "duration_s": float("nan"),
                    "distance_m": float("nan"),
                    "best_destination_id": None,
                    "best_entrance_id": None,
                    "source_snap_distance_m": float("nan"),
                    "dest_snap_distance_m": float("nan"),
                    "error_detail": f"{type(exc).__name__}: {exc}",
                }
            ]
        mid = n_origins // 2
        left = _route_batch_with_split(
            client, osrm_base_url, origins_batch.iloc[:mid], destinations, dest_chunk_size
        )
        right = _route_batch_with_split(
            client, osrm_base_url, origins_batch.iloc[mid:], destinations, dest_chunk_size
        )
        return left + right


def route_origins_osrm(
    origins: pd.DataFrame,
    destinations: pd.DataFrame,
    config: RunConfig,
    cache_dir: Path,
    client: httpx.Client | None = None,
    workers: int = 6,
    checkpoint_rows: int = 20_000,
) -> tuple[pd.DataFrame, RoutingRunMetrics]:
    """Route all unique origins against all destinations with resumable Parquet checkpoints."""
    run_dir = cache_dir / config.run_hash()
    run_dir.mkdir(parents=True, exist_ok=True)
    meta_path = run_dir / "run_config.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps(config.__dict__, indent=2), encoding="utf-8")

    # Load any existing cached batches
    existing_files = sorted(run_dir.glob("batch_*.parquet"))
    cached_dfs = [pd.read_parquet(p) for p in existing_files]
    cached_df = pd.concat(cached_dfs, ignore_index=True) if cached_dfs else pd.DataFrame()
    cached_ids = set(cached_df["origin_id"].tolist()) if len(cached_df) > 0 else set()

    pending = origins.loc[~origins["origin_id"].isin(cached_ids)].reset_index(drop=True)
    destinations_sorted = destinations.sort_values(
        ["destination_id", "entrance_id"]
    ).reset_index(drop=True)

    next_chunk_idx = len(existing_files)
    new_dfs: list[pd.DataFrame] = []

    batches = [
        pending.iloc[start : start + config.batch_size]
        for start in range(0, len(pending), config.batch_size)
    ]

    t0 = time.perf_counter()
    if len(batches) > 0:
        buffer_rows: list[dict] = []

        def _flush() -> None:
            nonlocal next_chunk_idx
            if not buffer_rows:
                return
            chunk_df = pd.DataFrame(buffer_rows)
            chunk_path = run_dir / f"batch_{next_chunk_idx:06d}.parquet"
            chunk_df.to_parquet(chunk_path, index=False)
            new_dfs.append(chunk_df)
            buffer_rows.clear()
            next_chunk_idx += 1

        if client is not None or workers <= 1:
            owns_client = client is None
            active_client = httpx.Client(timeout=config.timeout_s) if owns_client else client
            try:
                for batch in tqdm(batches, desc="OSRM routering", unit="batch", disable=len(batches) < 5):
                    buffer_rows.extend(
                        _route_batch_with_split(
                            client=active_client,
                            osrm_base_url=config.osrm_base_url,
                            origins_batch=batch,
                            destinations=destinations_sorted,
                            dest_chunk_size=config.dest_chunk_size,
                        )
                    )
                    if len(buffer_rows) >= checkpoint_rows:
                        _flush()
                _flush()
            finally:
                if owns_client:
                    active_client.close()
        else:
            limits = httpx.Limits(max_connections=workers * 2, max_keepalive_connections=workers * 2)
            with httpx.Client(timeout=config.timeout_s, limits=limits) as shared_client:
                def _run_one(batch: pd.DataFrame) -> list[dict]:
                    return _route_batch_with_split(
                        client=shared_client,
                        osrm_base_url=config.osrm_base_url,
                        origins_batch=batch,
                        destinations=destinations_sorted,
                        dest_chunk_size=config.dest_chunk_size,
                    )

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for batch_rows in tqdm(
                        pool.map(_run_one, batches),
                        total=len(batches),
                        desc="OSRM routering",
                        unit="batch",
                    ):
                        buffer_rows.extend(batch_rows)
                        if len(buffer_rows) >= checkpoint_rows:
                            _flush()
                _flush()

    elapsed = time.perf_counter() - t0
    all_parts = [df for df in (cached_df, *new_dfs) if len(df) > 0]
    all_results = pd.concat(all_parts, ignore_index=True) if all_parts else pd.DataFrame()

    all_results = origins[["origin_id"]].merge(
        all_results.drop_duplicates(subset=["origin_id"], keep="last"),
        on="origin_id",
        how="left",
    )

    newly_routed = len(pending)
    metrics = RoutingRunMetrics(
        total_origins=len(origins),
        cached_origins=len(origins) - newly_routed,
        newly_routed_origins=newly_routed,
        ok_count=int((all_results["status"] == "ok").sum()),
        no_route_count=int((all_results["status"] == "no_route").sum()),
        api_error_count=int((all_results["status"] == "api_error").sum()),
        elapsed_seconds=round(elapsed, 3),
        origins_per_second=round(newly_routed / elapsed, 2)
        if elapsed > 0 and newly_routed > 0
        else 0.0,
    )
    return all_results, metrics
