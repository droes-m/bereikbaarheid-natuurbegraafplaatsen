"""Publication-grade static charts/maps and interactive Leaflet HTML map."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bereikbaarheid.aggregate import province_from_nis

FOOTER_NOTE = (
    "Geschatte autorijtijden vanaf vermoedelijke woonadressen zonder actuele verkeersinformatie (OSRM car.lua). "
    "Bronnen: © OpenStreetMap contributors · Vlaams Adressenregister · Landgebruikskaart 2025 · ANB (laag 55)."
)

PROVINCE_COLORS: dict[str, str] = {
    "Antwerpen": "#1b9e77",
    "Vlaams-Brabant": "#386cb0",
    "Limburg": "#e6ab02",
    "Oost-Vlaanderen": "#d95f02",
    "West-Vlaanderen": "#e7298a",
}

DURATION_BINS = [0, 15, 25, 35, 45, 60, 120]
DURATION_LABELS = ["≤ 15 min", "15–25 min", "25–35 min", "35–45 min", "45–60 min", "> 60 min"]
DURATION_COLORS = ["#1a9850", "#91cf60", "#d9ef8b", "#fee08b", "#fc8d59", "#d73027"]

DISTANCE_BINS = [0, 10, 20, 30, 50, 80, 200]
DISTANCE_LABELS = ["≤ 10 km", "10–20 km", "20–30 km", "30–50 km", "50–80 km", "> 80 km"]
DISTANCE_COLORS = ["#1a9850", "#91cf60", "#d9ef8b", "#fee08b", "#fc8d59", "#d73027"]


def _short_dest_name(name: str) -> str:
    return name.replace("Natuurbegraafplek ", "").strip()


def _style_axes() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Helvetica", "Arial"],
            "axes.edgecolor": "#cccccc",
            "axes.linewidth": 0.8,
        }
    )


def render_travel_time_maps(
    municipalities_df: pd.DataFrame,
    boundaries_gdf: gpd.GeoDataFrame,
    destinations_df: pd.DataFrame,
    output_dir: Path,
    provinces_gdf: gpd.GeoDataFrame | None = None,
    nis_col: str = "NISCODE",
    prefix: str = "",
) -> dict[str, Path]:
    """Render side-by-side median & P90 choropleth map plus discrete-class median map."""
    _style_axes()
    output_dir.mkdir(parents=True, exist_ok=True)
    p = f"{prefix}_" if prefix else ""

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
    prov_proj = provinces_gdf.to_crs(merged.crs) if provinces_gdf is not None else None

    cmap = mcolors.ListedColormap(DURATION_COLORS)
    norm = mcolors.BoundaryNorm(DURATION_BINS, cmap.N)

    # 1. Dual panel: Mediaan vs P90
    fig, axes = plt.subplots(1, 2, figsize=(18, 6.8), dpi=220)
    panels = [
        (axes[0], "median_duration_min", "Mediaan autorijtijd (min)"),
        (axes[1], "p90_duration_min", "P90 autorijtijd (min)"),
    ]
    for ax, col, subtitle in panels:
        merged.plot(
            column=col,
            ax=ax,
            cmap=cmap,
            norm=norm,
            edgecolor="#ffffff",
            linewidth=0.35,
            missing_kwds={"color": "#dddddd"},
        )
        if prov_proj is not None:
            prov_proj.boundary.plot(ax=ax, edgecolor="#333333", linewidth=1.0, zorder=3)
        dest_gdf.plot(
            ax=ax,
            color="#0b3d2e",
            edgecolor="white",
            linewidth=0.9,
            markersize=48,
            marker="o",
            zorder=5,
        )
        ax.set_title(subtitle, fontsize=13, fontweight="bold", pad=8)
        ax.set_axis_off()

    legend_handles = [
        mpatches.Patch(facecolor=c, edgecolor="#888888", label=lbl)
        for c, lbl in zip(DURATION_COLORS, DURATION_LABELS, strict=True)
    ]
    legend_handles.append(
        plt.Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor="#0b3d2e",
            markeredgecolor="white",
            markersize=8,
            label=f"Natuurbegraafplek (ANB, n={len(destinations_df)})",
        )
    )
    fig.legend(
        handles=legend_handles,
        loc="lower center",
        ncol=len(legend_handles),
        frameon=True,
        facecolor="white",
        edgecolor="#dddddd",
        fontsize=9.5,
        bbox_to_anchor=(0.5, 0.06),
    )
    fig.suptitle(
        "Autorijtijd vanaf vermoedelijke woonadressen naar de snelst bereikbare natuurbegraafplaats in Vlaanderen",
        fontsize=15,
        fontweight="bold",
        y=0.98,
    )
    fig.text(0.5, 0.012, FOOTER_NOTE, ha="center", fontsize=8.5, color="#555555")
    plt.tight_layout(rect=[0, 0.11, 1, 0.94])

    dual_path = output_dir / f"{p}kaart_mediaan_en_p90.png"
    fig.savefig(dual_path, bbox_inches="tight")
    plt.close(fig)

    # 2. Verzorgingsgebiedenkaart (dichtstbijzijnde natuurbegraafplaats per gemeente)
    fig, ax = plt.subplots(figsize=(14, 6.2), dpi=220)
    # Order destinations by number of addresses served descending
    dest_order = (
        merged.dropna(subset=["top_destination_id"])
        .groupby(merged["top_destination_id"].astype(str))["n_selected"]
        .sum()
        .sort_values(ascending=False)
        .index.tolist()
    )
    unique_dests = dest_order
    palette = plt.colormaps.get_cmap("tab20").resampled(max(len(unique_dests), 1))
    color_map = {did: mcolors.to_hex(palette(i)) for i, did in enumerate(unique_dests)}
    merged["catchment_color"] = merged["top_destination_id"].astype(str).map(color_map).fillna("#dddddd")

    merged.plot(
        color=merged["catchment_color"],
        ax=ax,
        edgecolor="#ffffff",
        linewidth=0.4,
    )
    if prov_proj is not None:
        prov_proj.boundary.plot(ax=ax, edgecolor="#222222", linewidth=1.1, zorder=3)
    dest_gdf.plot(
        ax=ax,
        color="#111111",
        edgecolor="white",
        linewidth=1.1,
        markersize=58,
        marker="o",
        zorder=5,
    )

    name_lookup = dict(
        zip(
            destinations_df["destination_id"].astype(str),
            destinations_df["name"].map(_short_dest_name),
            strict=True,
        )
    )
    handles = [
        mpatches.Patch(facecolor=color_map[did], edgecolor="#666666", label=name_lookup.get(did, did))
        for did in unique_dests
    ]
    ax.legend(
        handles=handles,
        title="Snelst bereikbare natuurbegraafplaats",
        loc="center left",
        bbox_to_anchor=(1.01, 0.5),
        frameon=True,
        facecolor="white",
        fontsize=8.5,
        title_fontsize=9.5,
    )
    ax.set_title(
        "Verzorgingsgebieden: snelst bereikbare natuurbegraafplaats per gemeente (autorijtijd)",
        fontsize=14,
        fontweight="bold",
        pad=10,
    )
    ax.set_axis_off()
    fig.text(0.01, 0.01, FOOTER_NOTE, fontsize=8, color="#555555")
    catchment_path = output_dir / f"{p}kaart_verzorgingsgebieden.png"
    fig.savefig(catchment_path, bbox_inches="tight")
    plt.close(fig)

    return {"dual_map": dual_path, "catchment_map": catchment_path}


def render_cdf_curve(
    address_origin_map: pd.DataFrame,
    origin_results: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Weighted cumulative accessibility curve for Flanders and each Flemish province."""
    _style_axes()
    subset = address_origin_map.loc[address_origin_map["in_main_analysis"]]
    weights = (
        subset.groupby(["nis_code", "origin_id"], dropna=False)
        .size()
        .reset_index(name="weight")
    )
    merged = weights.merge(
        origin_results[["origin_id", "status", "duration_s"]],
        on="origin_id",
        how="left",
    )
    ok = merged.loc[merged["status"] == "ok"].copy()
    ok["dur_min"] = ok["duration_s"] / 60.0
    ok["provincie"] = ok["nis_code"].map(province_from_nis)

    grid = np.linspace(0, 90, 361)

    fig, ax = plt.subplots(figsize=(11, 6.2), dpi=220)

    def _plot_curve(df: pd.DataFrame, label: str, color: str, lw: float, zorder: int) -> None:
        if len(df) == 0:
            return
        d = df["dur_min"].to_numpy(dtype=np.float64)
        w = df["weight"].to_numpy(dtype=np.float64)
        order = np.argsort(d)
        d_s = d[order]
        cum = np.cumsum(w[order]) / np.sum(w) * 100.0
        y = np.interp(grid, d_s, cum, left=0.0, right=100.0)
        ax.plot(grid, y, label=label, color=color, linewidth=lw, zorder=zorder)

    for prov, color in PROVINCE_COLORS.items():
        sub_p = ok.loc[ok["provincie"] == prov]
        if len(sub_p) > 0:
            pct30 = 100.0 * sub_p.loc[sub_p["dur_min"] <= 30.0, "weight"].sum() / sub_p["weight"].sum()
            _plot_curve(sub_p, f"{prov} ({pct30:.0f}% ≤ 30 min)", color, lw=2.0, zorder=3)

    pct30_fl = 100.0 * ok.loc[ok["dur_min"] <= 30.0, "weight"].sum() / ok["weight"].sum()
    _plot_curve(ok, f"Vlaams Gewest ({pct30_fl:.0f}% ≤ 30 min)", "#111111", lw=3.2, zorder=5)

    for thresh in (15, 30, 45):
        ax.axvline(thresh, color="#888888", linestyle="--", linewidth=0.9, zorder=1)
        pct_t = 100.0 * ok.loc[ok["dur_min"] <= thresh, "weight"].sum() / ok["weight"].sum()
        ax.scatter([thresh], [pct_t], color="#111111", s=35, zorder=6)
        ax.annotate(
            f"{thresh} min: {pct_t:.1f}%",
            xy=(thresh, pct_t),
            xytext=(thresh + 1.5, max(pct_t - 6, 4)),
            fontsize=9,
            fontweight="bold",
            color="#111111",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#cccccc", "alpha": 0.9},
        )

    ax.set_xlim(0, 90)
    ax.set_ylim(0, 102)
    ax.set_xlabel("Autorijtijd naar snelst bereikbare natuurbegraafplaats (minuten)", fontsize=11)
    ax.set_ylabel("Cumulatief aandeel vermoedelijke woonadressen (%)", fontsize=11)
    ax.set_title(
        "Cumulatieve bereikbaarheid van natuurbegraafplaatsen in Vlaanderen en per provincie",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="lower right", frameon=True, facecolor="white", fontsize=9.5)
    fig.text(0.01, -0.02, FOOTER_NOTE, fontsize=8, color="#555555")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_destination_catchment_chart(
    dest_summary: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Horizontal bar chart of how many residential addresses have each ANB site as their fastest option."""
    _style_axes()
    df = dest_summary.sort_values("n_addresses_fastest", ascending=True).copy()
    df["short_name"] = df["name"].map(_short_dest_name)

    fig, ax = plt.subplots(figsize=(11, 7.2), dpi=220)
    bars = ax.barh(df["short_name"], df["n_addresses_fastest"], color="#2b7a5b", edgecolor="none")

    max_v = max(float(df["n_addresses_fastest"].max()), 1.0)
    for bar, (_, row) in zip(bars, df.iterrows(), strict=True):
        val = int(row["n_addresses_fastest"])
        pct = float(row["share_of_valid_pct"])
        med = row["median_duration_min"]
        med_str = f" · mediaan {med:.0f} min" if np.isfinite(med) else ""
        ax.text(
            val + max_v * 0.012,
            bar.get_y() + bar.get_height() / 2,
            f"{val:,} ({pct:.1f}%{med_str})".replace(",", "."),
            va="center",
            fontsize=8.5,
            color="#222222",
        )

    ax.set_xlim(0, max_v * 1.48)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x):,}".replace(",", ".")))
    ax.set_xlabel("Aantal vermoedelijke woonadressen waarvoor deze locatie het snelst bereikbaar is", fontsize=10.5)
    ax.set_title(
        "Verzorgingsbereik per natuurbegraafplaats in Vlaanderen",
        fontsize=13.5,
        fontweight="bold",
        pad=12,
    )
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.text(0.01, -0.02, FOOTER_NOTE, fontsize=8, color="#555555")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_extremes_and_provinces_chart(
    municipalities_df: pd.DataFrame,
    provinces_df: pd.DataFrame,
    output_path: Path,
    top_n: int = 12,
) -> Path:
    """Dumbbell chart showing median -> P90 for provinces and top/bottom municipalities."""
    _style_axes()
    valid_m = municipalities_df.dropna(subset=["median_duration_min", "p90_duration_min"]).copy()
    best = valid_m.nsmallest(top_n, "median_duration_min").sort_values("median_duration_min", ascending=False)
    worst = valid_m.nlargest(top_n, "median_duration_min").sort_values("median_duration_min", ascending=True)
    prov = provinces_df.dropna(subset=["median_duration_min"]).sort_values("median_duration_min", ascending=False)

    fig, axes = plt.subplots(1, 3, figsize=(17.5, 6.2), dpi=220, sharex=True)
    panels = [
        (axes[0], prov, "provincie", "Per provincie"),
        (axes[1], best, "gemeente", f"Top {len(best)} snelst bereikbare gemeenten"),
        (axes[2], worst, "gemeente", f"Top {len(worst)} verst gelegen gemeenten"),
    ]

    for ax, df, label_col, title in panels:
        y = np.arange(len(df))
        ax.hlines(
            y,
            df["median_duration_min"],
            df["p90_duration_min"],
            color="#999999",
            linewidth=2.2,
            zorder=2,
        )
        ax.scatter(
            df["median_duration_min"],
            y,
            color="#1b9e77",
            s=65,
            zorder=3,
            label="Mediaan",
        )
        ax.scatter(
            df["p90_duration_min"],
            y,
            color="#d95f02",
            s=65,
            zorder=3,
            label="P90",
        )
        ax.set_yticks(y)
        ax.set_yticklabels(df[label_col], fontsize=9.5)
        ax.axvline(30, color="#666666", linestyle="--", linewidth=0.8, alpha=0.7)
        ax.set_title(title, fontsize=11.5, fontweight="bold", pad=8)
        ax.set_xlabel("Autorijtijd (min)")
        ax.grid(axis="x", linestyle=":", alpha=0.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    axes[0].legend(loc="upper right", frameon=True, facecolor="white", fontsize=9)
    fig.suptitle(
        "Spreiding van autorijtijd (mediaan → P90) naar de snelst bereikbare natuurbegraafplaats",
        fontsize=14,
        fontweight="bold",
        y=0.99,
    )
    fig.text(0.5, -0.01, FOOTER_NOTE, ha="center", fontsize=8.5, color="#555555")
    plt.tight_layout(rect=[0, 0.03, 1, 0.94])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_interactive_html_map(
    municipalities_df: pd.DataFrame,
    boundaries_gdf: gpd.GeoDataFrame,
    destinations_df: pd.DataFrame,
    flanders_df: pd.DataFrame,
    output_path: Path,
    nis_col: str = "NISCODE",
    simplify_tolerance_m: float = 150.0,
) -> Path:
    """Generate a self-contained interactive Leaflet HTML dashboard (also GitHub Pages ready)."""
    b = boundaries_gdf.copy()
    if simplify_tolerance_m > 0:
        b["geometry"] = b.geometry.simplify(simplify_tolerance_m, preserve_topology=True)
    b = b.to_crs("EPSG:4326")
    b["nis_key"] = b[nis_col].astype(str).str.strip()

    m = municipalities_df.copy()
    m["nis_key"] = m["nis_code"].astype(str).str.strip()
    merged = b.merge(m, on="nis_key", how="left")

    keep_cols = [
        "nis_key",
        "NAAM",
        "provincie",
        "n_selected",
        "n_valid_route",
        "routing_coverage_pct",
        "mean_duration_min",
        "median_duration_min",
        "p90_duration_min",
        "pct_within_15_min",
        "pct_within_30_min",
        "pct_within_45_min",
        "mean_distance_km",
        "median_distance_km",
        "p90_distance_km",
        "pct_within_10_km",
        "pct_within_20_km",
        "pct_within_30_km",
        "pct_within_50_km",
        "top_destination_id",
        "top_destination_name",
        "geometry",
    ]
    keep_cols = [c for c in keep_cols if c in merged.columns]
    geojson_str = merged[keep_cols].to_json()

    dests_records = [
        {
            "id": str(r["destination_id"]),
            "name": str(r["name"]),
            "short_name": _short_dest_name(str(r["name"])),
            "lon": float(r["lon"]),
            "lat": float(r["lat"]),
        }
        for _, r in destinations_df.iterrows()
    ]
    fl = flanders_df.iloc[0]
    kpi = {
        "n_selected": int(fl["n_selected"]),
        "median_min": round(float(fl["median_duration_min"]), 1),
        "p90_min": round(float(fl["p90_duration_min"]), 1),
        "pct30": round(float(fl["pct_within_30_min"]), 1),
        "coverage": round(float(fl["routing_coverage_pct"]), 2),
    }

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Bereikbaarheid natuurbegraafplaatsen in Vlaanderen</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f7f6; color: #1f2933; }}
    header {{ background: #0f3d2e; color: #fff; padding: 14px 20px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; }}
    header h1 {{ margin: 0; font-size: 1.15rem; font-weight: 600; }}
    header p {{ margin: 2px 0 0; font-size: 0.82rem; opacity: 0.88; }}
    .kpis {{ display: flex; gap: 14px; flex-wrap: wrap; }}
    .kpi {{ background: rgba(255,255,255,0.12); padding: 6px 12px; border-radius: 6px; text-align: center; }}
    .kpi .val {{ font-size: 1.05rem; font-weight: 700; display: block; }}
    .kpi .lbl {{ font-size: 0.72rem; opacity: 0.85; }}
    .controls {{ background: #fff; border-bottom: 1px solid #dfe5e2; padding: 10px 20px; display: flex; flex-wrap: wrap; align-items: center; gap: 18px; font-size: 0.88rem; }}
    .controls select, .controls input {{ font-size: 0.88rem; padding: 4px 8px; border: 1px solid #cbd2d9; border-radius: 4px; }}
    #map {{ height: calc(100vh - 142px); width: 100%; }}
    .legend {{ background: white; padding: 10px 12px; border-radius: 6px; box-shadow: 0 1px 6px rgba(0,0,0,0.18); line-height: 1.5; font-size: 0.82rem; }}
    .legend i {{ width: 14px; height: 14px; float: left; margin-right: 7px; margin-top: 2px; border: 1px solid rgba(0,0,0,0.15); }}
    footer {{ background: #fff; border-top: 1px solid #dfe5e2; padding: 6px 20px; font-size: 0.75rem; color: #52606d; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Bereikbaarheid van natuurbegraafplaatsen in Vlaanderen</h1>
      <p>Geschatte autorijtijd vanaf vermoedelijke woonadressen naar de snelst bereikbare natuurbegraafplaats (zonder actuele files)</p>
    </div>
    <div class="kpis">
      <div class="kpi"><span class="val">{kpi['n_selected']:,}</span><span class="lbl">Woonadressen</span></div>
      <div class="kpi"><span class="val">{kpi['median_min']} min</span><span class="lbl">Mediaan Vlaanderen</span></div>
      <div class="kpi"><span class="val">{kpi['p90_min']} min</span><span class="lbl">P90 Vlaanderen</span></div>
      <div class="kpi"><span class="val">{kpi['pct30']}%</span><span class="lbl">Binnen 30 min</span></div>
      <div class="kpi"><span class="val">{kpi['coverage']}%</span><span class="lbl">Routedekking</span></div>
    </div>
  </header>
  <div class="controls">
    <label><strong>Kaartlaag:</strong>
      <select id="metricSelect">
        <option value="median_duration_min">Mediaan autorijtijd (min)</option>
        <option value="p90_duration_min">P90 autorijtijd (min)</option>
        <option value="pct_within_30_min">Aandeel binnen 30 minuten (%)</option>
        <option value="median_distance_km">Mediaan rijafstand (km)</option>
        <option value="p90_distance_km">P90 rijafstand (km)</option>
        <option value="pct_within_30_km">Aandeel binnen 30 km (%)</option>
      </select>
    </label>
    <label><strong>Markeer gemeenten met mediaan &gt; <span id="threshVal">0</span> min:</strong>
      <input id="threshSlider" type="range" min="0" max="60" step="5" value="0" />
    </label>
  </div>
  <div id="map"></div>
  <footer>{FOOTER_NOTE}</footer>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const geoData = {geojson_str};
    const destinations = {json.dumps(dests_records, ensure_ascii=False)};

    const map = L.map('map').setView([51.05, 4.45], 9);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
      maxZoom: 18
    }}).addTo(map);

    function durationColor(v) {{
      if (v == null || isNaN(v)) return '#dddddd';
      return v <= 15 ? '#1a9850' :
             v <= 25 ? '#91cf60' :
             v <= 35 ? '#d9ef8b' :
             v <= 45 ? '#fee08b' :
             v <= 60 ? '#fc8d59' : '#d73027';
    }}
    function pctColor(v) {{
      if (v == null || isNaN(v)) return '#dddddd';
      return v >= 90 ? '#1a9850' :
             v >= 70 ? '#91cf60' :
             v >= 50 ? '#d9ef8b' :
             v >= 25 ? '#fee08b' :
             v > 0   ? '#fc8d59' : '#d73027';
    }}
    function distColor(v) {{
      if (v == null || isNaN(v)) return '#dddddd';
      return v <= 10 ? '#1a9850' :
             v <= 20 ? '#91cf60' :
             v <= 30 ? '#d9ef8b' :
             v <= 50 ? '#fee08b' :
             v <= 80 ? '#fc8d59' : '#d73027';
    }}

    let currentMetric = 'median_duration_min';
    let threshold = 0;

    function styleFeature(f) {{
      const p = f.properties;
      const val = p[currentMetric];
      let fill = '#dddddd';
      if (currentMetric === 'pct_within_30_min' || currentMetric === 'pct_within_30_km') fill = pctColor(val);
      else if (currentMetric === 'median_distance_km' || currentMetric === 'p90_distance_km') fill = distColor(val);
      else fill = durationColor(val);

      const dimmed = threshold > 0 && (p.median_duration_min == null || p.median_duration_min <= threshold);
      return {{
        fillColor: fill,
        weight: dimmed ? 0.5 : 1.1,
        opacity: 1,
        color: dimmed ? '#cccccc' : '#ffffff',
        fillOpacity: dimmed ? 0.18 : 0.78
      }};
    }}

    function fmt(v, suffix='') {{
      return (v == null || isNaN(v)) ? 'n.v.t.' : Number(v).toFixed(1) + suffix;
    }}

    const geoLayer = L.geoJSON(geoData, {{
      style: styleFeature,
      onEachFeature: (f, layer) => {{
        const p = f.properties;
        const html = `
          <strong>${{p.NAAM || p.nis_key}}</strong> (${{p.provincie || ''}})<br/>
          <hr style="margin:4px 0;border:none;border-top:1px solid #ddd;"/>
          Vermoedelijke woonadressen: <b>${{p.n_selected ? Number(p.n_selected).toLocaleString('nl-BE') : '0'}}</b><br/>
          Mediaan autorijtijd: <b>${{fmt(p.median_duration_min, ' min')}}</b><br/>
          Gemiddelde autorijtijd: <b>${{fmt(p.mean_duration_min, ' min')}}</b><br/>
          P90 autorijtijd: <b>${{fmt(p.p90_duration_min, ' min')}}</b><br/>
          Binnen 15 / 30 / 45 min: <b>${{fmt(p.pct_within_15_min, '%')}} / ${{fmt(p.pct_within_30_min, '%')}} / ${{fmt(p.pct_within_45_min, '%')}}</b><br/>
          Mediaan / P90 rijafstand: <b>${{fmt(p.median_distance_km, ' km')}} / ${{fmt(p.p90_distance_km, ' km')}}</b><br/>
          Binnen 10 / 20 / 30 / 50 km: <b>${{fmt(p.pct_within_10_km, '%')}} / ${{fmt(p.pct_within_20_km, '%')}} / ${{fmt(p.pct_within_30_km, '%')}} / ${{fmt(p.pct_within_50_km, '%')}}</b><br/>
          Routedekking: <b>${{fmt(p.routing_coverage_pct, '%')}}</b><br/>
          Snelste locatie: <b>${{p.top_destination_name || 'n.v.t.'}}</b>
        `;
        layer.bindTooltip(html, {{ sticky: true }});
      }}
    }}).addTo(map);

    destinations.forEach(d => {{
      L.circleMarker([d.lat, d.lon], {{
        radius: 6,
        fillColor: '#0b3d2e',
        color: '#ffffff',
        weight: 2,
        opacity: 1,
        fillOpacity: 0.95
      }}).bindPopup(`<strong>${{d.name}}</strong><br/>TerraId: ${{d.id}}`).addTo(map);
    }});

    const legend = L.control({{ position: 'bottomright' }});
    legend.onAdd = function() {{
      this._div = L.DomUtil.create('div', 'legend');
      this.update();
      return this._div;
    }};
    legend.update = function() {{
      let items;
      if (currentMetric === 'pct_within_30_min' || currentMetric === 'pct_within_30_km') {{
        items = [['#1a9850','≥ 90%'],['#91cf60','70–90%'],['#d9ef8b','50–70%'],['#fee08b','25–50%'],['#fc8d59','1–25%'],['#d73027','0%']];
      }} else if (currentMetric === 'median_distance_km' || currentMetric === 'p90_distance_km') {{
        items = [['#1a9850','≤ 10 km'],['#91cf60','10–20 km'],['#d9ef8b','20–30 km'],['#fee08b','30–50 km'],['#fc8d59','50–80 km'],['#d73027','> 80 km']];
      }} else {{
        items = [['#1a9850','≤ 15 min'],['#91cf60','15–25 min'],['#d9ef8b','25–35 min'],['#fee08b','35–45 min'],['#fc8d59','45–60 min'],['#d73027','> 60 min']];
      }}
      this._div.innerHTML = '<strong>Legenda</strong><br/>' + items.map(([c,l]) => `<i style="background:${{c}}"></i>${{l}}<br/>`).join('');
    }};
    legend.addTo(map);

    document.getElementById('metricSelect').addEventListener('change', e => {{
      currentMetric = e.target.value;
      geoLayer.setStyle(styleFeature);
      legend.update();
    }});
    document.getElementById('threshSlider').addEventListener('input', e => {{
      threshold = Number(e.target.value);
      document.getElementById('threshVal').textContent = threshold;
      geoLayer.setStyle(styleFeature);
    }});
  </script>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def render_distance_maps(
    municipalities_df: pd.DataFrame,
    boundaries_gdf: gpd.GeoDataFrame,
    destinations_df: pd.DataFrame,
    output_dir: Path,
    provinces_gdf: gpd.GeoDataFrame | None = None,
    nis_col: str = "NISCODE",
    prefix: str = "",
) -> Path:
    """Render side-by-side median & P90 driving distance (km) choropleth map."""
    _style_axes()
    output_dir.mkdir(parents=True, exist_ok=True)
    p = f"{prefix}_" if prefix else ""

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
    prov_proj = provinces_gdf.to_crs(merged.crs) if provinces_gdf is not None else None

    cmap = mcolors.ListedColormap(DISTANCE_COLORS)
    norm = mcolors.BoundaryNorm(DISTANCE_BINS, cmap.N)

    fig, axes = plt.subplots(1, 2, figsize=(18, 6.8), dpi=220)
    panels = [
        (axes[0], "median_distance_km", "Mediaan rijafstand (km)"),
        (axes[1], "p90_distance_km", "P90 rijafstand (km)"),
    ]
    for ax, col, subtitle in panels:
        merged.plot(
            column=col,
            ax=ax,
            cmap=cmap,
            norm=norm,
            edgecolor="#ffffff",
            linewidth=0.35,
            missing_kwds={"color": "#dddddd"},
        )
        if prov_proj is not None:
            prov_proj.boundary.plot(ax=ax, edgecolor="#333333", linewidth=1.0, zorder=3)
        dest_gdf.plot(
            ax=ax,
            color="#0b3d2e",
            edgecolor="white",
            linewidth=0.9,
            markersize=48,
            marker="o",
            zorder=5,
        )
        ax.set_title(subtitle, fontsize=13, fontweight="bold", pad=8)
        ax.set_axis_off()

    legend_handles = [
        mpatches.Patch(facecolor=c, edgecolor="#888888", label=lbl)
        for c, lbl in zip(DISTANCE_COLORS, DISTANCE_LABELS, strict=True)
    ]
    legend_handles.append(
        plt.Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor="#0b3d2e",
            markeredgecolor="white",
            markersize=8,
            label=f"Natuurbegraafplek (ANB, n={len(destinations_df)})",
        )
    )
    fig.legend(
        handles=legend_handles,
        loc="lower center",
        ncol=len(legend_handles),
        frameon=True,
        facecolor="white",
        edgecolor="#dddddd",
        fontsize=9.5,
        bbox_to_anchor=(0.5, 0.06),
    )
    fig.suptitle(
        "Rijafstand (km) van de snelste autoroute naar de dichtstbijzijnde natuurbegraafplaats in Vlaanderen",
        fontsize=15,
        fontweight="bold",
        y=0.98,
    )
    fig.text(0.5, 0.012, FOOTER_NOTE, ha="center", fontsize=8.5, color="#555555")
    plt.tight_layout(rect=[0, 0.11, 1, 0.94])

    out_path = output_dir / f"{p}kaart_afstand_mediaan_en_p90_km.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def render_cdf_curve_km(
    address_origin_map: pd.DataFrame,
    origin_results: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Weighted cumulative accessibility curve in kilometers for Flanders and each province."""
    _style_axes()
    subset = address_origin_map.loc[address_origin_map["in_main_analysis"]]
    weights = (
        subset.groupby(["nis_code", "origin_id"], dropna=False)
        .size()
        .reset_index(name="weight")
    )
    merged = weights.merge(
        origin_results[["origin_id", "status", "distance_m"]],
        on="origin_id",
        how="left",
    )
    ok = merged.loc[merged["status"] == "ok"].copy()
    ok["dist_km"] = ok["distance_m"] / 1000.0
    ok = ok.loc[np.isfinite(ok["dist_km"])].copy()
    ok["provincie"] = ok["nis_code"].map(province_from_nis)

    grid = np.linspace(0, 140, 561)
    fig, ax = plt.subplots(figsize=(11, 6.2), dpi=220)

    def _plot_curve(df: pd.DataFrame, label: str, color: str, lw: float, zorder: int) -> None:
        if len(df) == 0:
            return
        d = df["dist_km"].to_numpy(dtype=np.float64)
        w = df["weight"].to_numpy(dtype=np.float64)
        order = np.argsort(d)
        d_s = d[order]
        cum = np.cumsum(w[order]) / np.sum(w) * 100.0
        y = np.interp(grid, d_s, cum, left=0.0, right=100.0)
        ax.plot(grid, y, label=label, color=color, linewidth=lw, zorder=zorder)

    for prov, color in PROVINCE_COLORS.items():
        sub_p = ok.loc[ok["provincie"] == prov]
        if len(sub_p) > 0:
            pct30 = 100.0 * sub_p.loc[sub_p["dist_km"] <= 30.0, "weight"].sum() / sub_p["weight"].sum()
            _plot_curve(sub_p, f"{prov} ({pct30:.0f}% ≤ 30 km)", color, lw=2.0, zorder=3)

    pct30_fl = 100.0 * ok.loc[ok["dist_km"] <= 30.0, "weight"].sum() / ok["weight"].sum()
    _plot_curve(ok, f"Vlaams Gewest ({pct30_fl:.0f}% ≤ 30 km)", "#111111", lw=3.2, zorder=5)

    for thresh, dy in ((10, -7), (20, -7), (30, -7), (50, -7)):
        ax.axvline(thresh, color="#888888", linestyle="--", linewidth=0.9, zorder=1)
        pct_t = 100.0 * ok.loc[ok["dist_km"] <= thresh, "weight"].sum() / ok["weight"].sum()
        ax.scatter([thresh], [pct_t], color="#111111", s=35, zorder=6)
        ax.annotate(
            f"{thresh} km: {pct_t:.1f}%",
            xy=(thresh, pct_t),
            xytext=(thresh + 2.0, max(pct_t + dy, 4)),
            fontsize=8.8,
            fontweight="bold",
            color="#111111",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#cccccc", "alpha": 0.9},
        )

    ax.set_xlim(0, 140)
    ax.set_ylim(0, 102)
    ax.set_xlabel("Rijafstand van de snelste autoroute naar een natuurbegraafplaats (km)", fontsize=11)
    ax.set_ylabel("Cumulatief aandeel vermoedelijke woonadressen (%)", fontsize=11)
    ax.set_title(
        "Cumulatieve bereikbaarheid in kilometers in Vlaanderen en per provincie",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="lower right", frameon=True, facecolor="white", fontsize=9.5)
    fig.text(0.01, -0.02, FOOTER_NOTE, fontsize=8, color="#555555")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_destination_catchment_chart_km(
    dest_summary: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Horizontal bar chart of residential addresses per ANB site labeled with median km."""
    _style_axes()
    df = dest_summary.sort_values("n_addresses_fastest", ascending=True).copy()
    df["short_name"] = df["name"].map(_short_dest_name)

    fig, ax = plt.subplots(figsize=(11, 7.2), dpi=220)
    bars = ax.barh(df["short_name"], df["n_addresses_fastest"], color="#2b7a5b", edgecolor="none")

    max_v = max(float(df["n_addresses_fastest"].max()), 1.0)
    for bar, (_, row) in zip(bars, df.iterrows(), strict=True):
        val = int(row["n_addresses_fastest"])
        pct = float(row["share_of_valid_pct"])
        med = row["median_distance_km"]
        val_str = f"{val:,}".replace(",", ".")
        pct_str = f"{pct:.1f}%".replace(".", ",")
        med_str = f" · mediaan {med:.1f} km".replace(".", ",") if np.isfinite(med) else ""
        ax.text(
            val + max_v * 0.012,
            bar.get_y() + bar.get_height() / 2,
            f"{val_str} ({pct_str}{med_str})",
            va="center",
            fontsize=8.5,
            color="#222222",
        )

    ax.set_xlim(0, max_v * 1.48)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x):,}".replace(",", ".")))
    ax.set_xlabel("Aantal vermoedelijke woonadressen waarvoor deze locatie het snelst bereikbaar is", fontsize=10.5)
    ax.set_title(
        "Verzorgingsbereik per natuurbegraafplaats in Vlaanderen (met mediaan rijafstand in km)",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.text(0.01, -0.02, FOOTER_NOTE, fontsize=8, color="#555555")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_extremes_and_provinces_chart_km(
    municipalities_df: pd.DataFrame,
    provinces_df: pd.DataFrame,
    output_path: Path,
    top_n: int = 12,
) -> Path:
    """Dumbbell chart showing median -> P90 in km for provinces and top/bottom municipalities."""
    _style_axes()
    valid_m = municipalities_df.dropna(subset=["median_distance_km", "p90_distance_km"]).copy()
    best = valid_m.nsmallest(top_n, "median_distance_km").sort_values("median_distance_km", ascending=False)
    worst = valid_m.nlargest(top_n, "median_distance_km").sort_values("median_distance_km", ascending=True)
    prov = provinces_df.dropna(subset=["median_distance_km"]).sort_values("median_distance_km", ascending=False)

    fig, axes = plt.subplots(1, 3, figsize=(17.5, 6.2), dpi=220, sharex=True)
    panels = [
        (axes[0], prov, "provincie", "Per provincie"),
        (axes[1], best, "gemeente", f"Top {len(best)} dichtstbijzijnde gemeenten"),
        (axes[2], worst, "gemeente", f"Top {len(worst)} verst gelegen gemeenten"),
    ]

    for ax, df, label_col, title in panels:
        y = np.arange(len(df))
        ax.hlines(
            y,
            df["median_distance_km"],
            df["p90_distance_km"],
            color="#999999",
            linewidth=2.2,
            zorder=2,
        )
        ax.scatter(df["median_distance_km"], y, color="#1b9e77", s=65, zorder=3, label="Mediaan (km)")
        ax.scatter(df["p90_distance_km"], y, color="#d95f02", s=65, zorder=3, label="P90 (km)")
        ax.set_yticks(y)
        ax.set_yticklabels(df[label_col], fontsize=9.5)
        ax.axvline(30, color="#666666", linestyle="--", linewidth=0.8, alpha=0.7)
        ax.set_title(title, fontsize=11.5, fontweight="bold", pad=8)
        ax.set_xlabel("Rijafstand (km)")
        ax.grid(axis="x", linestyle=":", alpha=0.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    axes[0].legend(loc="upper right", frameon=True, facecolor="white", fontsize=9)
    fig.suptitle(
        "Spreiding van rijafstand (mediaan → P90 in km) naar de snelst bereikbare natuurbegraafplaats",
        fontsize=14,
        fontweight="bold",
        y=0.99,
    )
    fig.text(0.5, -0.01, FOOTER_NOTE, ha="center", fontsize=8.5, color="#555555")
    plt.tight_layout(rect=[0, 0.03, 1, 0.94])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path
