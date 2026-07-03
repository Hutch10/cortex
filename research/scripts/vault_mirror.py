"""
vault_mirror.py — lightweight cloud-aware mirror for specimen photos + aviation vault.

Behavior:
- Detect basic internet availability.
- If online, mirror local specimen image files and aviation DB to an encrypted container path.
- On Windows, attempts EFS encryption via `cipher /E` for at-rest protection.
"""

from __future__ import annotations

import json
import shutil
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs"
ENCRYPTED_CONTAINER_DIR = OUTPUTS_DIR / "encrypted_container" / "latest"
MANIFEST_PATH = OUTPUTS_DIR / "encrypted_container" / "mirror_manifest.json"

AVIATION_DB = (
    Path.home() / "AppData" / "Roaming" / "Aero Cortex Hub"
    / "data" / "tenants" / "internal" / "marine.sqlite"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _has_internet(timeout_sec: float = 1.5) -> bool:
    targets = [("1.1.1.1", 53), ("8.8.8.8", 53)]
    for host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=timeout_sec):
                return True
        except OSError:
            continue
    return False


def _ensure_specimen_inventory_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS specimen_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expedition_id INTEGER,
            timestamp TEXT NOT NULL,
            image_path TEXT,
            yield_stars INTEGER NOT NULL,
            color TEXT,
            hardness REAL,
            mineral_class TEXT,
            notes TEXT,
            latitude REAL,
            longitude REAL,
            transport_suggestion_json TEXT
        )
        """
    )
    conn.commit()


def _collect_specimen_image_paths() -> list[Path]:
    paths: list[Path] = []

    specimen_dir = OUTPUTS_DIR / "specimens"
    if specimen_dir.exists():
        for item in specimen_dir.rglob("*"):
            if item.is_file():
                paths.append(item)

    if not AVIATION_DB.exists():
        return paths

    try:
        conn = sqlite3.connect(str(AVIATION_DB))
        try:
            _ensure_specimen_inventory_table(conn)
            rows = conn.execute(
                """
                SELECT image_path
                FROM specimen_inventory
                WHERE image_path IS NOT NULL
                  AND TRIM(image_path) <> ''
                """
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return paths

    seen = {p.resolve() for p in paths if p.exists()}
    for row in rows:
        raw = str(row[0] or "").strip()
        if not raw:
            continue
        lower = raw.lower()
        # Keep remote/mobile references in manifest only; local copies need local files.
        if lower.startswith(("mobile://", "http://", "https://", "s3://", "gs://")):
            continue

        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        if candidate.exists() and candidate.is_file():
            resolved = candidate.resolve()
            if resolved not in seen:
                paths.append(candidate)
                seen.add(resolved)

    return paths


def _encrypt_container_windows(container_dir: Path) -> tuple[bool, str | None]:
    if sys.platform != "win32":
        return False, "EFS cipher encryption is only available on Windows."

    try:
        result = subprocess.run(
            ["cipher", "/E", f"/S:{container_dir}"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"cipher invocation failed: {exc}"

    if result.returncode == 0:
        return True, None

    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    msg = stderr or stdout or f"cipher exited with code {result.returncode}"
    return False, msg


def _latest_container_timestamp(container_dir: Path) -> str | None:
    if not container_dir.exists():
        return None

    latest_mtime = None
    for item in container_dir.rglob("*"):
        if not item.is_file():
            continue
        try:
            mtime = item.stat().st_mtime
        except OSError:
            continue
        if latest_mtime is None or mtime > latest_mtime:
            latest_mtime = mtime

    if latest_mtime is None:
        return None
    return datetime.fromtimestamp(latest_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_mirror() -> dict:
    status: dict = {
        "checked_at": _utc_now(),
        "internet_detected": False,
        "mirrored": False,
        "encrypted": False,
        "container": str(ENCRYPTED_CONTAINER_DIR),
        "latest_container_timestamp": None,
        "specimen_files_mirrored": 0,
        "aviation_vault_mirrored": False,
        "notes": [],
    }

    if not _has_internet():
        status["notes"].append("No internet detected; cloud mirror skipped.")
        return status

    status["internet_detected"] = True

    ENCRYPTED_CONTAINER_DIR.mkdir(parents=True, exist_ok=True)
    (ENCRYPTED_CONTAINER_DIR / "specimens").mkdir(parents=True, exist_ok=True)
    (ENCRYPTED_CONTAINER_DIR / "aviation").mkdir(parents=True, exist_ok=True)

    specimen_paths = _collect_specimen_image_paths()
    mirrored_count = 0
    for src in specimen_paths:
        try:
            dest = ENCRYPTED_CONTAINER_DIR / "specimens" / src.name
            shutil.copy2(src, dest)
            mirrored_count += 1
        except OSError as exc:
            status["notes"].append(f"specimen copy failed ({src}): {exc}")

    status["specimen_files_mirrored"] = mirrored_count

    if AVIATION_DB.exists():
        try:
            shutil.copy2(AVIATION_DB, ENCRYPTED_CONTAINER_DIR / "aviation" / "marine.sqlite")
            status["aviation_vault_mirrored"] = True
        except OSError as exc:
            status["notes"].append(f"aviation vault copy failed: {exc}")
    else:
        status["notes"].append("Aviation vault DB not found; skipped DB mirror.")

    encrypted, enc_error = _encrypt_container_windows(ENCRYPTED_CONTAINER_DIR)
    status["encrypted"] = encrypted
    if enc_error:
        status["notes"].append(enc_error)

    status["mirrored"] = status["aviation_vault_mirrored"] or (mirrored_count > 0)
    status["latest_container_timestamp"] = _latest_container_timestamp(ENCRYPTED_CONTAINER_DIR)

    manifest = {
        "generated_at": status["checked_at"],
        "container": status["container"],
        "latest_container_timestamp": status["latest_container_timestamp"],
        "internet_detected": status["internet_detected"],
        "mirrored": status["mirrored"],
        "encrypted": status["encrypted"],
        "specimen_files_mirrored": status["specimen_files_mirrored"],
        "aviation_vault_mirrored": status["aviation_vault_mirrored"],
        "notes": status["notes"],
    }

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return status


def main() -> None:
    result = run_mirror()
    print(json.dumps(result, sort_keys=True))
    sys.exit(0)


if __name__ == "__main__":
    main()
