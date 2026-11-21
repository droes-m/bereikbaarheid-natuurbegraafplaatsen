"""Reproducible geographically stratified pilot sampling (Uitvoeringsplan §5)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def stratified_pilot_sample(
    address_origin_map: pd.DataFrame,
    target_n: int = 10_000,
    seed: int = 42,
) -> pd.DataFrame:
    """Create a reproducible geographically distributed sample across all municipalities.

    Allocates at least 1 address per municipality (when target_n >= n_municipalities)
    and distributes the remaining sample proportionally to each municipality's address count,
    ensuring urban centers, residential areas, rural municipalities, and border municipalities
    are all represented.
    """
    if len(address_origin_map) <= target_n:
        return address_origin_map.copy().reset_index(drop=True)

    rng = np.random.default_rng(seed)
    counts = (
        address_origin_map.groupby(["nis_code", "gemeente"], sort=True)
        .size()
        .reset_index(name="n_total")
    )
    n_mun = len(counts)
    total = int(counts["n_total"].sum())

    # Proportional allocation with floor 1 per municipality
    raw_alloc = np.floor(counts["n_total"].to_numpy() / total * target_n).astype(int)
    if target_n >= n_mun:
        raw_alloc = np.maximum(raw_alloc, 1)
    raw_alloc = np.minimum(raw_alloc, counts["n_total"].to_numpy())

    # Adjust to hit target_n as closely as possible
    diff = target_n - int(raw_alloc.sum())
    if diff > 0:
        room = counts["n_total"].to_numpy() - raw_alloc
        order = np.argsort(-room, kind="mergesort")
        for idx in order:
            if diff <= 0:
                break
            add = min(diff, int(room[idx]))
            raw_alloc[idx] += add
            diff -= add
    elif diff < 0:
        excess = raw_alloc - 1
        order = np.argsort(-excess, kind="mergesort")
        for idx in order:
            if diff >= 0:
                break
            sub = min(-diff, int(excess[idx]))
            raw_alloc[idx] -= sub
            diff += sub

    counts["n_sample"] = raw_alloc
    alloc_map = dict(
        zip(
            zip(counts["nis_code"], counts["gemeente"], strict=True),
            counts["n_sample"],
            strict=True,
        )
    )

    parts: list[pd.DataFrame] = []
    for key, grp in address_origin_map.groupby(["nis_code", "gemeente"], sort=True):
        k = alloc_map.get(key, 0)
        if k <= 0:
            continue
        if k >= len(grp):
            parts.append(grp)
        else:
            idx = rng.choice(len(grp), size=k, replace=False)
            parts.append(grp.iloc[np.sort(idx)])

    return pd.concat(parts, ignore_index=True)
