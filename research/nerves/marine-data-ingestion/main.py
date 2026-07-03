"""Compatibility wrapper for the marine data ingestion nerve CLI."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nerves.marine_data_ingestion.main import main


if __name__ == "__main__":
    raise SystemExit(main())
