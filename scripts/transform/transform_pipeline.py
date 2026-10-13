import argparse
import json
from pathlib import Path
import duckdb
import pandas as pd
from utils_curated_validation import (
    update_curated_checksums,
    verify_curated_lock,
)
from shapely.ops import nearest_points
from shapely.geometry import shape, Point

RAW_STATIONS_PATH = Path("data/raw/nlr/raw_stations.json")
RAW_REGISTRATIONS_PATH = Path("data/raw/nyserda/raw_ev_registrations.json")
FIPS_MAPPING_PATH = Path("metadata/schemas/ny_fips_mapping.json")
BOUNDARIES_GEOJSON_PATH = Path("data/raw/boundaries/ny_county_boundaries.geojson")

PARQUET_DIR = Path("data/curated/parquet")
DUCKDB_PATH = Path("data/curated/duckdb/ev_infrastructure.duckdb")


def load_fips_lookup() -> dict[str, str]:
    if FIPS_MAPPING_PATH.exists():
        with open(FIPS_MAPPING_PATH, "r", encoding="utf-8") as f:
            mapping = json.load(f)
            lookup = {}

            for fips, name in mapping.items():
                clean_name = name.lower().strip()
                fips_str = str(fips).zfill(3)
                lookup[clean_name] = fips_str
                # Also index the dot-stripped version
                lookup[clean_name.replace(".", "")] = fips_str
            return lookup
    return {}


def load_county_spatial_index():
    with open(BOUNDARIES_GEOJSON_PATH, "r", encoding="utf-8") as f:
        geojson_data = json.load(f)
    county_polygons = []

    for feature in geojson_data.get("features", []):
        props = feature.get("properties", {})
        fips = props.get("COUNTY")
        name = props.get("NAME")
        geom = shape(feature.get("geometry"))

        county_polygons.append((fips, name, geom))
    return county_polygons

def lookup_county_by_coords(lat, lon, county_index):
    if lat is None or lon is None:
        return None, None
    pt = Point(float(lon), float(lat))

    for fips, name, poly in county_index:
        if poly.covers(pt):
            return str(fips).zfill(3), name
            
    # Match nearest polygon if on boundary or outside
    min_dist = float("inf")
    best_match = (None, None)

    for fips, name, poly in county_index:
        d = poly.distance(pt)

        if d < min_dist:
            min_dist = d
            best_match = (str(fips).zfill(3), name)
    return best_match


def transform_stations(fips_lookup: dict[str, str]) -> pd.DataFrame:
    print("[TRANSFORM] Processing NLR charging station payloads...")

    with open(RAW_STATIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    stations = data.get("fuel_stations", [])
    county_index = load_county_spatial_index()
    records = []
    
    for s in stations:
        station_id = s.get("id")
        station_name = s.get("station_name")
        network = s.get("ev_network")
        city = s.get("city")
        zip_code = s.get("zip")
        lat = s.get("latitude")
        lon = s.get("longitude")
        status_code = s.get("status_code")
        open_date = s.get("open_date")
        county_fips, county_name = lookup_county_by_coords(lat, lon, county_index)

        ev_connector_types = s.get("ev_connector_types") or ["UNKNOWN"]
        ev_dc_fast_num = s.get("ev_dc_fast_num") or 0
        ev_level1_num = s.get("ev_level1_evse_num") or 0
        ev_level2_num = s.get("ev_level2_evse_num") or 0

        for connector in ev_connector_types:
            records.append({
                "station_id": station_id,
                "station_name": station_name,
                "network": network,
                "county": county_name,
                "county_fips": county_fips,
                "city": city,
                "zip_code": str(zip_code)[:5] if zip_code else None,
                "latitude": float(lat) if lat is not None else None,
                "longitude": float(lon) if lon is not None else None,
                "status_code": status_code,
                "open_date": open_date,
                "connector_type": connector,
                "level1_ports": int(ev_level1_num),
                "level2_ports": int(ev_level2_num),
                "dc_fast_ports": int(ev_dc_fast_num),
            })

    df_stations = pd.DataFrame(records)
    df_stations["county_fips"] = df_stations["county_fips"].astype("string")
    out_parquet = PARQUET_DIR / "curated_stations.parquet"

    df_stations.to_parquet(out_parquet, index=False)
    print(f"  Exported {len(df_stations)} unnested station rows to {out_parquet}")

    return df_stations


def transform_registrations(fips_lookup: dict[str, str]) -> pd.DataFrame:
    print("[TRANSFORM] Processing NYSERDA registration records...")

    with open(RAW_REGISTRATIONS_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)
    df = pd.DataFrame(records)
    date_col = next(
        (
            c
            for c in ["registration_date", "data_as_of", "date"]
            if c in df.columns
        ),
        None,
    )

    if date_col:
        df["snapshot_date"] = pd.to_datetime(
            df[date_col], errors="coerce"
        ).dt.strftime("%Y-%m-%d")
    else:
        df["snapshot_date"] = "2026-10-01"

    county_col = next(
        (c for c in ["county", "county_name"] if c in df.columns), "county"
    )
    df["county_clean"] = df[county_col].astype(str).str.strip().str.lower()\
        .str.replace(".", "", regex=False)
    df["county_fips"] = df["county_clean"].map(fips_lookup).astype("string")

    fuel_col = next(
        (c for c in ["fuel_type", "ev_type", "technology"] if c in df.columns),
        None,
    )

    if fuel_col:
        df["fuel_category"] = df[fuel_col].astype(str).str.upper()
    else:
        df["fuel_category"] = "BEV"

    out_parquet = PARQUET_DIR / "curated_ev_registrations.parquet"

    df.to_parquet(out_parquet, index=False)
    print(f"  Exported {len(df)} registration records to {out_parquet}")

    return df


def build_duckdb_schema(df_stations: pd.DataFrame, df_registrations: pd.DataFrame) -> None:
    print("[RELATIONAL] Compiling relational tables into DuckDB...")
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DUCKDB_PATH))

    con.execute(
        "CREATE OR REPLACE TABLE charging_stations AS SELECT * FROM df_stations"
    )
    con.execute(
        "CREATE OR REPLACE TABLE ev_registrations AS SELECT * FROM df_registrations"
    )

    con.execute("""
        CREATE OR REPLACE VIEW county_infrastructure_summary AS
        WITH distinct_station_ports AS (
            SELECT 
                station_id,
                CAST(county_fips AS VARCHAR) AS county_fips,
                level2_ports,
                dc_fast_ports
            FROM charging_stations
            WHERE county_fips IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY station_id) = 1
        ),
        county_station_aggs AS (
            SELECT 
                county_fips,
                COUNT(station_id) AS total_stations,
                COALESCE(SUM(level2_ports), 0) AS total_level2_ports,
                COALESCE(SUM(dc_fast_ports), 0) AS total_dc_fast_ports
            FROM distinct_station_ports
            GROUP BY county_fips
        ),
        county_ev_aggs AS (
            SELECT 
                CAST(county_fips AS VARCHAR) AS county_fips,
                COUNT(*) AS total_ev_registrations
            FROM ev_registrations
            WHERE county_fips IS NOT NULL
            GROUP BY county_fips
        )
        SELECT 
            COALESCE(s.county_fips, r.county_fips) AS county_fips,
            COALESCE(s.total_stations, 0) AS total_stations,
            COALESCE(s.total_level2_ports, 0) AS total_level2_ports,
            COALESCE(s.total_dc_fast_ports, 0) AS total_dc_fast_ports,
            COALESCE(r.total_ev_registrations, 0) AS total_ev_registrations
        FROM county_station_aggs s
        FULL OUTER JOIN county_ev_aggs r
            ON s.county_fips = r.county_fips;
    """)
    con.close()
    print(f"  DuckDB database initialized at {DUCKDB_PATH}")


def main():
    parser = argparse.ArgumentParser(
        description="Transform raw datasets into curated Parquet and DuckDB formats."
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild of curated data even if locked.",
    )
    args = parser.parse_args()

    # Pre-execution lock verification
    verify_curated_lock(force=args.force)

    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    fips_lookup = load_fips_lookup()
    df_stations = transform_stations(fips_lookup)
    df_registrations = transform_registrations(fips_lookup)

    build_duckdb_schema(df_stations, df_registrations)
    update_curated_checksums()


if __name__ == "__main__":
    main()
