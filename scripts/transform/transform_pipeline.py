import argparse
import json
from pathlib import Path
import duckdb
import pandas as pd
from utils_curated_validation import (
    update_curated_checksums,
    verify_curated_lock,
)

RAW_STATIONS_PATH = Path("data/raw/nlr/raw_stations.json")
RAW_REGISTRATIONS_PATH = Path("data/raw/nyserda/raw_ev_registrations.json")
FIPS_MAPPING_PATH = Path("metadata/schemas/ny_fips_mapping.json")

PARQUET_DIR = Path("data/curated/parquet")
DUCKDB_PATH = Path("data/curated/duckdb/ev_infrastructure.duckdb")


def load_fips_lookup() -> dict[str, str]:
    if FIPS_MAPPING_PATH.exists():
        with open(FIPS_MAPPING_PATH, "r", encoding="utf-8") as f:
            mapping = json.load(f)

            return {
                name.lower().strip(): str(fips).zfill(3)
                for fips, name in mapping.items()
            }
    return {}


def transform_stations(fips_lookup: dict[str, str]) -> pd.DataFrame:
    print("[TRANSFORM] Processing NLR charging station payloads...")

    with open(RAW_STATIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    stations = data.get("fuel_stations", [])
    records = []

    for s in stations:
        station_id = s.get("id")
        station_name = s.get("station_name")
        network = s.get("ev_network")
        county = s.get("ev_county") or s.get("county")
        city = s.get("city")
        zip_code = s.get("zip")
        lat = s.get("latitude")
        lon = s.get("longitude")
        status = s.get("status_code")
        open_date = s.get("open_date")

        county_clean = county.strip().lower() if county else ""
        county_fips = fips_lookup.get(county_clean, None)

        ev_connector_types = s.get("ev_connector_types") or ["UNKNOWN"]
        ev_dc_fast_num = s.get("ev_dc_fast_num") or 0
        ev_level2_num = s.get("ev_level2_evse_num") or 0
        ev_level1_num = s.get("ev_level1_evse_num") or 0

        for connector in ev_connector_types:
            records.append({
                "station_id": station_id,
                "station_name": station_name,
                "network": network,
                "county": county,
                "county_fips": (
                    str(county_fips).zfill(3) if county_fips else None
                ),
                "city": city,
                "zip_code": str(zip_code) if zip_code else None,
                "latitude": float(lat) if lat is not None else None,
                "longitude": float(lon) if lon is not None else None,
                "status_code": status,
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
    df["county_clean"] = df[county_col].astype(str).str.strip().str.lower()
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


def build_duckdb_schema(
    df_stations: pd.DataFrame, df_registrations: pd.DataFrame
) -> None:
    print("[RELATIONAL] Compiling relational tables into DuckDB...")
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DUCKDB_PATH))

    con.execute(
        "CREATE OR REPLACE TABLE charging_stations AS SELECT * FROM df_stations"
    )
    con.execute(
        "CREATE OR REPLACE TABLE ev_registrations AS SELECT * FROM"
        " df_registrations"
    )

    con.execute("""
        CREATE OR REPLACE VIEW county_infrastructure_summary AS
        SELECT 
            COALESCE(CAST(s.county_fips AS VARCHAR), CAST(r.county_fips AS VARCHAR)) AS county_fips,
            COUNT(DISTINCT s.station_id) AS total_stations,
            COALESCE(SUM(s.level2_ports), 0) AS total_level2_ports,
            COALESCE(SUM(s.dc_fast_ports), 0) AS total_dc_fast_ports,
            COUNT(r.county_clean) AS total_ev_registrations
        FROM charging_stations s
        FULL OUTER JOIN ev_registrations r
            ON CAST(s.county_fips AS VARCHAR) = CAST(r.county_fips AS VARCHAR)
        GROUP BY 1
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
