"""
pipeline/step1_import_data.py
Imports match data from TWO free APIs simultaneously.

SOURCE 1: football-data.org (already working)
  - Brazil Serie A        (active now - runs to December)
  - Copa Libertadores     (active now - runs to November)
  - All European leagues  (auto-enables August 1st)
  - Champions League      (auto-enables September 1st)

SOURCE 2: BSD API - sports.bzzoiro.com (new - no rate limits, free)
  - Norway Eliteserien    (active now - runs to December)
  - Sweden Allsvenskan    (active now - runs to November)
  - Japan J1 League       (active now - runs to November)
  - South Korea K League  (active now - runs to November)

IMPORTANT: All data is ADDED to existing history.json, never replaced.
Each match has a unique ID. If a match already exists it is skipped.
Your existing Brazil and Copa data is completely safe.
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

# ── API credentials ───────────────────────────────────────────────────────────
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
BSD_KEY           = os.environ.get("BSD_API_KEY", "")

FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
BSD_BASE           = "https://sports.bzzoiro.com/api"


# ─────────────────────────────────────────────────────────────────────────────
# COMPETITION LISTS
# ─────────────────────────────────────────────────────────────────────────────

def get_football_data_competitions() -> list:
    """
    Returns competitions to pull from football-data.org.
    Automatically adds European leagues on 1 August.
    Automatically adds Champions League on 1 September.
    """
    today = date.today()
    month = today.month

    # Always active on football-data.org free tier
    always = [
        {
            "code":      "BSA",
            "name":      "Brasileirao Serie A",
            "country":   "Brazil",
            "league_id": 71,
            "season":    2025,
            "source":    "football_data",
        },
        {
            "code":      "CLI",
            "name":      "Copa Libertadores",
            "country":   "South America",
            "league_id": 13,
            "season":    2025,
            "source":    "football_data",
        },
    ]

    # European leagues restart August every year
    european = [
        {"code": "PL",  "name": "Premier League",  "country": "England",     "league_id": 39,  "season": 2025, "source": "football_data"},
        {"code": "BL1", "name": "Bundesliga",       "country": "Germany",     "league_id": 78,  "season": 2025, "source": "football_data"},
        {"code": "SA",  "name": "Serie A",          "country": "Italy",       "league_id": 135, "season": 2025, "source": "football_data"},
        {"code": "PD",  "name": "La Liga",          "country": "Spain",       "league_id": 140, "season": 2025, "source": "football_data"},
        {"code": "FL1", "name": "Ligue 1",          "country": "France",      "league_id": 61,  "season": 2025, "source": "football_data"},
        {"code": "DED", "name": "Eredivisie",       "country": "Netherlands", "league_id": 88,  "season": 2025, "source": "football_data"},
        {"code": "PPL", "name": "Primeira Liga",    "country": "Portugal",    "league_id": 94,  "season": 2025, "source": "football_data"},
        {"code": "ELC", "name": "Championship",     "country": "England",     "league_id": 40,  "season": 2025, "source": "football_data"},
    ]

    # Champions League starts September
    ucl = [
        {"code": "CL", "name": "Champions League", "country": "Europe", "league_id": 2, "season": 2025, "source": "football_data"},
    ]

    active = list(always)

    if month >= 8:
        active.extend(european)
        log.info("August+ detected: European leagues ACTIVE on football-data.org")
    else:
        days_left = (date(today.year, 8, 1) - today).days
        log.info(
            f"Summer break: European leagues auto-enable in "
            f"{days_left} days (1 August {today.year})"
        )

    if month >= 9:
        active.extend(ucl)
        log.info("September+ detected: Champions League ACTIVE")

    return active


def get_bsd_competitions() -> list:
    """
    Returns competitions to pull from BSD API (sports.bzzoiro.com).
    These are active NOW (summer leagues) and supplement football-data.org.

    BSD league IDs discovered from their /api/leagues/ endpoint.
    Common IDs based on their documentation examples.
    """
    today = date.today()
    month = today.month

    # Active year-round or during summer
    # These BSD league IDs are based on their API documentation
    summer_active = [
        {
            "bsd_league_id": 8,
            "name":          "Eliteserien",
            "country":       "Norway",
            "league_id":     103,   # Internal ID for our stats engine
            "season":        2026,
            "source":        "bsd",
        },
        {
            "bsd_league_id": 9,
            "name":          "Allsvenskan",
            "country":       "Sweden",
            "league_id":     113,
            "season":        2026,
            "source":        "bsd",
        },
        {
            "bsd_league_id": 49,
            "name":          "J1 League",
            "country":       "Japan",
            "league_id":     98,
            "season":        2026,
            "source":        "bsd",
        },
        {
            "bsd_league_id": 55,
            "name":          "K League 1",
            "country":       "South Korea",
            "league_id":     292,
            "season":        2026,
            "source":        "bsd",
        },
    ]

    return summer_active


# ─────────────────────────────────────────────────────────────────────────────
# API REQUEST HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def football_data_get(endpoint: str, params: dict = None) -> dict | None:
    """GET request to football-data.org with rate limit retry."""
    url = f"{FOOTBALL_DATA_BASE}/{endpoint}"
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    try:
        r = httpx.get(url, headers=headers, params=params or {}, timeout=30.0)
        if r.status_code == 429:
            log.warning("football-data.org rate limited - waiting 65s")
            time.sleep(65)
            r = httpx.get(url, headers=headers, params=params or {}, timeout=30.0)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 403:
            log.error(f"403 Forbidden: {endpoint} - not on your free tier plan")
            return None
        elif r.status_code == 401:
            log.error("401 Unauthorised - FOOTBALL_DATA_API_KEY is wrong or missing")
            return None
        else:
            log.error(f"HTTP {r.status_code} on {endpoint}: {r.text[:200]}")
            return None
    except Exception as e:
        log.error(f"football-data.org request failed: {e}")
        return None


def bsd_get(endpoint: str, params: dict = None) -> dict | None:
    """GET request to BSD API (sports.bzzoiro.com). No rate limits."""
    url = f"{BSD_BASE}/{endpoint}"
    headers = {"Authorization": f"Token {BSD_KEY}"}
    try:
        r = httpx.get(url, headers=headers, params=params or {}, timeout=30.0)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 401:
            log.error("401 Unauthorised - BSD_API_KEY is wrong or missing in GitHub Secrets")
            return None
        elif r.status_code == 404:
            log.warning(f"404 Not found: {endpoint} - league may not exist in BSD")
            return None
        else:
            log.error(f"BSD HTTP {r.status_code} on {endpoint}: {r.text[:200]}")
            return None
    except Exception as e:
        log.error(f"BSD request failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# FOOTBALL-DATA.ORG IMPORTERS
# ─────────────────────────────────────────────────────────────────────────────

def import_from_football_data(comp: dict, match_history: dict, upcoming_data: dict) -> dict:
    """Import completed matches and upcoming fixtures from football-data.org."""
    code    = comp["code"]
    results = {"completed": 0, "upcoming": 0, "skipped": 0}

    # Completed matches - last 60 days
    try:
        date_from = (date.today() - timedelta(days=60)).isoformat()
        date_to   = date.today().isoformat()

        data = football_data_get(
            f"competitions/{code}/matches",
            {"dateFrom": date_from, "dateTo": date_to, "status": "FINISHED"}
        )

        if data and "matches" in data:
            for m in data["matches"]:
                result = _parse_football_data_match(m, comp, match_history)
                if result == "imported":
                    results["completed"] += 1
                else:
                    results["skipped"] += 1
            log.info(
                f"  [football-data] {comp['name']}: "
                f"{results['completed']} new completed matches"
            )
        else:
            log.warning(f"  [football-data] {comp['name']}: no completed matches returned")

        time.sleep(7)  # Respect 10 req/min limit

    except Exception as e:
        log.error(f"  [football-data] completed matches failed for {comp['name']}: {e}")

    # Upcoming fixtures - next 14 days
    try:
        date_from = date.today().isoformat()
        date_to   = (date.today() + timedelta(days=14)).isoformat()

        data = football_data_get(
            f"competitions/{code}/matches",
            {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED,TIMED"}
        )

        if data and "matches" in data:
            for m in data["matches"]:
                result = _parse_football_data_fixture(m, comp, upcoming_data)
                if result == "imported":
                    results["upcoming"] += 1
            log.info(
                f"  [football-data] {comp['name']}: "
                f"{results['upcoming']} upcoming fixtures"
            )
        else:
            log.warning(f"  [football-data] {comp['name']}: no upcoming fixtures")

        time.sleep(7)

    except Exception as e:
        log.error(f"  [football-data] upcoming fixtures failed for {comp['name']}: {e}")

    return results


def _parse_football_data_match(match: dict, comp: dict, match_history: dict) -> str:
    """Parse one completed match from football-data.org format."""
    match_id = match.get("id")
    if not match_id:
        return "skipped"

    # SAFETY CHECK: skip if already stored - protects existing data
    unique_key = f"fd_{match_id}"
    if unique_key in match_history["matches"]:
        return "skipped"

    ft     = match.get("score", {}).get("fullTime", {})
    home_g = ft.get("home")
    away_g = ft.get("away")
    if home_g is None or away_g is None:
        return "skipped"

    ht  = match.get("homeTeam", {})
    at  = match.get("awayTeam", {})
    ref = (match.get("referees") or [{}])[0].get("name")

    match_history["matches"][unique_key] = {
        "api_fixture_id":   unique_key,
        "league_id":        comp["league_id"],
        "league_name":      comp["name"],
        "home_team_id":     f"fd_{ht.get('id')}",
        "home_team_name":   ht.get("name") or ht.get("shortName"),
        "away_team_id":     f"fd_{at.get('id')}",
        "away_team_name":   at.get("name") or at.get("shortName"),
        "match_date":       match.get("utcDate", ""),
        "season":           comp.get("season", CURRENT_SEASON),
        "home_goals":       int(home_g),
        "away_goals":       int(away_g),
        "referee_name":     ref,
        "data_source":      "football_data",
        # Detailed stats not available on free tier
        "home_corners": None, "away_corners": None,
        "home_yellow_cards": None, "away_yellow_cards": None,
        "home_red_cards":    None, "away_red_cards":    None,
        "possession_home":   None, "possession_away":   None,
        "shots_home":        None, "shots_away":        None,
        "shots_on_target_home": None, "shots_on_target_away": None,
        "fouls_home":        None, "fouls_away":        None,
    }
    return "imported"


def _parse_football_data_fixture(match: dict, comp: dict, upcoming_data: dict) -> str:
    """Parse one upcoming fixture from football-data.org format."""
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

    unique_id = f"fd_{match_id}"
    if unique_id in {f["api_fixture_id"] for f in upcoming_data["fixtures"]}:
        return "skipped"

    upcoming_data["fixtures"].append({
        "id":              f"{comp['league_id']}_{home_id}_{away_id}_{fixture_dt.strftime('%Y%m%d')}",
        "api_fixture_id":  unique_id,
        "fixture_date":    utc_date,
        "league_id":       comp["league_id"],
        "league_name":     comp["name"],
        "league_country":  comp["country"],
        "league_logo":     None,
        "season":          comp.get("season", CURRENT_SEASON),
        "round":           str(match.get("matchday", "")),
        "venue":           None,
        "home_team_id":    f"fd_{home_id}",
        "home_team_name":  ht.get("name") or ht.get("shortName"),
        "home_team_logo":  ht.get("crest"),
        "away_team_id":    f"fd_{away_id}",
        "away_team_name":  at.get("name") or at.get("shortName"),
        "away_team_logo":  at.get("crest"),
        "referee_name":    None,
        "status":          match.get("status", "SCHEDULED"),
        "is_featured":     False,
        "data_source":     "football_data",
        "home_xg_adjustment": 1.0,
        "away_xg_adjustment": 1.0,
    })
    return "imported"


# ─────────────────────────────────────────────────────────────────────────────
# BSD API IMPORTERS
# ─────────────────────────────────────────────────────────────────────────────

def import_from_bsd(comp: dict, match_history: dict, upcoming_data: dict) -> dict:
    """Import completed matches and upcoming fixtures from BSD API."""
    league_id = comp["bsd_league_id"]
    results   = {"completed": 0, "upcoming": 0, "skipped": 0}

    # Completed matches - last 60 days
    try:
        date_from = (date.today() - timedelta(days=60)).isoformat()
        date_to   = date.today().isoformat()

        data = bsd_get("events/", {
            "league":    league_id,
            "date_from": date_from,
            "date_to":   date_to,
            "status":    "finished",
        })

        if data:
            # BSD returns either a list directly or {"events": [...]}
            matches = data if isinstance(data, list) else data.get("events", data.get("results", []))
            if isinstance(matches, list):
                for m in matches:
                    result = _parse_bsd_match(m, comp, match_history)
                    if result == "imported":
                        results["completed"] += 1
                    else:
                        results["skipped"] += 1
                log.info(
                    f"  [BSD] {comp['name']}: "
                    f"{results['completed']} new completed matches"
                )
            else:
                log.warning(f"  [BSD] {comp['name']}: unexpected response format")
        else:
            log.warning(f"  [BSD] {comp['name']}: no completed matches returned")

        time.sleep(1)  # BSD has no rate limit but be respectful

    except Exception as e:
        log.error(f"  [BSD] completed matches failed for {comp['name']}: {e}")

    # Upcoming fixtures - next 14 days
    try:
        date_from = date.today().isoformat()
        date_to   = (date.today() + timedelta(days=14)).isoformat()

        data = bsd_get("events/", {
            "league":    league_id,
            "date_from": date_from,
            "date_to":   date_to,
            "status":    "notstarted",
        })

        if data:
            fixtures = data if isinstance(data, list) else data.get("events", data.get("results", []))
            if isinstance(fixtures, list):
                for m in fixtures:
                    result = _parse_bsd_fixture(m, comp, upcoming_data)
                    if result == "imported":
                        results["upcoming"] += 1
                log.info(
                    f"  [BSD] {comp['name']}: "
                    f"{results['upcoming']} upcoming fixtures"
                )
        else:
            log.warning(f"  [BSD] {comp['name']}: no upcoming fixtures")

        time.sleep(1)

    except Exception as e:
        log.error(f"  [BSD] upcoming fixtures failed for {comp['name']}: {e}")

    return results


def _parse_bsd_match(match: dict, comp: dict, match_history: dict) -> str:
    """Parse one completed match from BSD API format."""
    match_id = match.get("id")
    if not match_id:
        return "skipped"

    unique_key = f"bsd_{match_id}"

    # SAFETY CHECK: skip if already stored
    if unique_key in match_history["matches"]:
        return "skipped"

    home_score = match.get("home_score")
    away_score = match.get("away_score")
    if home_score is None or away_score is None:
        return "skipped"

    # BSD uses different field names - handle both old and new formats
    home_team_name = (
        match.get("home_team") or
        match.get("home_team_name") or
        match.get("homeTeam", {}).get("name", "Unknown")
    )
    away_team_name = (
        match.get("away_team") or
        match.get("away_team_name") or
        match.get("awayTeam", {}).get("name", "Unknown")
    )
    home_team_id = match.get("home_team_id") or match.get("homeTeam", {}).get("id", 0)
    away_team_id = match.get("away_team_id") or match.get("awayTeam", {}).get("id", 0)

    event_date = match.get("event_date") or match.get("date") or match.get("utcDate", "")

    match_history["matches"][unique_key] = {
        "api_fixture_id":   unique_key,
        "league_id":        comp["league_id"],
        "league_name":      comp["name"],
        "home_team_id":     f"bsd_{home_team_id}",
        "home_team_name":   home_team_name,
        "away_team_id":     f"bsd_{away_team_id}",
        "away_team_name":   away_team_name,
        "match_date":       event_date,
        "season":           comp.get("season", CURRENT_SEASON),
        "home_goals":       int(home_score),
        "away_goals":       int(away_score),
        "referee_name":     None,
        "data_source":      "bsd",
        # BSD free tier - detailed stats may not be available
        "home_corners": None, "away_corners": None,
        "home_yellow_cards": None, "away_yellow_cards": None,
        "home_red_cards":    None, "away_red_cards":    None,
        "possession_home":   None, "possession_away":   None,
        "shots_home":        None, "shots_away":        None,
        "shots_on_target_home": None, "shots_on_target_away": None,
        "fouls_home":        None, "fouls_away":        None,
    }
    return "imported"


def _parse_bsd_fixture(match: dict, comp: dict, upcoming_data: dict) -> str:
    """Parse one upcoming fixture from BSD API format."""
    match_id = match.get("id")
    if not match_id:
        return "skipped"

    unique_id = f"bsd_{match_id}"
    if unique_id in {f["api_fixture_id"] for f in upcoming_data["fixtures"]}:
        return "skipped"

    home_team_name = (
        match.get("home_team") or
        match.get("home_team_name") or
        match.get("homeTeam", {}).get("name", "Unknown")
    )
    away_team_name = (
        match.get("away_team") or
        match.get("away_team_name") or
        match.get("awayTeam", {}).get("name", "Unknown")
    )
    home_team_id = match.get("home_team_id") or match.get("homeTeam", {}).get("id", 0)
    away_team_id = match.get("away_team_id") or match.get("awayTeam", {}).get("id", 0)

    event_date = match.get("event_date") or match.get("date") or match.get("utcDate", "")

    # Parse date for the fixture ID
    try:
        if event_date:
            dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y%m%d")
        else:
            date_str = date.today().strftime("%Y%m%d")
    except Exception:
        date_str = date.today().strftime("%Y%m%d")

    upcoming_data["fixtures"].append({
        "id":              f"{comp['league_id']}_{home_team_id}_{away_team_id}_{date_str}",
        "api_fixture_id":  unique_id,
        "fixture_date":    event_date,
        "league_id":       comp["league_id"],
        "league_name":     comp["name"],
        "league_country":  comp["country"],
        "league_logo":     None,
        "season":          comp.get("season", CURRENT_SEASON),
        "round":           str(match.get("round") or match.get("matchday") or ""),
        "venue":           match.get("venue") or match.get("stadium"),
        "home_team_id":    f"bsd_{home_team_id}",
        "home_team_name":  home_team_name,
        "home_team_logo":  match.get("home_team_logo") or match.get("home_badge"),
        "away_team_id":    f"bsd_{away_team_id}",
        "away_team_name":  away_team_name,
        "away_team_logo":  match.get("away_team_logo") or match.get("away_badge"),
        "referee_name":    None,
        "status":          match.get("status", "notstarted"),
        "is_featured":     False,
        "data_source":     "bsd",
        "home_xg_adjustment": 1.0,
        "away_xg_adjustment": 1.0,
    })
    return "imported"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RUN FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def run():
    log.info("=" * 60)
    log.info("Step 1: Importing data from football-data.org + BSD API")
    log.info("=" * 60)

    # Load EXISTING data - this is the key line that protects your data
    # All new matches are ADDED to this, nothing is ever deleted
    match_history = get_match_history()
    if "matches" not in match_history:
        match_history["matches"] = {}

    existing_count = len(match_history["matches"])
    log.info(f"Existing match history: {existing_count} matches (will be preserved)")

    upcoming_data  = {"fixtures": []}
    referee_data   = get_referee_data()
    if "referees" not in referee_data:
        referee_data["referees"] = {}

    total_new_matches   = 0
    total_new_fixtures  = 0
    total_skipped       = 0
    sources_used        = []

    # ── SOURCE 1: football-data.org ───────────────────────────────────────────
    if FOOTBALL_DATA_KEY:
        log.info("\n--- SOURCE 1: football-data.org ---")
        fd_comps = get_football_data_competitions()
        log.info(f"Competitions: {[c['name'] for c in fd_comps]}")

        for comp in fd_comps:
            log.info(f"\nProcessing: {comp['name']}")
            r = import_from_football_data(comp, match_history, upcoming_data)
            total_new_matches   += r["completed"]
            total_new_fixtures  += r["upcoming"]
            total_skipped       += r["skipped"]

        sources_used.append("football-data.org")
    else:
        log.error("FOOTBALL_DATA_API_KEY not set - skipping football-data.org")

    # ── SOURCE 2: BSD API (sports.bzzoiro.com) ────────────────────────────────
    if BSD_KEY:
        log.info("\n--- SOURCE 2: BSD API (sports.bzzoiro.com) ---")
        bsd_comps = get_bsd_competitions()
        log.info(f"Competitions: {[c['name'] for c in bsd_comps]}")

        for comp in bsd_comps:
            log.info(f"\nProcessing: {comp['name']}")
            r = import_from_bsd(comp, match_history, upcoming_data)
            total_new_matches   += r["completed"]
            total_new_fixtures  += r["upcoming"]
            total_skipped       += r["skipped"]

        sources_used.append("BSD API")
    else:
        log.warning(
            "BSD_API_KEY not set - skipping Norway/Sweden/Japan/Korea leagues. "
            "Add BSD_API_KEY to GitHub Secrets to enable these leagues."
        )

    # Save everything
    save_match_history(match_history)
    save_upcoming_fixtures(upcoming_data)
    save_referee_data(referee_data)

    final_count = len(match_history["matches"])

    log.info("\n" + "=" * 60)
    log.info("Step 1 Complete")
    log.info(f"  Sources used:          {', '.join(sources_used)}")
    log.info(f"  Match history before:  {existing_count}")
    log.info(f"  New matches added:     {total_new_matches}")
    log.info(f"  Match history after:   {final_count}")
    log.info(f"  Already known skipped: {total_skipped}")
    log.info(f"  Upcoming fixtures:     {total_new_fixtures}")
    log.info("=" * 60)

    return {
        "sources_used":       sources_used,
        "existing_matches":   existing_count,
        "new_matches":        total_new_matches,
        "total_matches":      final_count,
        "upcoming_fixtures":  total_new_fixtures,
        "skipped":            total_skipped,
    }


if __name__ == "__main__":
    run()
