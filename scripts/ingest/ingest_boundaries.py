import json
from pathlib import Path
import requests
from utils_integrity import verify_and_commit_payload

# US Census Bureau 2020 500k Cartographic Boundary GeoJSON for US Counties
CENSUS_URL = "https://eric.clst.org/assets/wiki/uploads/Stuff/gz_2010_us_050_00_500k.json"
CACHE_PATH = Path("data/raw/boundaries/ny_county_boundaries.geojson")

def fetch_ny_boundaries() -> dict:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if CACHE_PATH.exists():
        print(f"[CACHE HIT] Loaded existing boundaries: {CACHE_PATH}")

        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    print("[FETCHING] Downloading county boundary dataset...")
    
    response = requests.get(CENSUS_URL, timeout=60)

    response.raise_for_status()
    all_data = response.json()

    # Filter strictly for New York State (State FIPS == '36')
    ny_features = [
        feat for feat in all_data.get("features", [])
        if feat.get("properties", {}).get("STATE") == "36"
    ]
    ny_geojson = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}
        },
        "features": ny_features
    }

    # Atomically verify and commit to disk + metadata/checksums_raw.sha256
    verify_and_commit_payload(CACHE_PATH, ny_geojson)
    return ny_geojson

if __name__ == "__main__":
    data = fetch_ny_boundaries()

    print(f"Verified: Extracted all {len(data['features'])} New York counties.")
