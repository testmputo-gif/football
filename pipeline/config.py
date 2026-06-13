"""
pipeline/config.py
All pipeline configuration.
Secrets come from GitHub Actions Secrets - never hardcoded here.
"""

import os
from datetime import date as _date
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

for _p in [
    DATA / "fixtures", DATA / "teams", DATA / "leagues",
    DATA / "accuracy", DATA / "models", DATA / "logs",
    DATA / "predictions", DATA / "matches",
    DATA / "h2h", DATA / "referees",
]:
    _p.mkdir(parents=True, exist_ok=True)

# ── API Configuration ─────────────────────────────────────────────────────────
# All sources below are free and require no API key.
# OpenLigaDB — completely free, no key needed (Germany + Austria)
OPENLIGADB_BASE_URL = "https://api.openligadb.de"

# ── Season — auto-detected from current date ──────────────────────────────────
# European leagues: season = year the season STARTED (2025/26 → 2025)
# Year-round leagues (Nordic, South American): season = calendar year
# Logic: if month >= 6, year-round leagues are in the CURRENT year.
#        European seasons start in August — we keep them as "current year - 1"
#        until they restart. CURRENT_SEASON env var overrides everything.
_today = _date.today()
_auto_season = _today.year if _today.month >= 6 else _today.year - 1
CURRENT_SEASON = int(os.environ.get("CURRENT_SEASON") or _auto_season)

# ── Active Leagues ────────────────────────────────────────────────────────────
ACTIVE_LEAGUES = [
    # ── Year-round South America ──────────────────────────────────────────────
    {"id": 71,  "name": "Brasileirao Serie A",        "country": "Brazil",        "year_round": True},
    {"id": 13,  "name": "Copa Libertadores",          "country": "South America", "year_round": True},
    {"id": 11,  "name": "Copa Sudamericana",          "country": "South America", "year_round": True},
    {"id": 128, "name": "Argentine Primera Division", "country": "Argentina",     "year_round": True},
    {"id": 72,  "name": "Brasileirao Serie B",        "country": "Brazil",        "year_round": True},

    # ── Year-round North America ──────────────────────────────────────────────
    {"id": 253, "name": "MLS",                        "country": "USA",           "year_round": True},

    # ── Year-round Asia/Pacific ───────────────────────────────────────────────
    {"id": 98,  "name": "J1 League",                  "country": "Japan",         "year_round": True},
    {"id": 292, "name": "K League 1",                 "country": "South Korea",   "year_round": True},

    # ── Scandinavian / Nordic (Apr-Nov) ───────────────────────────────────────
    {"id": 103, "name": "Eliteserien Norway",         "country": "Norway",        "year_round": True},
    {"id": 113, "name": "Allsvenskan Sweden",         "country": "Sweden",        "year_round": True},
    {"id": 244, "name": "Finnish Veikkausliiga",      "country": "Finland",       "year_round": True},
    {"id": 119, "name": "Denmark Superliga",          "country": "Denmark",       "year_round": False},

    # ── Year-round / early-restart Europe ────────────────────────────────────
    {"id": 88,  "name": "Eredivisie",                 "country": "Netherlands",   "year_round": False},
    {"id": 218, "name": "Austrian Bundesliga",        "country": "Austria",       "year_round": True},
    {"id": 94,  "name": "Primeira Liga",              "country": "Portugal",      "year_round": False},

    # ── Major European (resume Aug) ───────────────────────────────────────────
    {"id": 39,  "name": "Premier League",             "country": "England",       "year_round": False},
    {"id": 40,  "name": "Championship",               "country": "England",       "year_round": False},
    {"id": 78,  "name": "Bundesliga",                 "country": "Germany",       "year_round": False},
    {"id": 135, "name": "Serie A",                    "country": "Italy",         "year_round": False},
    {"id": 140, "name": "La Liga",                    "country": "Spain",         "year_round": False},
    {"id": 61,  "name": "Ligue 1",                    "country": "France",        "year_round": False},
    {"id": 2,   "name": "Champions League",           "country": "Europe",        "year_round": False},
    {"id": 3,   "name": "Europa League",              "country": "Europe",        "year_round": False},
]

ACTIVE_LEAGUE_IDS     = [league["id"] for league in ACTIVE_LEAGUES]
YEAR_ROUND_LEAGUE_IDS = [l["id"] for l in ACTIVE_LEAGUES if l.get("year_round")]

# ── Prediction Engine Thresholds ──────────────────────────────────────────────
MIN_MATCHES_FOR_PREDICTION = 5
MIN_HOME_AWAY_MATCHES      = 3
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
