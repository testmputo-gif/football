"""
pipeline/step1_import_data.py
Imports match data using football-data.org API.
Free, no daily cap, no RapidAPI needed.

ACTIVE NOW (June-December):
  - Brazil Serie A (BSA)      runs April to December
  - Copa Libertadores (CLI)   runs February to November

AUTO-ENABLES IN AUGUST automatically (no action needed):
  - Premier League, Bundesliga, Serie A, La Liga, Ligue 1
  - Eredivisie, Primeira Liga, Championship

AUTO-ENABLES IN SEPTEMBER automatically:
  - Champions League
"""

import httpx
import json
import logging
import time
import os
from datetime import datetime, timedelta, date
from pipeline.config import PATHS, CURRENT_SEASON
from pipeline.data_store import (
    get_match_history, save_match_history,
    get_upcoming_fixtures, save_upcoming_fixtures,
    get_referee_data, save_referee_data,
)

log = logging.getLogger(__name__)

API_KEY  = os.environ.get("FOOTBALL_DATA_API_KEY", "")
BASE_URL = "https://api.football-data.org/v4"
HEADERS  = {"X-Auth-Token": API_KEY}


def get_active_competitions() -> list:
    """
    Returns correct competition list based on TODAY's date.
    No manual changes ever needed - switches automatically.

    June-July   : Brazil + Copa only (European leagues off-season)
    August+     : Brazil + Copa + all 8 European leagues
    September+  : Everything above + Champions League
    """
    today = date.today()
    month = today.month

    # These run June through November/December every year
    always_active = [
        {
            "code":      "BSA",
            "name":      "Brasileirao Serie A",
            "country":   "Brazil",
            "league_id": 71,
            "season":    2025,
        },
        {
            "code":      "CLI",
            "name":      "Copa Libertadores",
            "country":   "South America",
            "league_id": 13,
            "season":    2025,
        },
    ]

    # European leagues: off June-July, back every August
    european = [
        {"code": "PL",  "name": "Premier League",  "country": "England",     "league_id": 39,  "season": 2025},
        {"code": "BL1", "name": "Bundesliga",       "country": "Germany",     "league_id": 78,  "season": 2025},
        {"code": "SA",  "name": "Serie A",          "country": "Italy",       "league_id": 135, "season": 2025},
        {"code": "PD",  "name": "La Liga",          "country": "Spain",       "league_id": 140, "season": 2025},
        {"code": "FL1", "name": "Ligue 1",          "country": "France",      "league_id": 61,  "season": 2025},
        {"code": "DED", "name": "Eredivisie",       "country": "Netherlands", "league_id": 88,  "season": 2025},
        {"code": "PPL", "name": "Primeira Liga",    "country": "Portugal",    "league_id": 94,  "season": 2025},
        {"code": "ELC", "name": "Championship",     "country": "England",     "league_id": 40,  "season": 2025},
    ]

    # Champions League starts September
    champions_league = [
        {"code": "CL", "name": "Champions League", "country": "Europe", "league_id": 2, "season": 2025},
    ]

    active = list(always_active)

    if month >= 8:
        active.extend(european)
        log.info("August detected - European leagues now ACTIVE")
    else:
        days_left = (date(today.year, 8, 1) - today).days
        log.info(
            f"June/July - European leagues on summer break. "
            f"They auto-enable in {days_left} days on 1 August {today.year}. "
            f"Running Brazil Serie A + Copa Libertadores."
        )

    if month >= 9:
        active.extend(champions_league)
        log.info("September detected - Champions League now ACTIVE")

    log.info(f"Competitions this run: {[c['name'] for c in active]}")
    return active


def api_get(endpoint: str, params: dict = None) -> dict | None:
    """GET request to football-data.org. Retries once on rate limit."""
    url = f"{BASE_URL}/{endpoint}"
    try:
        r = httpx.get(url, headers=HEADERS, params=params or {}, timeout=30.0)

        if r.status_code == 429:
            log.warning("Rate limited - waiting 65 seconds then retrying")
            time.sleep(65)
            r = httpx.get(url, headers=HEADERS, params=params or {}, timeout=30.0)

        if r.status_code == 200:
            return r.json()
        elif r.status_code == 403:
            log.error(
                f"403 Forbidden on {endpoint} - "
                f"this competition is not included in your free tier plan"
            )
            return None
        elif r.status_code == 401:
            log.error("401 Unauthorised - API key is wrong or missing in GitHub Secrets")
            return None
        else:
            log.error(f"HTTP {r.status_code} on {endpoint}: {r.text[:200]}")
            return None
    except Exception as e:
        log.error(f"Request failed for {endpoint}: {e}")
        return None


def run():
    log.info("Step 1: Importing data from football-data.org")

    if not API_KEY:
        log.error(
            "FOOTBALL_DATA_API_KEY secret is missing. "
            "Go to GitHub repo -> Settings -> Secrets -> Actions -> New secret"
        )
        return {"error": "missing_api_key"}

    match_history = get_match_history()
    if "matches" not in match_history:
        match_history["matches"] = {}

    upcoming_data  = {"fixtures": []}
    referee_data   = get_referee_data()
    if "referees" not in referee_data:
        referee_data["referees"] = {}

    total_matches  = 0
    total_fixtures = 0
    total_skipped  = 0

    for comp in get_active_competitions():
        code   = comp["code"]
        season = comp.get("season", CURRENT_SEASON)
        log.info(f"--- {comp['name']} (season {season}) ---")

        # Completed matches - last 60 days
        try:
            date_from = (date.today() - timedelta(days=60)).isoformat()
            date_to   = date.today().isoformat()

            data = api_get(
                f"competitions/{code}/matches",
                {"dateFrom": date_from, "dateTo": date_to, "status": "FINISHED"}
            )

            if data and "matches" in data:
                new = 0
                for m in data["matches"]:
                    if _process_completed_match(m, comp, match_history) == "imported":
                        new += 1
                        total_matches += 1
                    else:
                        total_skipped += 1
                log.info(f"  Completed: {new} new | {len(data['matches'])} returned")
            else:
                log.warning(f"  No completed matches for {comp['name']}")

            time.sleep(7)

        except Exception as e:
            log.error(f"Completed matches failed for {comp['name']}: {e}")

        # Upcoming fixtures - next 14 days
        try:
            date_from = date.today().isoformat()
            date_to   = (date.today() + timedelta(days=14)).isoformat()

            data = api_get(
                f"competitions/{code}/matches",
                {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED,TIMED"}
            )

            if data and "matches" in data:
                new = 0
                for m in data["matches"]:
                    if _process_upcoming_fixture(m, comp, upcoming_data) == "imported":
                        new += 1
                        total_fixtures += 1
                log.info(f"  Upcoming: {new} fixtures in next 14 days")
            else:
                log.warning(f"  No upcoming fixtures for {comp['name']}")

            time.sleep(7)

        except Exception as e:
            log.error(f"Upcoming fixtures failed for {comp['name']}: {e}")

    save_match_history(match_history)
    save_upcoming_fixtures(upcoming_data)
    save_referee_data(referee_data)

    log.info(
        f"Step 1 complete - "
        f"{total_matches} new matches, "
        f"{total_fixtures} upcoming fixtures"
    )

    return {
        "matches_imported":  total_matches,
        "fixtures_imported": total_fixtures,
        "matches_skipped":   total_skipped,
    }


def _process_completed_match(match: dict, comp: dict, match_history: dict) -> str:
    match_id = match.get("id")
    if not match_id or str(match_id) in match_history["matches"]:
        return "skipped"

    ft     = match.get("score", {}).get("fullTime", {})
    home_g = ft.get("home")
    away_g = ft.get("away")
    if home_g is None or away_g is None:
        return "skipped"

    ht  = match.get("homeTeam", {})
    at  = match.get("awayTeam", {})
    ref = (match.get("referees") or [{}])[0].get("name")

    match_history["matches"][str(match_id)] = {
        "api_fixture_id":        match_id,
        "league_id":             comp["league_id"],
        "league_name":           comp["name"],
        "home_team_id":          ht.get("id"),
        "home_team_name":        ht.get("name") or ht.get("shortName"),
        "away_team_id":          at.get("id"),
        "away_team_name":        at.get("name") or at.get("shortName"),
        "match_date":            match.get("utcDate", ""),
        "season":                comp.get("season", CURRENT_SEASON),
        "home_goals":            int(home_g),
        "away_goals":            int(away_g),
        "referee_name":          ref,
        # Free tier does not include detailed stats - engine handles None fine
        "home_corners": None, "away_corners": None,
        "home_yellow_cards": None, "away_yellow_cards": None,
        "home_red_cards":    None, "away_red_cards":    None,
        "possession_home":   None, "possession_away":   None,
        "shots_home":        None, "shots_away":        None,
        "shots_on_target_home": None, "shots_on_target_away": None,
        "fouls_home":        None, "fouls_away":        None,
    }
    return "imported"


def _process_upcoming_fixture(match: dict, comp: dict, upcoming_data: dict) -> str:
    match_id = match.get("id")
    if not match_id:
        return "skipped"

    ht      = match.get("homeTeam", {})
    at      = match.get("awayTeam", {})
    home_id = ht.get("id")
    away_id = at.get("id")
    if not home_id or not away_id:
        return "skipped"

    utc_date = match.get("utcDate", "")
    try:
        fixture_dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
    except Exception:
        return "skipped"

    # Deduplicate
    if match_id in {f["api_fixture_id"] for f in upcoming_data["fixtures"]}:
        return "skipped"

    upcoming_data["fixtures"].append({
        "id": f"{comp['league_id']}_{home_id}_{away_id}_{fixture_dt.strftime('%Y%m%d')}",
        "api_fixture_id":  match_id,
        "fixture_date":    utc_date,
        "league_id":       comp["league_id"],
        "league_name":     comp["name"],
        "league_country":  comp["country"],
        "league_logo":     None,
        "season":          comp.get("season", CURRENT_SEASON),
        "round":           str(match.get("matchday", "")),
        "venue":           None,
        "home_team_id":    home_id,
        "home_team_name":  ht.get("name") or ht.get("shortName"),
        "home_team_logo":  ht.get("crest"),
        "away_team_id":    away_id,
        "away_team_name":  at.get("name") or at.get("shortName"),
        "away_team_logo":  at.get("crest"),
        "referee_name":    None,
        "status":          match.get("status", "SCHEDULED"),
        "is_featured":     False,
        "home_xg_adjustment": 1.0,
        "away_xg_adjustment": 1.0,
    })
    return "imported"


if __name__ == "__main__":
    run()
