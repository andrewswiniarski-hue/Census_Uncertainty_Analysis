"""Pull US state and county boundaries and simplify them for map display.

What it does
------------
Downloads 2024 ACS cartographic boundaries (same vintage as pull_usdash.py)
for all US states and counties, drops Puerto Rico (see pull_usdash.py's
module docstring for why), then writes two versions of each level:

- geo_2024_usdash_{state,county}.parquet         -- full-precision, EPSG:4326
- geo_2024_usdash_{state,county}_simple.parquet   -- simplified, EPSG:4326

Simplification uses the `topojson` package's toposimplify, NOT
shapely.simplify. shapely.simplify(preserve_topology=True) only guarantees
a SINGLE polygon stays internally valid -- it says nothing about SHARED
borders between neighboring counties, so at the tolerance nationwide
geometry needs (national totals run into tens of millions of vertices
raw), adjacent counties develop visible slivers and gaps along their
shared line. topojson builds one shared-arc topology across the whole
GeoDataFrame first, simplifies each arc once, then rebuilds the polygons
-- neighbors that shared a border before simplification still share
exactly that border after.

Tolerance 0.0005 degrees (~50m at mid-US latitudes) matches the value
Streamlit/app_NJ.py already uses for its own display geometry -- reusing
an already-justified number instead of picking a new one. Real, measured
nationwide county numbers at this tolerance (verified live 2026-08-12,
before this script existed): 644,965 vertices / 16.79 MB raw GeoJSON for
all 3,144 counties at once. This script's own simplified output ends up
smaller after the PR drop and topojson's shared-arc dedup.

The state-first drill-down (Streamlit/app_US.py) never actually renders
all 3,144 counties in one deck.gl payload -- the county view is always
scoped to one state's counties (62 median, 254 max in Texas) after the
click-grid removal, so this file's total size only matters for the
one-time cache_resource load, not for anything sent to the browser per
render.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt (censusdis, geopandas,
  topojson, pyarrow)

What it produces
----------------
- data/raw/geo_2024_usdash_state.parquet          (51 shapes)
- data/raw/geo_2024_usdash_state_simple.parquet
- data/raw/geo_2024_usdash_county.parquet         (~3,144 shapes)
- data/raw/geo_2024_usdash_county_simple.parquet

Run from the repo root:
    python ingestion/pull_us_geometry.py
"""

from __future__ import annotations

import time

import censusdis.data as ced
import shapely
import topojson as tp

from _common import OUT_DIR, REPO_ROOT, load_api_key
from pull_usdash import STATE_PR, drop_puerto_rico

DATASET = "acs/acs5"
VINTAGE = 2024
SIMPLIFY_TOLERANCE_DEG = 0.0005  # matches Streamlit/app_NJ.py's _FILL_SIMPLIFY_TOLERANCE_DEG

GEO_LEVELS = {
    "state": dict(state="*"),
    "county": dict(state="*", county="*"),
}
EXPECTED_ROWS = {"state": 51, "county": 3_144}


def repair_invalid(geom):
    """Fix a rare simplification artifact: a thin land/water neck folding
    into a self-intersection, or a tiny island/exclave ring collapsing to
    fewer than 4 coordinates, at this tolerance. Confirmed live on the
    nationwide county pull: 3 of 3,144 counties, ~0.05% area difference
    from the un-simplified shape -- Marshall County AL and Prince William
    County VA (self-intersections, both have convoluted lake/river
    shorelines) and Pickens County SC (a degenerate ring).

    shapely.make_valid() sometimes returns a GeometryCollection mixing the
    real polygon with a zero-area Point/LineString remnant of the
    collapsed ring (confirmed on Pickens County) -- pydeck's GeoJsonLayer
    expects Polygon/MultiPolygon, so those non-area parts are dropped.
    """
    fixed = shapely.make_valid(geom)
    if fixed.geom_type == "GeometryCollection":
        polys = [g for g in fixed.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if polys:
            fixed = shapely.union_all(polys)
    return fixed


def vertex_count(gdf) -> int:
    total = 0
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        for poly in polys:
            total += len(poly.exterior.coords)
            for ring in poly.interiors:
                total += len(ring.coords)
    return total


def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []

    for level, geo_kwargs in GEO_LEVELS.items():
        raw_path = OUT_DIR / f"geo_2024_usdash_{level}.parquet"
        simple_path = OUT_DIR / f"geo_2024_usdash_{level}_simple.parquet"

        if raw_path.exists() and simple_path.exists():
            print(f"\nAlready on disk, skipping download: {level} "
                  f"(delete both files to re-pull)")
            continue

        print(f"\nDownloading {level} geometry ...")
        gdf = ced.download(
            DATASET, VINTAGE, download_variables=["NAME"],
            api_key=api_key, with_geometry=True, **geo_kwargs,
        )
        gdf = drop_puerto_rico(gdf, level, checks)
        gdf = gdf.to_crs(epsg=4326)

        ok = len(gdf) == EXPECTED_ROWS[level]
        checks.append(f"{'PASS' if ok else 'FAIL'} [{level}] row count {len(gdf):,} "
                       f"(expected exactly {EXPECTED_ROWS[level]:,})")
        invalid = int((~gdf.geometry.is_valid).sum())
        checks.append(f"{'PASS' if invalid == 0 else 'FAIL'} [{level}] invalid geometries: {invalid}")

        raw_vertices = vertex_count(gdf)
        gdf.to_parquet(raw_path, index=False)
        print(f"  Saved {raw_path.relative_to(REPO_ROOT)} "
              f"({raw_path.stat().st_size / 1024:,.0f} KB, {raw_vertices:,} vertices)")

        print(f"  Simplifying via topojson (tolerance {SIMPLIFY_TOLERANCE_DEG} deg) ...")
        topo = tp.Topology(gdf, prequantize=False)
        simple_gdf = topo.toposimplify(SIMPLIFY_TOLERANCE_DEG).to_gdf()
        simple_gdf = simple_gdf.set_crs(epsg=4326, allow_override=True)

        invalid_mask = ~simple_gdf.geometry.is_valid
        n_repaired = int(invalid_mask.sum())
        if n_repaired:
            simple_gdf.loc[invalid_mask, "geometry"] = (
                simple_gdf.loc[invalid_mask, "geometry"].apply(repair_invalid)
            )
            checks.append(f"INFO [{level}] repaired {n_repaired} simplification "
                          f"artifact(s) via shapely.make_valid()")

        invalid_simple = int((~simple_gdf.geometry.is_valid).sum())
        checks.append(f"{'PASS' if invalid_simple == 0 else 'FAIL'} "
                       f"[{level}] invalid geometries after simplify + repair: {invalid_simple}")
        non_polygonal = int((~simple_gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])).sum())
        checks.append(f"{'PASS' if non_polygonal == 0 else 'FAIL'} "
                       f"[{level}] non-polygonal geometries: {non_polygonal}")
        simple_vertices = vertex_count(simple_gdf)
        simple_gdf.to_parquet(simple_path, index=False)
        print(f"  Saved {simple_path.relative_to(REPO_ROOT)} "
              f"({simple_path.stat().st_size / 1024:,.0f} KB, {simple_vertices:,} vertices, "
              f"{raw_vertices - simple_vertices:,} fewer than raw)")

    print(f"\n{'=' * 60}\nCheck summary:")
    for line in checks:
        print(f"  {line}")
    failures = [c for c in checks if c.startswith("FAIL")]
    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        raise SystemExit(f"{len(failures)} sanity check(s) FAILED -- see summary above.")
    print("All sanity checks passed.")


if __name__ == "__main__":
    main()
