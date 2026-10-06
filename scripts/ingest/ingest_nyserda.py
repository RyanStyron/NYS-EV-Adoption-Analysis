import json
from pathlib import Path
import requests
from utils_integrity import verify_and_commit_payload

ENDPOINT = "https://data.ny.gov/resource/x9ct-hwyv.json"
CACHE_PATH = Path("data/raw/nyserda/raw_ev_registrations.json")

def fetch_all_nyserda_records(batch_size: int = 50000) -> list:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if CACHE_PATH.exists():
        print(f"[CACHE HIT] Loaded existing snapshot: {CACHE_PATH}")

        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    all_records = []
    offset = 0

    print("[FETCHING] Downloading all records via paginated requests...")

    while True:
        params = {
            "$limit": batch_size,
            "$offset": offset,
            "$order": ":id"
        }
        response = requests.get(ENDPOINT, params=params, timeout=60)

        response.raise_for_status()
        batch = response.json()

        if not batch:
            break
        all_records.extend(batch)
        print(f"  Fetched {len(batch)} rows (total so far: {len(all_records)})")

        if len(batch) < batch_size:
            break
        offset += batch_size

    verify_and_commit_payload(CACHE_PATH, all_records)
    return all_records

if __name__ == "__main__":
    records = fetch_all_nyserda_records()

    print(f"Verified: {len(records)} total EV registration records retrieved.")
