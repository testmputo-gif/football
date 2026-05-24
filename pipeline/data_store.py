"""
pipeline/data_store.py
The entire "database" layer.
Reads and writes JSON files in the data/ directory.
All pipeline steps go through this — never write files directly.

Design principle: every read returns a safe default if file doesn't exist.
Every write is atomic (write to temp file, then rename) to prevent corruption.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional
from pipeline.config import PATHS

log = logging.getLogger(__name__)


def _read(path: Path, default: Any = None) -> Any:
    """Read a JSON file. Returns default if file doesn't exist."""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log.warning(f"Could not read {path}: {e}")
    return default


def _write(path: Path, data: Any):
    """
    Atomic write: write to temp file first, then rename.
    Prevents corruption if process is killed mid-write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        tmp.rename(path)
        log.debug(f"Written: {path}")
    except Exception as e:
        log.error(f"Failed to write {path}: {e}")
        if tmp.exists():
            tmp.unlink()
        raise


# ── Upcoming Fixtures ─────────────────────────────────────────────────────────

def get_upcoming_fixtures() -> dict:
    return _read(PATHS["upcoming"], {"last_updated": None, "fixtures": []})

def save_upcoming_fixtures(data: dict):
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(PATHS["upcoming"], data)
    log.info(f"Saved {len(data.get('fixtures', []))} upcoming fixtures")


# ── Team Statistics ───────────────────────────────────────────────────────────

def get_team_statistics() -> dict:
    """Returns dict keyed by team_id (int) → stats dict."""
    raw = _read(PATHS["team_stats"], {"last_updated": None, "teams": {}})
    # Keys come back as strings from JSON — convert to int
    raw["teams"] = {int(k): v for k, v in raw.get("teams", {}).items()}
    return raw

def save_team_statistics(data: dict):
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(PATHS["team_stats"], data)
    log.info(f"Saved statistics for {len(data.get('teams', {}))} teams")


# ── League Baselines ──────────────────────────────────────────────────────────

def get_league_baselines() -> dict:
    """Returns dict keyed by league_id (int) → baseline dict."""
    raw = _read(PATHS["baselines"], {"last_updated": None, "leagues": {}})
    raw["leagues"] = {int(k): v for k, v in raw.get("leagues", {}).items()}
    return raw

def save_league_baselines(data: dict):
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(PATHS["baselines"], data)
    log.info(f"Saved baselines for {len(data.get('leagues', {}))} leagues")


# ── Predictions ───────────────────────────────────────────────────────────────

def get_predictions(for_date: date = None) -> dict:
    if for_date is None:
        for_date = date.today()
    path = PATHS["predictions_dir"] / f"{for_date.isoformat()}.json"
    return _read(path, {"date": for_date.isoformat(), "fixtures": []})

def save_predictions(data: dict, for_date: date = None):
    if for_date is None:
        for_date = date.today()
    path = PATHS["predictions_dir"] / f"{for_date.isoformat()}.json"
    data["date"] = for_date.isoformat()
    data["generated_at"] = datetime.utcnow().isoformat()
    _write(path, data)

    # Always keep latest.json updated — frontend reads this
    _write(PATHS["predictions_dir"] / "latest.json", data)
    log.info(f"Saved {len(data.get('fixtures', []))} predictions for {for_date}")

def get_all_prediction_dates() -> list[str]:
    """Return list of dates that have prediction files."""
    pred_dir = PATHS["predictions_dir"]
    dates = []
    for f in pred_dir.glob("????-??-??.json"):
        dates.append(f.stem)
    return sorted(dates, reverse=True)


# ── Accuracy / Results ────────────────────────────────────────────────────────

def get_accuracy_data() -> dict:
    return _read(PATHS["accuracy"], {
        "last_updated": None,
        "total_evaluated": 0,
        "by_market": {
            "winner":  {"total": 0, "correct": 0},
            "over25":  {"total": 0, "correct": 0},
            "btts":    {"total": 0, "correct": 0},
            "corners": {"total": 0, "correct": 0},
            "cards":   {"total": 0, "correct": 0},
        },
        "calibration": {},   # market → bucket → {total, correct}
        "recent_results": [] # last 50 evaluated predictions
    })

def save_accuracy_data(data: dict):
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(PATHS["accuracy"], data)


# ── Match History (used for stats calculation) ────────────────────────────────

def get_match_history() -> dict:
    """
    Stores all imported completed matches.
    Keyed by api_fixture_id to prevent duplicates.
    """
    path = PATHS["predictions_dir"].parent.parent / "data" / "matches" / "history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _read(path, {"last_updated": None, "matches": {}})
    return raw

def save_match_history(data: dict):
    path = PATHS["predictions_dir"].parent.parent / "data" / "matches" / "history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(path, data)
    log.info(f"Saved {len(data.get('matches', {}))} historical matches")


# ── Model Metadata ────────────────────────────────────────────────────────────

def get_model_meta() -> dict:
    return _read(PATHS["model_meta"], {
        "version": "v1.0.0",
        "last_trained": None,
        "training_samples": 0,
        "ml_available": False,
        "accuracy_on_training": {}
    })

def save_model_meta(data: dict):
    _write(PATHS["model_meta"], data)


# ── Pipeline Logs ─────────────────────────────────────────────────────────────

def save_pipeline_log(log_data: dict):
    today = date.today().isoformat()
    path = PATHS["logs_dir"] / f"pipeline_{today}.json"
    _write(path, log_data)

def get_pipeline_log(for_date: date = None) -> dict:
    if for_date is None:
        for_date = date.today()
    path = PATHS["logs_dir"] / f"pipeline_{for_date.isoformat()}.json"
    return _read(path, {})


# ── H2H Records ───────────────────────────────────────────────────────────────

def get_h2h_data() -> dict:
    path = PATHS["predictions_dir"].parent.parent / "data" / "h2h" / "records.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return _read(path, {"last_updated": None, "records": {}})

def save_h2h_data(data: dict):
    path = PATHS["predictions_dir"].parent.parent / "data" / "h2h" / "records.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(path, data)

def get_h2h_key(team1_id: int, team2_id: int) -> str:
    """Canonical H2H key — always smaller ID first."""
    return f"{min(team1_id, team2_id)}_{max(team1_id, team2_id)}"


# ── Referee Profiles ──────────────────────────────────────────────────────────

def get_referee_data() -> dict:
    path = PATHS["predictions_dir"].parent.parent / "data" / "referees" / "profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return _read(path, {"last_updated": None, "referees": {}})

def save_referee_data(data: dict):
    path = PATHS["predictions_dir"].parent.parent / "data" / "referees" / "profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(path, data)
