"""Project paths and reproducible run configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

CRS_LAMBERT72 = "EPSG:31370"
CRS_WGS84 = "EPSG:4326"


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def data_raw(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def data_interim(self) -> Path:
        return self.root / "data" / "interim"

    @property
    def data_osrm(self) -> Path:
        return self.root / "data" / "osrm"

    @property
    def data_processed(self) -> Path:
        return self.root / "data" / "processed"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_raw,
            self.data_interim,
            self.data_osrm,
            self.data_processed,
            self.outputs,
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class RunConfig:
    osrm_base_url: str = "http://localhost:5000"
    osrm_profile: str = "car"
    osrm_algorithm: str = "ch"
    batch_size: int = 200
    dest_chunk_size: int = 50
    timeout_s: float = 60.0
    destinations_version: str = "anb_layer55_2026-11-21"
    osm_extract: str = "belgium-latest"

    def run_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:12]
