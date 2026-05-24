"""
pipeline/step1_import_data.py
Imports completed match results and upcoming fixtures from football API.
Writes to:
  data/matches/history.json   — completed matches (training data)
  data/fixtures/upcoming.json — next 7 days fixtures
  data/referees/profiles.json — referee discipline data (updated from match stats)

This is the ONLY step that calls the external API.
Budget: uses ~2 API calls per league = 10 calls for 5 leagues.
Remaining ~80 calls available for H2H fetches and fixture stats.
"""

import logging
import time
from datetime import datetime, timedelta, date
from pipeline.config import ACTIVE_LEAGUES, CURRENT_SEASON, PATHS
from pipeline.api_client import primary_api, RateLimitExceeded, get_calls_remaining
from pipeline.data_store import (
    get_match_history, save_match_history,
    get_upcoming_fixtures, save_upcoming_fixtures,
    get_referee_data, save_referee_data,
    save_pipeline_log
)

log = logging.getLogger(__name__)


def run():
    """Main entry point for step 1."""
    start = time.time()
    stats = {
        "matches_imported": 0,
        "matches_skipped": 0,
        "fixtures_imported": 0,
        "fixtures_skipped": 0,
        "api_calls_used": 0,
        "errors": []
    }

    log.info(f"Step 1: Import data — {get_calls_remaining()} API calls remaining today")

    match_history = get_match_history()
    if "matches" not in match_history:
        match_history["matches"] = {}

    upcoming_data = {"fixtures": []}
    referee_data = get_referee_data()
    if "referees" not in referee_data:
        referee_data["referees"] = {}

    for league in ACTIVE_LEAGUES:
        league_id = league["id"]
        log.info(f"Processing league: {league['name']}")

        # ── Import completed matches ──────────────────────────────────────────
        try:
            results = primary_api.get_fixtures(
                league_id=league_id,
                season=CURRENT_SEASON,
                status="FT",   # Full Time only
                next_n=None,
            )
            # Get last 20 finished matches
            params = {"league": league_id, "season": CURRENT_SEASON, "status": "FT", "last": 20}
            data = primary_api.get("fixtures", params)
            results = data.get("response", []) if data else []
            stats["api_calls_used"] += 1

            for fixture_data in results:
                result = _process_completed_match(fixture_data, match_history, referee_data, league)
                if result == "imported":
                    stats["matches_imported"] += 1
                else:
                    stats["matches_skipped"] += 1

        except RateLimitExceeded as e:
            log.warning(f"Rate limit during match import: {e}")
            stats["errors"].append(str(e))
            break
        except Exception as e:
            log.error(f"Failed to import matches for {league['name']}: {e}")
            stats["errors"].append(str(e))

        # ── Import upcoming fixtures ──────────────────────────────────────────
        try:
            fixture_results = primary_api.get_fixtures(
                league_id=league_id,
                season=CURRENT_SEASON,
                next_n=21  # Next ~7 days worth
            )
            stats["api_calls_used"] += 1

            for fixture_data in fixture_results:
                result = _process_upcoming_fixture(fixture_data, upcoming_data, league)
                if result == "imported":
                    stats["fixtures_imported"] += 1
                else:
                    stats["fixtures_skipped"] += 1

        except RateLimitExceeded as e:
            log.warning(f"Rate limit during fixture import: {e}")
            break
        except Exception as e:
            log.error(f"Failed to import fixtures for {league['name']}: {e}")

    # Save all data
    save_match_history(match_history)
    save_upcoming_fixtures(upcoming_data)
    save_referee_data(referee_data)

    elapsed = round(time.time() - start, 1)
    log.info(
        f"Step 1 complete in {elapsed}s: "
        f"{stats['matches_imported']} matches, "
        f"{stats['fixtures_imported']} fixtures imported, "
        f"{stats['api_calls_used']} API calls used"
    )
    return stats


def _process_completed_match(fixture_data: dict, match_history: dict, referee_data: dict, league: dict) -> str:
    """Parse and store one completed match."""
    fixture = fixture_data.get("fixture", {})
    teams = fixture_data.get("teams", {})
    goals = fixture_data.get("goals", {})

    api_id = fixture.get("id")
    if not api_id:
        return "skipped"

    # Skip if already stored
    if str(api_id) in match_history["matches"]:
        return "skipped"

    # Only finished matches
    status = fixture.get("status", {}).get("short", "")
    if status not in ("FT", "AET", "PEN"):
        return "skipped"

    home_goals = goals.get("home")
    away_goals = goals.get("away")
    if home_goals is None or away_goals is None:
        return "skipped"

    # Parse statistics
    stats_raw = fixture_data.get("statistics", [])
    parsed_stats = _parse_statistics(stats_raw)

    # Referee
    referee_name = fixture.get("referee")
    if referee_name:
        _update_referee_stats(referee_name, parsed_stats, referee_data)

    match_date = fixture.get("date", "")

    match_record = {
        "api_fixture_id": api_id,
        "league_id": league["id"],
        "league_name": league["name"],
        "home_team_id": teams.get("home", {}).get("id"),
        "home_team_name": teams.get("home", {}).get("name"),
        "away_team_id": teams.get("away", {}).get("id"),
        "away_team_name": teams.get("away", {}).get("name"),
        "match_date": match_date,
        "season": CURRENT_SEASON,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "referee_name": referee_name,
        **parsed_stats
    }

    match_history["matches"][str(api_id)] = match_record
    return "imported"


def _process_upcoming_fixture(fixture_data: dict, upcoming_data: dict, league: dict) -> str:
    """Parse and store one upcoming fixture."""
    fixture = fixture_data.get("fixture", {})
    teams = fixture_data.get("teams", {})

    api_id = fixture.get("id")
    if not api_id:
        return "skipped"

    status = fixture.get("status", {}).get("short", "")
    if status in ("FT", "AET", "PEN", "CANC", "ABD", "PST"):
        return "skipped"

    fixture_date_str = fixture.get("date", "")
    try:
        fixture_date = datetime.fromisoformat(fixture_date_str.replace("Z", "+00:00"))
        # Only include fixtures in the next 7 days
        now = datetime.now().astimezone()
        if fixture_date < now or fixture_date > now + timedelta(days=7):
            return "skipped"
    except Exception:
        return "skipped"

    home_id = teams.get("home", {}).get("id")
    away_id = teams.get("away", {}).get("id")
    if not home_id or not away_id:
        return "skipped"

    fixture_record = {
        "id": f"{league['id']}_{home_id}_{away_id}_{fixture_date.strftime('%Y%m%d')}",
        "api_fixture_id": api_id,
        "fixture_date": fixture_date_str,
        "league_id": league["id"],
        "league_name": league["name"],
        "league_country": league["country"],
        "league_logo": None,
        "season": CURRENT_SEASON,
        "round": fixture.get("round"),
        "venue": fixture.get("venue", {}).get("name"),
        "home_team_id": home_id,
        "home_team_name": teams.get("home", {}).get("name"),
        "home_team_logo": teams.get("home", {}).get("logo"),
        "away_team_id": away_id,
        "away_team_name": teams.get("away", {}).get("name"),
        "away_team_logo": teams.get("away", {}).get("logo"),
        "referee_name": fixture.get("referee"),
        "status": status,
        "is_featured": False,
    }

    # Deduplicate by api_fixture_id
    existing_ids = {f["api_fixture_id"] for f in upcoming_data["fixtures"]}
    if api_id not in existing_ids:
        upcoming_data["fixtures"].append(fixture_record)
        return "imported"
    return "skipped"


def _parse_statistics(statistics: list) -> dict:
    """Extract match statistics from API response."""
    result = {
        "home_corners": None, "away_corners": None,
        "home_yellow_cards": None, "away_yellow_cards": None,
        "home_red_cards": None, "away_red_cards": None,
        "possession_home": None, "possession_away": None,
        "shots_home": None, "shots_away": None,
        "shots_on_target_home": None, "shots_on_target_away": None,
        "fouls_home": None, "fouls_away": None,
    }
    if not statistics or len(statistics) < 2:
        return result

    home_stats = {s["type"]: s["value"] for s in statistics[0].get("statistics", [])}
    away_stats = {s["type"]: s["value"] for s in statistics[1].get("statistics", [])}

    def si(val):
        try: return int(val) if val is not None else None
        except: return None

    def sf(val):
        try:
            if isinstance(val, str) and "%" in val:
                return float(val.replace("%", ""))
            return float(val) if val is not None else None
        except: return None

    result.update({
        "home_corners": si(home_stats.get("Corner Kicks")),
        "away_corners": si(away_stats.get("Corner Kicks")),
        "home_yellow_cards": si(home_stats.get("Yellow Cards")),
        "away_yellow_cards": si(away_stats.get("Yellow Cards")),
        "home_red_cards": si(home_stats.get("Red Cards")),
        "away_red_cards": si(away_stats.get("Red Cards")),
        "possession_home": sf(home_stats.get("Ball Possession")),
        "possession_away": sf(away_stats.get("Ball Possession")),
        "shots_home": si(home_stats.get("Total Shots")),
        "shots_away": si(away_stats.get("Total Shots")),
        "shots_on_target_home": si(home_stats.get("Shots on Goal")),
        "shots_on_target_away": si(away_stats.get("Shots on Goal")),
        "fouls_home": si(home_stats.get("Fouls")),
        "fouls_away": si(away_stats.get("Fouls")),
    })
    return result


def _update_referee_stats(name: str, match_stats: dict, referee_data: dict):
    """Update referee running averages from match data."""
    if name not in referee_data["referees"]:
        referee_data["referees"][name] = {
            "name": name,
            "matches_officiated": 0,
            "total_yellow_cards": 0,
            "total_red_cards": 0,
            "total_fouls": 0,
            "avg_yellow_cards": None,
            "avg_red_cards": None,
        }

    ref = referee_data["referees"][name]
    yellows = (match_stats.get("home_yellow_cards") or 0) + (match_stats.get("away_yellow_cards") or 0)
    reds = (match_stats.get("home_red_cards") or 0) + (match_stats.get("away_red_cards") or 0)
    fouls = (match_stats.get("fouls_home") or 0) + (match_stats.get("fouls_away") or 0)

    ref["matches_officiated"] += 1
    ref["total_yellow_cards"] += yellows
    ref["total_red_cards"] += reds
    ref["total_fouls"] += fouls

    n = ref["matches_officiated"]
    ref["avg_yellow_cards"] = round(ref["total_yellow_cards"] / n, 3)
    ref["avg_red_cards"] = round(ref["total_red_cards"] / n, 3)


if __name__ == "__main__":
    run()
