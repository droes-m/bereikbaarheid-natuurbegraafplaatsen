"""Command-line interface for the bereikbaarheid-natuurbegraafplaatsen pipeline."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd

from bereikbaarheid.addresses import filter_official_addresses
from bereikbaarheid.aggregate import (
    aggregate_accessibility,
    aggregate_by_destination,
    aggregate_by_province,
    compare_variants,
)
from bereikbaarheid.config import ProjectPaths, RunConfig
from bereikbaarheid.destinations import check_osrm_snapping, load_destinations
from bereikbaarheid.landuse import DEFAULT_RESIDENTIAL_CODE, check_spatial_tolerance, sample_landuse
from bereikbaarheid.origins import build_origins
from bereikbaarheid.reporting import write_summary_tables
from bereikbaarheid.routing import route_origins_osrm
from bereikbaarheid.sampling import stratified_pilot_sample
from bereikbaarheid.visuals import (
    render_cdf_curve,
    render_destination_catchment_chart,
    render_extremes_and_provinces_chart,
    render_interactive_html_map,
    render_travel_time_maps,
)


def cmd_validate_destinations(args: argparse.Namespace) -> None:
    overrides = Path(args.overrides) if args.overrides else None
    df, report = load_destinations(Path(args.destinations), overrides_path=overrides)
    print(json.dumps(report.__dict__, indent=2, ensure_ascii=False))
    if args.check_snapping:
        snap = check_osrm_snapping(df, osrm_base_url=args.osrm_url)
        out = Path(args.snapping_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        snap.to_csv(out, index=False)
        print(f"Snapping controle opgeslagen naar: {out}")
        print(
            snap[["destination_id", "name", "snap_distance_m", "snapped_road", "status"]].to_string(
                index=False
            )
        )


def cmd_prepare_addresses(args: argparse.Namespace) -> None:
    paths = ProjectPaths(Path.cwd())
    paths.ensure_dirs()
    t0 = time.perf_counter()

    print(f"Laden Adressenregister: {args.addresses}")
    read_kwargs: dict = {"use_arrow": True}
    if args.layer:
        read_kwargs["layer"] = args.layer
    gdf = gpd.read_file(args.addresses, **read_kwargs)
    col_map = json.loads(args.column_map) if args.column_map else None

    valid_addr, dup_labels, addr_report = filter_official_addresses(gdf, column_map=col_map)
    print("Adressenregister filter:", json.dumps(addr_report.__dict__, indent=2, ensure_ascii=False))

    sampled, lu_report = sample_landuse(
        valid_addr,
        raster_path=Path(args.landuse_raster),
        residential_code=args.residential_code,
    )
    print("Landgebruik sampling:", json.dumps(lu_report.__dict__, indent=2, ensure_ascii=False))

    tol = None
    if args.check_tolerance:
        tol = check_spatial_tolerance(
            sampled,
            raster_path=Path(args.landuse_raster),
            residential_code=args.residential_code,
            radius_cells=1,
        )
        print("Ruimtelijke tolerantie (±1 cel / 10 m):", json.dumps(tol, indent=2, ensure_ascii=False))

    addr_origin_map, origins, orig_report = build_origins(sampled)
    print("Vertrekpunten:", json.dumps(orig_report.__dict__, indent=2, ensure_ascii=False))

    dup_labels.to_parquet(paths.data_interim / "duplicate_active_labels.parquet", index=False)
    addr_origin_map.to_parquet(paths.data_interim / "address_origin_map.parquet", index=False)
    origins.to_parquet(paths.data_interim / "origins.parquet", index=False)

    elapsed = round(time.perf_counter() - t0, 2)
    meta = {
        "elapsed_seconds": elapsed,
        "address_filter": addr_report.__dict__,
        "landuse_sampling": lu_report.__dict__,
        "spatial_tolerance_1cell": tol,
        "origins": orig_report.__dict__,
    }
    (paths.data_interim / "preparation_report.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Opgeslagen in {paths.data_interim} (duur: {elapsed} s)")


def _generate_all_outputs(
    addr_origin_map: pd.DataFrame,
    results: pd.DataFrame,
    destinations: pd.DataFrame,
    output_dir: Path,
    prefix: str,
    boundaries_path: str | None,
    provinces_path: str | None,
    boundaries_nis_col: str,
) -> None:
    flanders_main, mun_main = aggregate_accessibility(
        addr_origin_map, results, variant="main", destinations_df=destinations
    )
    flanders_var, mun_var = aggregate_accessibility(
        addr_origin_map, results, variant="no_bus_variant", destinations_df=destinations
    )
    diff_df = compare_variants(flanders_main, flanders_var)
    prov_main = aggregate_by_province(addr_origin_map, results, variant="main")
    dest_summary = aggregate_by_destination(addr_origin_map, results, destinations, variant="main")

    written = write_summary_tables(flanders_main, mun_main, diff_df, output_dir, prefix=prefix)
    p = f"{prefix}_" if prefix else ""
    mun_var.to_csv(output_dir / f"{p}gemeenten_no_bus_variant.csv", index=False)
    prov_main.to_csv(output_dir / f"{p}provincies_samenvatting.csv", index=False)
    dest_summary.to_csv(output_dir / f"{p}bestemmingen_verzorgingsgebied.csv", index=False)

    # Static charts (always possible even without boundaries)
    cdf_path = render_cdf_curve(addr_origin_map, results, output_dir / f"{p}grafiek_cumulatieve_bereikbaarheid.png")
    dest_chart = render_destination_catchment_chart(
        dest_summary, output_dir / f"{p}grafiek_verzorgingsbereik_per_locatie.png"
    )
    ext_chart = render_extremes_and_provinces_chart(
        mun_main, prov_main, output_dir / f"{p}grafiek_provincies_en_gemeenten_spreiding.png"
    )
    print("Tabellen & grafieken geschreven:")
    for k, v in written.items():
        print(f"  - {k}: {v}")
    print(f"  - cdf: {cdf_path}")
    print(f"  - catchment_chart: {dest_chart}")
    print(f"  - extremes_chart: {ext_chart}")

    if boundaries_path:
        boundaries = gpd.read_file(boundaries_path)
        provinces = gpd.read_file(provinces_path) if provinces_path and Path(provinces_path).exists() else None
        maps = render_travel_time_maps(
            mun_main,
            boundaries,
            destinations,
            output_dir,
            provinces_gdf=provinces,
            nis_col=boundaries_nis_col,
            prefix=prefix,
        )
        html_path = render_interactive_html_map(
            mun_main,
            boundaries,
            destinations,
            flanders_main,
            output_dir / f"{p}interactieve_kaart.html",
            nis_col=boundaries_nis_col,
        )
        print(f"  - dual_map: {maps['dual_map']}")
        print(f"  - catchment_map: {maps['catchment_map']}")
        print(f"  - interactive_html: {html_path}")


def cmd_route(args: argparse.Namespace) -> None:
    paths = ProjectPaths(Path.cwd())
    paths.ensure_dirs()

    destinations, _ = load_destinations(
        Path(args.destinations),
        overrides_path=Path(args.overrides) if args.overrides else None,
    )
    addr_origin_map = pd.read_parquet(paths.data_interim / "address_origin_map.parquet")
    origins = pd.read_parquet(paths.data_interim / "origins.parquet")

    if args.pilot_n:
        addr_origin_map = stratified_pilot_sample(
            addr_origin_map, target_n=args.pilot_n, seed=args.seed
        )
        pilot_origin_ids = set(addr_origin_map["origin_id"].unique())
        origins = origins.loc[origins["origin_id"].isin(pilot_origin_ids)].reset_index(drop=True)
        addr_origin_map.to_parquet(paths.data_interim / "pilot_address_origin_map.parquet", index=False)
        origins.to_parquet(paths.data_interim / "pilot_origins.parquet", index=False)
        print(f"Pilot steekproef: {len(addr_origin_map):,} adressen -> {len(origins):,} unieke vertrekpunten")

    cfg = RunConfig(
        osrm_base_url=args.osrm_url,
        batch_size=args.batch_size,
        dest_chunk_size=args.dest_chunk_size,
        osm_extract=args.osm_extract,
    )
    results, metrics = route_origins_osrm(
        origins=origins,
        destinations=destinations,
        config=cfg,
        cache_dir=paths.data_interim / "routing_batches",
    )
    print("Routeringsmetrieken:", json.dumps(metrics.__dict__, indent=2, ensure_ascii=False))

    prefix = "pilot" if args.pilot_n else "full"
    out_parquet = paths.data_processed / f"{prefix}_origin_results.parquet"
    results.to_parquet(out_parquet, index=False)

    _generate_all_outputs(
        addr_origin_map=addr_origin_map,
        results=results,
        destinations=destinations,
        output_dir=paths.outputs,
        prefix=prefix,
        boundaries_path=args.boundaries,
        provinces_path=args.provinces,
        boundaries_nis_col=args.boundaries_nis_col,
    )


def cmd_visualize(args: argparse.Namespace) -> None:
    paths = ProjectPaths(Path.cwd())
    destinations, _ = load_destinations(
        Path(args.destinations),
        overrides_path=Path(args.overrides) if args.overrides else None,
    )
    prefix = args.prefix
    map_file = (
        paths.data_interim / "pilot_address_origin_map.parquet"
        if prefix == "pilot"
        else paths.data_interim / "address_origin_map.parquet"
    )
    addr_origin_map = pd.read_parquet(map_file)
    results = pd.read_parquet(paths.data_processed / f"{prefix}_origin_results.parquet")

    _generate_all_outputs(
        addr_origin_map=addr_origin_map,
        results=results,
        destinations=destinations,
        output_dir=paths.outputs,
        prefix=prefix,
        boundaries_path=args.boundaries,
        provinces_path=args.provinces,
        boundaries_nis_col=args.boundaries_nis_col,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bereikbaarheid",
        description="Bereikbaarheidsanalyse natuurbegraafplaatsen in Vlaanderen",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_dest = sub.add_parser("validate-destinations", help="Valideer bestemmingen en optioneel OSRM-snapping")
    p_dest.add_argument("--destinations", default="data/raw/natuurbegraafplaatsen_anb_layer55.csv")
    p_dest.add_argument("--overrides", default=None)
    p_dest.add_argument("--check-snapping", action="store_true")
    p_dest.add_argument("--osrm-url", default="http://localhost:5000")
    p_dest.add_argument("--snapping-out", default="outputs/destination_snapping_check.csv")
    p_dest.set_defaults(func=cmd_validate_destinations)

    p_prep = sub.add_parser(
        "prepare-addresses",
        help="Filter Adressenregister, sample Landgebruik 2025 en bouw vertrekpunten",
    )
    p_prep.add_argument("--addresses", required=True)
    p_prep.add_argument("--layer", default=None)
    p_prep.add_argument("--landuse-raster", required=True)
    p_prep.add_argument("--residential-code", type=int, default=DEFAULT_RESIDENTIAL_CODE)
    p_prep.add_argument("--column-map", default=None, help="Optionele JSON kolommapping")
    p_prep.add_argument("--check-tolerance", action="store_true")
    p_prep.set_defaults(func=cmd_prepare_addresses)

    p_route = sub.add_parser("route", help="Draai pilot of eindrun OSRM routering + aggregatie + visuals")
    p_route.add_argument("--destinations", default="data/raw/natuurbegraafplaatsen_anb_layer55.csv")
    p_route.add_argument("--overrides", default=None)
    p_route.add_argument("--osrm-url", default="http://localhost:5000")
    p_route.add_argument("--batch-size", type=int, default=200)
    p_route.add_argument("--dest-chunk-size", type=int, default=50)
    p_route.add_argument("--osm-extract", default="belgium-latest")
    p_route.add_argument("--pilot-n", type=int, default=None, help="Aantal adressen voor proefberekening (bv. 10000)")
    p_route.add_argument("--seed", type=int, default=42)
    p_route.add_argument("--boundaries", default="data/raw/vrbg2025_gemeenten.geojson")
    p_route.add_argument("--provinces", default="data/raw/vrbg2025_provincies.geojson")
    p_route.add_argument("--boundaries-nis-col", default="NISCODE")
    p_route.set_defaults(func=cmd_route)

    p_vis = sub.add_parser("visualize", help="Genereer alle tabellen, grafieken en kaarten uit bestaande resultaten")
    p_vis.add_argument("--prefix", choices=["pilot", "full"], default="full")
    p_vis.add_argument("--destinations", default="data/raw/natuurbegraafplaatsen_anb_layer55.csv")
    p_vis.add_argument("--overrides", default=None)
    p_vis.add_argument("--boundaries", default="data/raw/vrbg2025_gemeenten.geojson")
    p_vis.add_argument("--provinces", default="data/raw/vrbg2025_provincies.geojson")
    p_vis.add_argument("--boundaries-nis-col", default="NISCODE")
    p_vis.set_defaults(func=cmd_visualize)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
