"""
pipeline/config.py
All pipeline configuration. Secrets come from environment variables
(set in GitHub Actions Secrets — never hardcoded here).
"""

import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent          # repo root
DATA = ROOT / "data"
PIPELINE = ROOT / "pipeline"

PATHS = {
    "upcoming":     DATA / "fixtures" / "upcoming.json",
    "team_stats":   DATA / "teams" / "statistics.json",
    "baselines":    DATA / "leagues" / "baselines.json",
    "accuracy":     DATA / "accuracy" / "results.json",
    "model_meta":   DATA / "models" / "model_meta.json",
    "predictions_dir": DATA / "predictions",
    "models_dir":   DATA / "models",
    "logs_dir":     DATA / "logs",
}

# Ensure all data directories exist
for path in [DATA / d for d in ["fixtures", "teams", "leagues", "accuracy", "models", "logs", "predictions"]]:
    path.mkdir(parents=True, exist_ok=True)

# ── API Configuration ─────────────────────────────────────────────────────────
FOOTBALL_API_KEY       = os.environ.get("FOOTBALL_API_KEY", "")
FOOTBALL_API_BASE_URL  = "https://v3.football.api-sports.io"
FOOTBALL_API_HOST      = "v3.football.api-sports.io"
FOOTBALL_API_DAILY_LIMIT = 100
FOOTBALL_API_SAFETY_BUFFER = 10   # Stop at 90 to leave buffer

FOOTBALL_DATA_API_KEY  = os.environ.get("FOOTBALL_DATA_API_KEY", "")
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"

# ── Active Leagues ─────────────────────────────────────────────────────────────
# API-Football IDs: 39=EPL, 140=La Liga, 78=Bundesliga, 135=Serie A, 61=Ligue 1
ACTIVE_LEAGUES = [
    {"id": 39,  "name": "English Premier League", "country": "England"},
    {"id": 140, "name": "La Liga",                "country": "Spain"},
    {"id": 78,  "name": "Bundesliga",             "country": "Germany"},
    {"id": 135, "name": "Serie A",                "country": "Italy"},
    {"id": 61,  "name": "Ligue 1",                "country": "France"},
]
ACTIVE_LEAGUE_IDS = [l["id"] for l in ACTIVE_LEAGUES]
CURRENT_SEASON = int(os.environ.get("CURRENT_SEASON", "2025"))

# ── Prediction Engine Thresholds ──────────────────────────────────────────────
MIN_MATCHES_FOR_PREDICTION = 8   # Min completed matches needed
MIN_HOME_AWAY_MATCHES      = 4   # Min home OR away matches
WINNER_GATE_MARGIN         = 0.08  # Min gap between top 2 win probabilities

# Per-market confidence caps (football is genuinely uncertain)
CONFIDENCE_CAPS = {
    "winner":   82.0,
    "over15":   85.0,
    "over25":   88.0,
    "over35":   82.0,
    "btts":     85.0,
    "corners":  78.0,
    "cards":    72.0,
    "fh_over05": 75.0,
}

# Minimum confidence to output a pick (below this = no_pick)
CONFIDENCE_FLOORS = {
    "winner":   53.0,
    "over15":   55.0,
    "over25":   55.0,
    "over35":   53.0,
    "btts":     55.0,
    "corners":  53.0,
    "cards":    50.0,
    "fh_over05": 52.0,
}

# ── ML Model Settings ─────────────────────────────────────────────────────────
MIN_TRAINING_SAMPLES = 200   # Minimum matches to train ML models
MODEL_VERSION        = os.environ.get("MODEL_VERSION", "v1.0.0")

# ── Logging ───────────────────────────────────────────────────────────────────
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
