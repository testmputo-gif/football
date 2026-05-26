"""
pipeline/config.py
All pipeline configuration.
Secrets come from GitHub Actions Secrets - never hardcoded here.
"""

import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

PATHS = {
    "upcoming":        DATA / "fixtures"     / "upcoming.json",
    "team_stats":      DATA / "teams"        / "statistics.json",
    "baselines":       DATA / "leagues"      / "baselines.json",
    "accuracy":        DATA / "accuracy"     / "results.json",
    "model_meta":      DATA / "models"       / "model_meta.json",
    "predictions_dir": DATA / "predictions",
    "models_dir":      DATA / "models",
    "logs_dir":        DATA / "logs",
}

# Ensure all data directories exist
for _p in [
    DATA / "fixtures", DATA / "teams", DATA / "leagues",
    DATA / "accuracy", DATA / "models", DATA / "logs",
    DATA / "predictions", DATA / "matches",
    DATA / "h2h", DATA / "referees",
]:
    _p.mkdir(parents=True, exist_ok=True)

# ── API Configuration ─────────────────────────────────────────────────────────
FOOTBALL_API_KEY       = os.environ.get("FOOTBALL_API_KEY", "")
FOOTBALL_API_BASE_URL  = "https://v3.football.api-sports.io"
FOOTBALL_API_HOST      = "v3.football.api-sports.io"
FOOTBALL_API_DAILY_LIMIT    = 100
FOOTBALL_API_SAFETY_BUFFER  = 10

FOOTBALL_DATA_API_KEY  = os.environ.get("FOOTBALL_DATA_API_KEY", "")
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"

# ── Season ────────────────────────────────────────────────────────────────────
CURRENT_SEASON = int(os.environ.get("CURRENT_SEASON", "2025"))

# ── Active Leagues ────────────────────────────────────────────────────────────
# These are used by step2_calculate_stats.py
# Brazil (71) and Copa Libertadores (13) are always included
# European leagues are added automatically in August by step1_import_data.py

ACTIVE_LEAGUES = [
    {"id": 71,  "name": "Brasileirao Serie A", "country": "Brazil"},
    {"id": 13,  "name": "Copa Libertadores",   "country": "South America"},
    {"id": 39,  "name": "Premier League",      "country": "England"},
    {"id": 78,  "name": "Bundesliga",          "country": "Germany"},
    {"id": 135, "name": "Serie A",             "country": "Italy"},
    {"id": 140, "name": "La Liga",             "country": "Spain"},
    {"id": 61,  "name": "Ligue 1",             "country": "France"},
    {"id": 88,  "name": "Eredivisie",          "country": "Netherlands"},
    {"id": 94,  "name": "Primeira Liga",       "country": "Portugal"},
    {"id": 40,  "name": "Championship",        "country": "England"},
    {"id": 2,   "name": "Champions League",    "country": "Europe"},
]

# All league IDs in one flat list - used for filtering match data
ACTIVE_LEAGUE_IDS = [league["id"] for league in ACTIVE_LEAGUES]

# ── Prediction Engine Thresholds ──────────────────────────────────────────────
MIN_MATCHES_FOR_PREDICTION = 8
MIN_HOME_AWAY_MATCHES      = 4
WINNER_GATE_MARGIN         = 0.08

CONFIDENCE_CAPS = {
    "winner":    82.0,
    "over15":    85.0,
    "over25":    88.0,
    "over35":    82.0,
    "btts":      85.0,
    "corners":   78.0,
    "cards":     72.0,
    "fh_over05": 75.0,
}

CONFIDENCE_FLOORS = {
    "winner":    53.0,
    "over15":    55.0,
    "over25":    55.0,
    "over35":    53.0,
    "btts":      55.0,
    "corners":   53.0,
    "cards":     50.0,
    "fh_over05": 52.0,
}

# ── ML Model Settings ─────────────────────────────────────────────────────────
MIN_TRAINING_SAMPLES = 200
MODEL_VERSION        = os.environ.get("MODEL_VERSION", "v1.0.0")

# ── Logging ───────────────────────────────────────────────────────────────────
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
