"""Reporting outputs: summary tables, municipality choropleth map, and method note."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd


def write_summary_tables(
    flanders_main: pd.DataFrame,
    municipalities_main: pd.DataFrame,
    variant_diff: pd.DataFrame,
    output_dir: Path,
    prefix: str = "",
) -> dict[str, Path]:
    """Write CSV and Markdown summary tables."""
    output_dir.mkdir(parents=True, exist_ok=True)
    p = f"{prefix}_" if prefix else ""

    paths = {
        "flanders_csv": output_dir / f"{p}vlaanderen_samenvatting.csv",
        "municipalities_csv": output_dir / f"{p}gemeenten_samenvatting.csv",
        "variant_diff_csv": output_dir / f"{p}busnummer_variant_verschil.csv",
        "summary_md": output_dir / f"{p}samenvatting.md",
    }

    flanders_main.to_csv(paths["flanders_csv"], index=False)
    municipalities_main.to_csv(paths["municipalities_csv"], index=False)
    variant_diff.to_csv(paths["variant_diff_csv"], index=False)

    f = flanders_main.iloc[0]
    v = variant_diff.iloc[0]
    md = f"""# Samenvatting bereikbaarheid natuurbegraafplaatsen in Vlaanderen

> **Opmerking:** Alle reistijden zijn geschatte autorijtijden zonder actuele verkeersinformatie (OSRM vast autoprofiel). De analyse-eenheid zijn **vermoedelijke woonadressen** (officiële actieve adressen uit het Vlaamse Adressenregister binnen de landgebruiksklasse *Huizen en tuinen*).

## Resultaten Vlaams Gewest (hoofdanalyse)

| Indicator | Waarde |
|---|---:|
| Geselecteerde vermoedelijke woonadressen | {int(f['n_selected']):,} |
| Geldige route | {int(f['n_valid_route']):,} |
| Geen route (`no_route`) | {int(f['n_no_route']):,} |
| Technische uitval (`api_error`) | {int(f['n_api_error']):,} |
| Routedekking (%) | {f['routing_coverage_pct']:.2f}% |
| Gewogen gemiddelde autorijtijd (min) | {f['mean_duration_min']:.2f} |
| Gewogen mediaan autorijtijd (min) | {f['median_duration_min']:.2f} |
| P90 autorijtijd (min) | {f['p90_duration_min']:.2f} |
| Aandeel binnen 15 min (%) | {f['pct_within_15_min']:.2f}% |
| Aandeel binnen 30 min (%) | {f['pct_within_30_min']:.2f}% |
| Aandeel binnen 45 min (%) | {f['pct_within_45_min']:.2f}% |
| Gewogen gemiddelde rijafstand (km) | {f['mean_distance_km']:.2f} |
| Gewogen mediaan rijafstand (km) | {f['median_distance_km']:.2f} |

## Gevoeligheidsanalyse: busnummervariant

| Indicator | Verschil (variant − hoofd) |
|---|---:|
| Aantal weggevallen adressen zonder bus naast geselecteerde busadressen | {int(v['n_addresses_changed']):,} |
| Verschil gemiddelde reistijd (min) | {v['mean_duration_diff_min']:+.3f} |
| Verschil P90 reistijd (min) | {v['p90_duration_diff_min']:+.3f} |
| Verschil aandeel binnen 30 min (procentpunt) | {v['pct_within_30_min_diff']:+.3f} |

---
*Bronnen: © OpenStreetMap contributors (OSRM), Vlaams Adressenregister (Digitaal Vlaanderen), Landgebruikskaart Vlaanderen 2025 (Departement Omgeving), Natuurbegraafplekken (Agentschap voor Natuur en Bos, laag 55).*
"""
    paths["summary_md"].write_text(md, encoding="utf-8")
    return paths


def render_municipality_map(
    municipalities_df: pd.DataFrame,
    boundaries_gdf: gpd.GeoDataFrame,
    destinations_df: pd.DataFrame,
    output_path: Path,
    nis_col: str = "NISCODE",
    metric_col: str = "median_duration_min",
    title: str = "Bereikbaarheid natuurbegraafplaatsen in Vlaanderen (mediaan autorijtijd per gemeente)",
) -> Path:
    """Render a publication-ready municipality choropleth map with destination points and attribution."""
    b = boundaries_gdf.copy()
    b["nis_key"] = b[nis_col].astype(str).str.strip()
    m = municipalities_df.copy()
    m["nis_key"] = m["nis_code"].astype(str).str.strip()

    merged = b.merge(m, on="nis_key", how="left")
    dest_gdf = gpd.GeoDataFrame(
        destinations_df.copy(),
        geometry=gpd.points_from_xy(destinations_df["lon"], destinations_df["lat"]),
        crs="EPSG:4326",
    ).to_crs(merged.crs)

    fig, ax = plt.subplots(figsize=(14, 7.5), dpi=200)
    merged.plot(
        column=metric_col,
        ax=ax,
        cmap="YlOrRd",
        edgecolor="#555555",
        linewidth=0.35,
        legend=True,
        legend_kwds={"label": "Autorijtijd (minuten)", "shrink": 0.72},
        missing_kwds={"color": "#e0e0e0", "label": "Geen geldige route"},
    )
    dest_gdf.plot(
        ax=ax,
        color="#0b5345",
        edgecolor="white",
        linewidth=0.9,
        markersize=55,
        marker="o",
        zorder=5,
        label="Natuurbegraafplek (ANB, n=19)",
    )

    ax.set_title(title, fontsize=13, fontweight="bold", pad=12)
    ax.set_axis_off()
    ax.legend(loc="lower left", frameon=True, facecolor="white", framealpha=0.9)

    fig.text(
        0.01,
        0.01,
        "Geschatte autorijtijden vanaf vermoedelijke woonadressen zonder actuele verkeersinformatie. "
        "Bronnen: © OpenStreetMap contributors (OSRM) · Vlaams Adressenregister · Landgebruikskaart 2025 · ANB (laag 55).",
        fontsize=8,
        color="#444444",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path
