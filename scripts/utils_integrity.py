import hashlib
import json
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path("metadata/checksums_raw.sha256")

def get_existing_checksums() -> dict[str, str]:
    if not MANIFEST_PATH.exists():
        return {}
    checksums = {}

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)

            if len(parts) == 2:
                digest, path_str = parts
                checksums[path_str.strip()] = digest.strip()
    return checksums

def verify_and_commit_payload(target_path: Path, payload_data: Any) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    posix_path = target_path.as_posix()

    # Deterministic in-memory serialization
    serialized_bytes = json.dumps(payload_data, indent=2, ensure_ascii=False).encode("utf-8")
    incoming_digest = hashlib.sha256(serialized_bytes).hexdigest()

    existing_checksums = get_existing_checksums()

    # Pre-write validation
    if posix_path in existing_checksums:
        recorded_digest = existing_checksums[posix_path]

        if recorded_digest != incoming_digest:
            raise ValueError(
                f"[INTEGRITY ERROR] Checksum mismatch for {posix_path}\n"
                f"  Recorded Baseline: {recorded_digest}\n"
                f"  Incoming Payload:  {incoming_digest}\n"
                f"Failed write: Target file was not overwritten."
            )
        print(f"[INTEGRITY OK] Matched baseline checksum for {posix_path}: {recorded_digest[:12]}...")
    else:
        with open(MANIFEST_PATH, "a", encoding="utf-8") as f:
            f.write(f"{incoming_digest}  {posix_path}\n")
        print(f"[HASH RECORDED] Baseline registered for {posix_path}: {incoming_digest[:12]}...")

    temp_path = target_path.with_suffix(".tmp")

    with open(temp_path, "wb") as f:
        f.write(serialized_bytes)
    temp_path.replace(target_path)
    print(f"[COMMITTED] Safely written to {posix_path}")
