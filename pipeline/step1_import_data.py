"""
pipeline/step1_import_data.py
Imports match data using football-data.org API.
Free, no daily cap, no RapidAPI needed.
Covers: EPL, La Liga, Bundesliga, Serie A, Ligue 1
"""

import httpx
import json
import logging
import time
from datetime import datetime, timedelta, date
from pathlib import Path
from pipeline.config import PATHS, CURRENT_SEASON
from pipeline.data_store import (
    get_match_history, save_match_history,
    get_upcoming_fixtures, save_upcoming_fixtures,
    get_referee_data, save_referee_data,
    save_pipeline_log
)
import os

log = logging.getLogger(__name__)

API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_KEY}

# football-data.org competition codes and their IDs
COMPETITIONS = [
    {"code": "PL",  "name": "English Premier League", "country": "England",  "league_id": 39},
    {"code": "PD",  "name": "La Liga",                "country": "Spain",    "league_id": 140},
    {"code": "BL1", "name": "Bundesliga",             "country": "Germany",  "league_id": 78},
    {"code": "SA",  "name": "Serie A",                "country": "Italy",    "league_id": 135},
    {"code": "FL1", "name": "Ligue 1",                "country": "France",   "league_id": 61},
]


def api_get(endpoint: str, params: dict = None) -> dict | None:
    """Make a request to football-data.org"""
    url = f"{BASE_URL}/{endpoint}"
    try:
        response = httpx.get(url, headers=HEADERS, params=params or {}, timeout=30.0)
        if response.status_code == 429:
            log.warning("Rate limited — waiting 65 seconds")
            time.sleep(65)
            response = httpx.get(url, headers=HEADERS, params=params or {}, timeout=30.0)
        if response.status_code == 200:
            return response.json()
        else:
            log.error(f"API error {response.status_code} for {endpoint}: {response.text[:200]}")
            return None
    except Exception as e:
        log.error(f"Request failed for {endpoint}: {e}")
        return None


def run():
    log.info("Step 1: Importing data from football-data.org")

    if not API_KEY:
        log.error("FOOTBALL_DATA_API_KEY is not set! Add it to GitHub Secrets.")
        return {"error": "missing_api_key"}

    match_history = get_match_history()
    if "matches" not in match_history:
        match_history["matches"] = {}

    upcoming_data = {"fixtures": []}
    referee_data = get_referee_data()
    if "referees" not in referee_data:
        referee_data["referees"] = {}

    total_matches = 0
    total_fixtures = 0

    for comp in COMPETITIONS:
        code = comp["code"]
        log.info(f"Processing {comp['name']}...")

        # ── Get recent completed matches ──────────────────────────────────
        try:
            # Get matches from last 60 days
            date_from = (date.today() - timedelta(days=60)).isoformat()
            date_to = date.today().isoformat()

            data = api_get(
                f"competitions/{code}/matches",
                {"dateFrom": date_from, "dateTo": date_to, "status": "FINISHED"}
            )

            if data and "matches" in data:
                for match in data["matches"]:
                    result = _process_completed_match(match, comp, match_history)
                    if result == "imported":
                        total_matches += 1

                log.info(f"  {comp['name']}: imported {len(data['matches'])} completed matches")
            else:
                log.warning(f"  {comp['name']}: no completed matches returned")

            time.sleep(6)  # Be respectful — 10 req/min limit

        except Exception as e:
            log.error(f"Failed completed matches for {comp['name']}: {e}")

        # ── Get upcoming fixtures ─────────────────────────────────────────
        try:
            date_from = date.today().isoformat()
            date_to = (date.today() + timedelta(days=7)).isoformat()

            data = api_get(
                f"competitions/{code}/matches",
                {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED,TIMED"}
            )

            if data and "matches" in data:
                for match in data["matches"]:
                    result = _process_upcoming_fixture(match, comp, upcoming_data)
                    if result == "imported":
                        total_fixtures += 1

                log.info(f"  {comp['name']}: imported {len(data['matches'])} upcoming fixtures")
            else:
                log.warning(f"  {comp['name']}: no upcoming fixtures returned")

            time.sleep(6)

        except Exception as e:
            log.error(f"Failed upcoming fixtures for {comp['name']}: {e}")

    save_match_history(match_history)
    save_upcoming_fixtures(upcoming_data)
    save_referee_data(referee_data)

    log.info(f"Step 1 complete: {total_matches} matches, {total_fixtures} fixtures imported")
    return {"matches_imported": total_matches, "fixtures_imported": total_fixtures}


def _process_completed_match(match: dict, comp: dict, match_history: dict) -> str:
    """Parse and store one completed match from football-data.org format."""
    match_id = match.get("id")
    if not match_id:
        return "skipped"

    if str(match_id) in match_history["matches"]:
        return "skipped"  # Already have this match

    score = match.get("score", {})
    full_time = score.get("fullTime", {})
    home_goals = full_time.get("home")
    away_goals = full_time.get("away")

    if home_goals is None or away_goals is None:
        return "skipped"

    home_team = match.get("homeTeam", {})
    away_team = match.get("awayTeam", {})

    match_record = {
        "api_fixture_id": match_id,
        "league_id": comp["league_id"],
        "league_name": comp["name"],
        "home_team_id": home_team.get("id"),
        "home_team_name": home_team.get("name") or home_team.get("shortName"),
        "away_team_id": away_team.get("id"),
        "away_team_name": away_team.get("name") or away_team.get("shortName"),
        "match_date": match.get("utcDate", ""),
        "season": CURRENT_SEASON,
        "home_goals": int(home_goals),
        "away_goals": int(away_goals),
        "referee_name": None,
        # football-data.org free tier doesn't include detailed stats
        # so these will be None — the statistical engine handles missing data
        "home_corners": None, "away_corners": None,
        "home_yellow_cards": None, "away_yellow_cards": None,
        "home_red_cards": None, "away_red_cards": None,
        "possession_home": None, "possession_away": None,
        "shots_home": None, "shots_away": None,
        "shots_on_target_home": None, "shots_on_target_away": None,
        "fouls_home": None, "fouls_away": None,
    }

    # Get referee if available
    referees = match.get("referees", [])
    if referees:
        match_record["referee_name"] = referees[0].get("name")

    match_history["matches"][str(match_id)] = match_record
    return "imported"


def _process_upcoming_fixture(match: dict, comp: dict, upcoming_data: dict) -> str:
    """Parse and store one upcoming fixture from football-data.org format."""
    match_id = match.get("id")
    if not match_id:
        return "skipped"

    home_team = match.get("homeTeam", {})
    away_team = match.get("awayTeam", {})

    home_id = home_team.get("id")
    away_id = away_team.get("id")

    if not home_id or not away_id:
        return "skipped"

    utc_date = match.get("utcDate", "")
    try:
        fixture_date = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
    except Exception:
        return "skipped"

    # Deduplicate
    existing_ids = {f["api_fixture_id"] for f in upcoming_data["fixtures"]}
    if match_id in existing_ids:
        return "skipped"

    fixture_record = {
        "id": f"{comp['league_id']}_{home_id}_{away_id}_{fixture_date.strftime('%Y%m%d')}",
        "api_fixture_id": match_id,
        "fixture_date": utc_date,
        "league_id": comp["league_id"],
        "league_name": comp["name"],
        "league_country": comp["country"],
        "league_logo": None,
        "season": CURRENT_SEASON,
        "round": match.get("matchday", ""),
        "venue": None,
        "home_team_id": home_id,
        "home_team_name": home_team.get("name") or home_team.get("shortName"),
        "home_team_logo": home_team.get("crest"),
        "away_team_id": away_id,
        "away_team_name": away_team.get("name") or away_team.get("shortName"),
        "away_team_logo": away_team.get("crest"),
        "referee_name": None,
        "status": match.get("status", "SCHEDULED"),
        "is_featured": False,
        "home_xg_adjustment": 1.0,
        "away_xg_adjustment": 1.0,
    }

    upcoming_data["fixtures"].append(fixture_record)
    return "imported"


if __name__ == "__main__":
    run()
