import os
import json
from pathlib import Path
import requests
from dotenv import load_dotenv
from utils_integrity import verify_and_commit_payload

load_dotenv()

API_KEY = os.getenv("NLR_API_KEY")
ENDPOINT = "https://developer.nlr.gov/api/alt-fuel-stations/v1.json"
CACHE_PATH = Path("data/raw/nlr/raw_stations.json")

def fetch_nlr_stations(state: str = "NY") -> dict:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if CACHE_PATH.exists():
        print(f"[CACHE HIT] Loaded existing snapshot: {CACHE_PATH}")

        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    if not API_KEY:
        raise ValueError("Missing NLR_API_KEY in .env file.")

    params = {
        "api_key": API_KEY,
        "fuel_type": "ELEC",
        "state": state,
        "limit": "all"
    }
    print(f"[FETCHING] Querying NLR AFDC endpoint for {state}...")

    response = requests.get(ENDPOINT, params=params, timeout=60)

    response.raise_for_status()
    payload = response.json()

    verify_and_commit_payload(CACHE_PATH, payload)
    return payload

if __name__ == "__main__":
    data = fetch_nlr_stations()
    stations = data.get("fuel_stations", [])

    print(f"Verified: {len(stations)} total EV charging stations retrieved.")
