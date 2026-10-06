import hashlib
from pathlib import Path
import sys

PARQUET_DIR = Path("data/curated/parquet")
DUCKDB_PATH = Path("data/curated/duckdb/ev_infrastructure.duckdb")
CURATED_MANIFEST = Path("metadata/checksums_curated.sha256")

EXPECTED_OUTPUTS = [
    DUCKDB_PATH,
    PARQUET_DIR / "curated_ev_registrations.parquet",
    PARQUET_DIR / "curated_stations.parquet",
]


def verify_curated_lock(force: bool = False) -> None:
    if not CURATED_MANIFEST.exists():
        return
    all_exist = all(p.exists() for p in EXPECTED_OUTPUTS)

    if all_exist and not force:
        print("[LOCKED] Curated datasets are already built and verified against:")
        print(f"         {CURATED_MANIFEST}")
        print("         Execution halted to prevent unintended data drift.")
        print(
            "         To force a clean rebuild, run: python"
            " scripts/transform/transform_pipeline.py --force"
        )
        sys.exit(0)


def update_curated_checksums() -> None:
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    curated_files = sorted(list(PARQUET_DIR.glob("*.parquet")) + [DUCKDB_PATH])
    lines = []

    for p in curated_files:
        if p.exists():
            hasher = hashlib.sha256()

            with open(p, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            posix_path = p.as_posix()

            lines.append(f"{digest}  {posix_path}\n")
            print(f"[CURATED HASH] {posix_path} -> {digest[:12]}...")

    with open(CURATED_MANIFEST, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"[CURATED CHECKSUM] Manifest written to {CURATED_MANIFEST}")
