#!/usr/bin/env python3
"""
pipeline/seed_empty_data.py
Creates empty stub JSON files so the frontend loads cleanly
before the first pipeline run. Run this once after cloning.

  python pipeline/seed_empty_data.py
"""
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

stubs = {
    "data/fixtures/upcoming.json": {
        "last_updated": None,
        "fixtures": []
    },
    "data/predictions/latest.json": {
        "date": datetime.utcnow().date().isoformat(),
        "generated_at": None,
        "model_version": "v1.0.0",
        "ml_active": False,
        "total_fixtures": 0,
        "predictions_made": 0,
        "fixtures": []
    },
    "data/teams/statistics.json": {
        "last_updated": None,
        "teams": {}
    },
    "data/leagues/baselines.json": {
        "last_updated": None,
        "leagues": {}
    },
    "data/accuracy/results.json": {
        "last_updated": None,
        "total_evaluated": 0,
        "by_market": {},
        "calibration": {},
        "recent_results": []
    },
    "data/models/model_meta.json": {
        "version": "v1.0.0",
        "last_trained": None,
        "training_samples": 0,
        "ml_available": False,
        "accuracy_on_training": {}
    },
    "data/matches/history.json": {
        "last_updated": None,
        "matches": {}
    },
    "data/h2h/records.json": {
        "last_updated": None,
        "records": {}
    },
    "data/referees/profiles.json": {
        "last_updated": None,
        "referees": {}
    },
    "data/logs/api_usage.json": {}
}

for path_str, content in stubs.items():
    path = ROOT / path_str
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(content, indent=2))
        print(f"✅ Created: {path_str}")
    else:
        print(f"⏭  Already exists: {path_str}")

print("\nDone. Commit these stub files, then run the daily pipeline (no API keys needed).")
