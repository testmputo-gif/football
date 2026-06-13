"""
pipeline/data_store.py
The entire database layer.
Reads and writes JSON files in the data/ directory.
All pipeline steps go through this - never write files directly.

Design principle:
  - Every read returns a safe default if file does not exist
  - Every write is atomic (write to temp, then rename) to prevent corruption
  - Keys can be strings or integers - handled safely everywhere
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Any
from pipeline.config import PATHS

log = logging.getLogger(__name__)


def _read(path: Path, default: Any = None) -> Any:
    """Read a JSON file. Returns default if file does not exist or is corrupt."""
    try:
        if path.exists() and path.stat().st_size > 2:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log.warning(f"Could not read {path}: {e}")
    return default


def _write(path: Path, data: Any):
    """
    Atomic write: write to temp file first then rename.
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


def _safe_key(k: Any) -> Any:
    """
    Safely convert a JSON key to the right type.
    Keys can be plain integers like 1234 or prefixed strings like fd_1234 or bsd_5678.
    We keep them as strings to handle both cases safely.
    """
    return str(k)


# ── Upcoming Fixtures ──────────────────────────────────────────────────────────

def get_upcoming_fixtures() -> dict:
    return _read(PATHS["upcoming"], {"last_updated": None, "fixtures": []})


def save_upcoming_fixtures(data: dict):
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(PATHS["upcoming"], data)
    log.info(f"Saved {len(data.get('fixtures', []))} upcoming fixtures")


# ── Team Statistics ────────────────────────────────────────────────────────────

def get_team_statistics() -> dict:
    """Returns dict keyed by team_id as STRING to handle fd_/bsd_ prefixes."""
    raw = _read(PATHS["team_stats"], {"last_updated": None, "teams": {}})
    # Keep all keys as strings - handles both int keys and prefixed string keys
    raw["teams"] = {_safe_key(k): v for k, v in raw.get("teams", {}).items()}
    return raw


def save_team_statistics(data: dict):
    # Ensure all keys are strings before saving
    data["teams"] = {_safe_key(k): v for k, v in data.get("teams", {}).items()}
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(PATHS["team_stats"], data)
    log.info(f"Saved statistics for {len(data.get('teams', {}))} teams")


# ── League Baselines ────────────────────────────────────────────────────────────

def get_league_baselines() -> dict:
    """Returns dict keyed by league_id as STRING."""
    raw = _read(PATHS["baselines"], {"last_updated": None, "leagues": {}})
    raw["leagues"] = {_safe_key(k): v for k, v in raw.get("leagues", {}).items()}
    return raw


def save_league_baselines(data: dict):
    data["leagues"] = {_safe_key(k): v for k, v in data.get("leagues", {}).items()}
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(PATHS["baselines"], data)
    log.info(f"Saved baselines for {len(data.get('leagues', {}))} leagues")


# ── Predictions ────────────────────────────────────────────────────────────────

def get_predictions(for_date: date = None) -> dict:
    if for_date is None:
        for_date = date.today()
    path = PATHS["predictions_dir"] / f"{for_date.isoformat()}.json"
    return _read(path, {"date": for_date.isoformat(), "fixtures": []})


def save_predictions(data: dict, for_date: date = None):
    if for_date is None:
        for_date = date.today()
    path = PATHS["predictions_dir"] / f"{for_date.isoformat()}.json"
    data["date"]         = for_date.isoformat()
    data["generated_at"] = datetime.utcnow().isoformat()
    _write(path, data)
    # Always keep latest.json updated - frontend reads this
    _write(PATHS["predictions_dir"] / "latest.json", data)
    log.info(f"Saved {len(data.get('fixtures', []))} predictions for {for_date}")


def get_all_prediction_dates() -> list[str]:
    pred_dir = PATHS["predictions_dir"]
    return sorted([f.stem for f in pred_dir.glob("????-??-??.json")], reverse=True)


# ── Accuracy / Results ──────────────────────────────────────────────────────────

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
        "calibration": {},
        "recent_results": []
    })


def save_accuracy_data(data: dict):
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(PATHS["accuracy"], data)


# ── Match History ───────────────────────────────────────────────────────────────

def get_match_history() -> dict:
    """
    Stores all imported completed matches.
    Keys are unique match IDs like fd_12345 or bsd_67890.
    """
    path = PATHS["predictions_dir"].parent / "matches" / "history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _read(path, {"last_updated": None, "matches": {}})
    # Keep all keys as strings
    raw["matches"] = {_safe_key(k): v for k, v in raw.get("matches", {}).items()}
    return raw


def save_match_history(data: dict):
    path = PATHS["predictions_dir"].parent / "matches" / "history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data["matches"]      = {_safe_key(k): v for k, v in data.get("matches", {}).items()}
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(path, data)
    log.info(f"Saved {len(data.get('matches', {}))} historical matches")


# ── Model Metadata ──────────────────────────────────────────────────────────────

def get_model_meta() -> dict:
    return _read(PATHS["model_meta"], {
        "version":              "v1.0.0",
        "last_trained":         None,
        "training_samples":     0,
        "ml_available":         False,
        "accuracy_on_training": {}
    })


def save_model_meta(data: dict):
    _write(PATHS["model_meta"], data)


# ── Pipeline Logs ───────────────────────────────────────────────────────────────

def save_pipeline_log(log_data: dict):
    today = date.today().isoformat()
    path  = PATHS["logs_dir"] / f"pipeline_{today}.json"
    _write(path, log_data)


def get_pipeline_log(for_date: date = None) -> dict:
    if for_date is None:
        for_date = date.today()
    path = PATHS["logs_dir"] / f"pipeline_{for_date.isoformat()}.json"
    return _read(path, {})


# ── H2H Records ─────────────────────────────────────────────────────────────────

def get_h2h_data() -> dict:
    path = PATHS["predictions_dir"].parent / "h2h" / "records.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return _read(path, {"last_updated": None, "records": {}})


def save_h2h_data(data: dict):
    path = PATHS["predictions_dir"].parent / "h2h" / "records.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(path, data)


def get_h2h_key(team1_id: Any, team2_id: Any) -> str:
    """Canonical H2H key - always lexicographically smaller ID first."""
    k1 = _safe_key(team1_id)
    k2 = _safe_key(team2_id)
    return f"{min(k1, k2)}_{max(k1, k2)}"


# ── Referee Profiles ─────────────────────────────────────────────────────────────

def get_referee_data() -> dict:
    path = PATHS["predictions_dir"].parent / "referees" / "profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return _read(path, {"last_updated": None, "referees": {}})


def save_referee_data(data: dict):
    path = PATHS["predictions_dir"].parent / "referees" / "profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.utcnow().isoformat()
    _write(path, data)
