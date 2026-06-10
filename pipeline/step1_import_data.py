"""
pipeline/step1_import_data.py  — REWRITTEN

STRATEGY:
=========
The old approach fetched one league at a time, wasting API quota and missing
hundreds of active leagues. The new approach:

SOURCE 1 — API-Football (api-sports.io) free tier, 100 req/day
  • GET /fixtures?date=TODAY           → 1 request → ALL leagues, ALL fixtures today
  • GET /fixtures?date=YESTERDAY&status=FT → 1 request → ALL finished results
  • GET /fixtures?season=YEAR&league=X → 1 request per league for history backfill
    (spread across days using remaining quota — 98 requests left after dailies)

  This gives us Venezuela, Spain 2nd div, Brazil Serie B, Int'l friendlies,
  Costa Rica, Morocco, Argentina, Finland, Iceland, MLS — everything in 2 calls.

SOURCE 2 — football-data.org (free, 10 req/min, no daily cap)
  • Supplements with deeper data for top European leagues (when in season)
  • Also pulls Copa Libertadores and Brasileirao history

LEAGUES COVERED (year-round active right now):
  Brazil Serie A + B, Copa Libertadores, Copa Sudamericana,
  Argentina Liga Profesional, Venezuela, MLS, J1 League, K League 1,
  Sweden Allsvenskan, Norway Eliteserien, Finland Veikkausliiga,
  Iceland Urvalsdeild, Denmark Superliga, Turkey Super Lig,
  Austrian Bundesliga, Greek Super League, Scottish Premiership,
  Morocco Botola, International Friendlies + qualifiers

HISTORY BACKFILL:
  On first run for any new league, automatically pulls last 12 months of
  results so predictions start immediately (not after weeks of waiting).
"""

import httpx
import json
import logging
import time
import os
from datetime import datetime, timedelta, date, timezone
from pipeline.config import PATHS, CURRENT_SEASON
from pipeline.data_store import (
    get_match_history, save_match_history,
    get_upcoming_fixtures, save_upcoming_fixtures,
    get_referee_data, save_referee_data,
)

log = logging.getLogger(__name__)

FOOTBALL_DATA_KEY  = os.environ.get("FOOTBALL_DATA_API_KEY", "")
APISPORTS_KEY      = os.environ.get("FOOTBALL_DATA_API_KEY", "")  # same key works on both domains
APISPORTS_BASE     = "https://v3.football.api-sports.io"
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

# ── Which leagues to backfill history for (api-football league IDs) ───────────
# These are pulled once (or when teams have < 5 matches) to build history
HISTORY_LEAGUES = [
    # Year-round South America
    {"id": 71,  "name": "Brasileirao Serie A",        "season": 2025},
    {"id": 72,  "name": "Brasileirao Serie B",        "season": 2025},
    {"id": 13,  "name": "Copa Libertadores",          "season": 2025},
    {"id": 11,  "name": "Copa Sudamericana",          "season": 2025},
    {"id": 128, "name": "Argentine Liga Profesional", "season": 2025},
    {"id": 131, "name": "Venezuela Primera Division", "season": 2025},
    # Year-round North America
    {"id": 253, "name": "MLS",                        "season": 2025},
    # Year-round Asia
    {"id": 98,  "name": "J1 League",                  "season": 2026},
    {"id": 292, "name": "K League 1",                 "season": 2026},
    # Year-round Europe (summer leagues)
    {"id": 103, "name": "Eliteserien Norway",         "season": 2026},
    {"id": 113, "name": "Allsvenskan Sweden",         "season": 2026},
    {"id": 244, "name": "Veikkausliiga Finland",      "season": 2026},
    {"id": 164, "name": "Urvalsdeild Iceland",        "season": 2026},
    {"id": 119, "name": "Denmark Superliga",          "season": "2025-2026"},
    {"id": 203, "name": "Turkey Super Lig",           "season": "2024-2025"},
    {"id": 218, "name": "Austrian Bundesliga",        "season": "2024-2025"},
    {"id": 197, "name": "Greek Super League",         "season": "2024-2025"},
    {"id": 179, "name": "Scottish Premiership",       "season": "2024-2025"},
    {"id": 207, "name": "Swiss Super League",         "season": "2024-2025"},
    {"id": 301, "name": "Morocco Botola Pro",         "season": 2025},
    # European top leagues (winter — skip if not in season)
    {"id": 39,  "name": "Premier League",             "season": 2025, "month_start": 8},
    {"id": 78,  "name": "Bundesliga",                 "season": 2025, "month_start": 8},
    {"id": 135, "name": "Serie A",                    "season": 2025, "month_start": 8},
    {"id": 140, "name": "La Liga",                    "season": 2025, "month_start": 8},
    {"id": 61,  "name": "Ligue 1",                    "season": 2025, "month_start": 8},
    {"id": 88,  "name": "Eredivisie",                 "season": 2025, "month_start": 8},
    {"id": 2,   "name": "Champions League",           "season": 2025, "month_start": 9},
]

# How many history backfill requests to spend per pipeline run
# (saves remaining quota for future days)
MAX_BACKFILL_REQUESTS_PER_RUN = 15


# ─────────────────────────────────────────────────────────────────────────────
# HTTP HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def apisports_get(endpoint, params=None):
    """API-Football / api-sports.io — counts against 100/day quota."""
    url = f"{APISPORTS_BASE}/{endpoint}"
    headers = {
        "x-apisports-key": APISPORTS_KEY,
        "x-rapidapi-host": "v3.football.api-sports.io",
    }
    try:
        r = httpx.get(url, headers=headers, params=params or {}, timeout=30.0)
        if r.status_code == 429:
            log.warning("API-Sports rate limited — waiting 60s")
            time.sleep(60)
            r = httpx.get(url, headers=headers, params=params or {}, timeout=30.0)
        if r.status_code == 200:
            data = r.json()
            remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
            log.info(f"  [API-Sports] {endpoint} OK — {remaining} requests remaining today")
            return data
        log.error(f"API-Sports HTTP {r.status_code}: {r.text[:120]}")
        return None
    except Exception as e:
        log.error(f"API-Sports request failed: {e}")
        return None


def football_data_get(endpoint, params=None):
    """football-data.org — no daily cap, 10 req/min."""
    url = f"{FOOTBALL_DATA_BASE}/{endpoint}"
    try:
        r = httpx.get(url,
            headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
            params=params or {}, timeout=30.0)
        if r.status_code == 429:
            log.warning("football-data.org rate limited — waiting 65s")
            time.sleep(65)
            r = httpx.get(url,
                headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
                params=params or {}, timeout=30.0)
        if r.status_code == 200:
            return r.json()
        log.error(f"football-data HTTP {r.status_code}: {r.text[:120]}")
        return None
    except Exception as e:
        log.error(f"football-data request failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# BACKFILL DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def teams_needing_backfill(match_history, league_id, min_matches=5):
    """Returns list of team IDs with fewer than min_matches in this league."""
    team_counts = {}
    for m in match_history.get("matches", {}).values():
        if m.get("league_id") != league_id:
            continue
        for tid in [m.get("home_team_id"), m.get("away_team_id")]:
            if tid:
                team_counts[tid] = team_counts.get(tid, 0) + 1
    return [tid for tid, cnt in team_counts.items() if cnt < min_matches]


def league_needs_backfill(match_history, league_id, min_matches=5):
    """True if this league has no history or teams with too few matches."""
    league_matches = [
        m for m in match_history.get("matches", {}).values()
        if m.get("league_id") == league_id
    ]
    if len(league_matches) < 10:
        return True
    low = len(teams_needing_backfill(match_history, league_id, min_matches))
    total_teams = len(set(
        tid for m in league_matches
        for tid in [m.get("home_team_id"), m.get("away_team_id")] if tid
    ))
    return total_teams > 0 and low / total_teams > 0.25


# ─────────────────────────────────────────────────────────────────────────────
# PARSE API-FOOTBALL RESPONSES
# ─────────────────────────────────────────────────────────────────────────────

def parse_apisports_fixture(fix, match_history, upcoming_data, now_utc,
                             only_finished=False, only_upcoming=False):
    """
    Parse one fixture dict from api-sports.io response.
    Routes to history or upcoming based on status.
    """
    fid    = fix.get("fixture", {}).get("id")
    if not fid:
        return "skipped"

    status   = fix.get("fixture", {}).get("status", {}).get("short", "")
    date_str = fix.get("fixture", {}).get("date", "")
    league   = fix.get("league", {})
    teams    = fix.get("teams", {})
    goals    = fix.get("goals", {})

    league_id   = league.get("id")
    league_name = league.get("name", "Unknown")
    league_country = league.get("country", "")
    league_logo = league.get("logo")
    season      = league.get("season", CURRENT_SEASON)

    home = teams.get("home", {})
    away = teams.get("away", {})
    home_id   = home.get("id")
    away_id   = away.get("id")
    home_name = home.get("name", "Unknown")
    away_name = away.get("name", "Unknown")
    home_logo = home.get("logo")
    away_logo = away.get("logo")

    key = f"apisports_{fid}"

    # Finished match → add to history
    if status in ("FT", "AET", "PEN", "AWD") or \
       (status in ("FT",) and goals.get("home") is not None):
        if only_upcoming:
            return "skipped"
        if key in match_history["matches"]:
            return "skipped"
        home_g = goals.get("home")
        away_g = goals.get("away")
        if home_g is None or away_g is None:
            return "skipped"

        stats = fix.get("statistics") or []
        def get_stat(team_stats, stat_name):
            for s in team_stats:
                if s.get("type") == stat_name:
                    v = s.get("value")
                    return int(v) if v is not None and str(v).isdigit() else None
            return None

        home_stats = stats[0].get("statistics", []) if len(stats) > 0 else []
        away_stats = stats[1].get("statistics", []) if len(stats) > 1 else []

        match_history["matches"][key] = {
            "api_fixture_id": key,
            "league_id": league_id, "league_name": league_name,
            "home_team_id": f"ap_{home_id}", "home_team_name": home_name,
            "away_team_id": f"ap_{away_id}", "away_team_name": away_name,
            "match_date": date_str, "season": season,
            "home_goals": int(home_g), "away_goals": int(away_g),
            "referee_name": fix.get("fixture", {}).get("referee"),
            "venue": (fix.get("fixture", {}).get("venue") or {}).get("name") if isinstance(fix.get("fixture", {}).get("venue"), dict) else fix.get("fixture", {}).get("venue"),
            "data_source": "apisports",
            "home_corners": get_stat(home_stats, "Corner Kicks"),
            "away_corners": get_stat(away_stats, "Corner Kicks"),
            "home_yellow_cards": get_stat(home_stats, "Yellow Cards"),
            "away_yellow_cards": get_stat(away_stats, "Yellow Cards"),
            "home_red_cards": get_stat(home_stats, "Red Cards"),
            "away_red_cards": get_stat(away_stats, "Red Cards"),
            "possession_home": get_stat(home_stats, "Ball Possession"),
            "possession_away": get_stat(away_stats, "Ball Possession"),
            "shots_home": get_stat(home_stats, "Total Shots"),
            "shots_away": get_stat(away_stats, "Total Shots"),
            "shots_on_target_home": get_stat(home_stats, "Shots on Goal"),
            "shots_on_target_away": get_stat(away_stats, "Shots on Goal"),
            "fouls_home": get_stat(home_stats, "Fouls"),
            "fouls_away": get_stat(away_stats, "Fouls"),
        }
        return "imported_history"

    # Upcoming / scheduled → add to fixtures
    elif status in ("NS", "TBD", "SUSP", "PST", ""):
        if only_finished:
            return "skipped"
        # Only include future fixtures
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < (now_utc - timedelta(hours=2)):
                return "skipped"
            date_ymd = dt.strftime("%Y%m%d")
        except Exception:
            date_ymd = date.today().strftime("%Y%m%d")

        uid = key
        existing_ids = {f.get("api_fixture_id") for f in upcoming_data["fixtures"]}
        if uid in existing_ids:
            return "skipped"

        upcoming_data["fixtures"].append({
            "id": f"{league_id}_{home_id}_{away_id}_{date_ymd}",
            "api_fixture_id": uid,
            "fixture_date": date_str,
            "league_id": league_id, "league_name": league_name,
            "league_country": league_country, "league_logo": league_logo,
            "season": season,
            "round": fix.get("league", {}).get("round", ""),
            "venue": (fix.get("fixture", {}).get("venue") or {}).get("name") if isinstance(fix.get("fixture", {}).get("venue"), dict) else fix.get("fixture", {}).get("venue"),
            "home_team_id": f"ap_{home_id}", "home_team_name": home_name,
            "home_team_logo": home_logo,
            "away_team_id": f"ap_{away_id}", "away_team_name": away_name,
            "away_team_logo": away_logo,
            "referee_name": fix.get("fixture", {}).get("referee"),
            "status": status, "is_featured": False,
            "data_source": "apisports",
            "home_xg_adjustment": 1.0, "away_xg_adjustment": 1.0,
        })
        return "imported_upcoming"

    return "skipped"


# ─────────────────────────────────────────────────────────────────────────────
# DAILY FETCHES — the core of the new strategy
# ─────────────────────────────────────────────────────────────────────────────

def fetch_todays_fixtures(match_history, upcoming_data, now_utc):
    """
    1 API call → ALL fixtures scheduled today across ALL leagues.
    This is the key call that gets Venezuela, Morocco, Finland, etc.
    """
    today = date.today().isoformat()
    log.info(f"\n  Fetching ALL fixtures for {today} (1 API call)...")
    data = apisports_get("fixtures", {"date": today})
    if not data:
        return 0, 0

    fixtures = data.get("response", [])
    log.info(f"  API returned {len(fixtures)} fixtures today across all leagues")

    hist_count = 0
    upcoming_count = 0
    leagues_seen = set()

    for fix in fixtures:
        result = parse_apisports_fixture(fix, match_history, upcoming_data, now_utc)
        if result == "imported_history":   hist_count     += 1
        elif result == "imported_upcoming": upcoming_count += 1
        leagues_seen.add(fix.get("league", {}).get("name", "?"))

    log.info(f"  Today: {upcoming_count} upcoming fixtures, {hist_count} finished")
    log.info(f"  Leagues covered today: {len(leagues_seen)}")
    for ln in sorted(leagues_seen)[:20]:
        log.info(f"    · {ln}")

    return hist_count, upcoming_count


def fetch_recent_results(match_history, upcoming_data, now_utc, days_back=3):
    """
    Fetch finished matches from last N days — keeps history fresh.
    Uses 1 API call per day (so max 3 calls here).
    """
    total = 0
    for i in range(1, days_back + 1):
        d = (date.today() - timedelta(days=i)).isoformat()
        log.info(f"\n  Fetching finished results for {d}...")
        data = apisports_get("fixtures", {"date": d, "status": "FT-AET-PEN"})
        if not data:
            continue
        fixtures = data.get("response", [])
        count = 0
        for fix in fixtures:
            r = parse_apisports_fixture(fix, match_history, upcoming_data, now_utc,
                                        only_finished=True)
            if r == "imported_history":
                count += 1
        log.info(f"  {d}: {count} new finished results added")
        total += count
        time.sleep(0.5)
    return total


def fetch_upcoming_next_days(match_history, upcoming_data, now_utc, days_ahead=7):
    """
    Fetch upcoming fixtures for next N days — so we have a week's worth.
    Uses 1 API call per day.
    """
    total = 0
    for i in range(1, days_ahead + 1):
        d = (date.today() + timedelta(days=i)).isoformat()
        data = apisports_get("fixtures", {"date": d})
        if not data:
            continue
        fixtures = data.get("response", [])
        count = 0
        for fix in fixtures:
            r = parse_apisports_fixture(fix, match_history, upcoming_data, now_utc,
                                        only_upcoming=True)
            if r == "imported_upcoming":
                count += 1
        if count > 0:
            log.info(f"  {d}: {count} upcoming fixtures added")
        total += count
        time.sleep(0.3)
    return total


# ─────────────────────────────────────────────────────────────────────────────
# HISTORY BACKFILL
# ─────────────────────────────────────────────────────────────────────────────

def run_history_backfill(match_history, upcoming_data, now_utc):
    """
    For leagues with insufficient history, pull full season data.
    Spends up to MAX_BACKFILL_REQUESTS_PER_RUN API calls.
    Prioritises leagues with the least data first.
    """
    today_month = date.today().month
    requests_used = 0

    # Score leagues by how much they need backfilling
    league_scores = []
    for lg in HISTORY_LEAGUES:
        # Skip seasonal leagues that aren't active
        if "month_start" in lg and today_month < lg["month_start"]:
            continue
        league_id = lg["id"]
        matches_count = sum(
            1 for m in match_history.get("matches", {}).values()
            if m.get("league_id") == league_id
        )
        if matches_count < 50:  # Needs backfill
            league_scores.append((matches_count, lg))

    # Sort: least data first
    league_scores.sort(key=lambda x: x[0])
    log.info(f"\n  History backfill: {len(league_scores)} leagues need data")

    for matches_count, lg in league_scores:
        if requests_used >= MAX_BACKFILL_REQUESTS_PER_RUN:
            log.info(f"  Backfill quota reached ({MAX_BACKFILL_REQUESTS_PER_RUN} requests)")
            break

        league_id = lg["id"]
        season    = lg["season"]
        name      = lg["name"]

        log.info(f"\n  Backfilling {name} (currently {matches_count} matches)...")
        data = apisports_get("fixtures", {
            "league": league_id,
            "season": season,
            "status": "FT-AET-PEN"
        })
        requests_used += 1

        if not data:
            continue

        fixtures = data.get("response", [])
        count = 0
        for fix in fixtures:
            r = parse_apisports_fixture(fix, match_history, upcoming_data, now_utc,
                                        only_finished=True)
            if r == "imported_history":
                count += 1

        log.info(f"  {name}: {count} new historical matches added ({requests_used}/{MAX_BACKFILL_REQUESTS_PER_RUN} requests used)")
        time.sleep(1)

    return requests_used


# ─────────────────────────────────────────────────────────────────────────────
# FOOTBALL-DATA.ORG SUPPLEMENT (no quota cost)
# ─────────────────────────────────────────────────────────────────────────────

def run_football_data_supplement(match_history, upcoming_data, now_utc):
    """
    Supplements api-sports with deeper data from football-data.org.
    No daily cap so we can pull more here.
    """
    if not FOOTBALL_DATA_KEY:
        log.warning("FOOTBALL_DATA_API_KEY not set — skipping football-data.org")
        return

    today_month = date.today().month
    comps = [
        {"code": "BSA", "name": "Brasileirao Serie A", "league_id": 71},
        {"code": "CLI", "name": "Copa Libertadores",   "league_id": 13},
    ]
    if today_month >= 8:
        comps += [
            {"code": "PL",  "name": "Premier League",  "league_id": 39},
            {"code": "BL1", "name": "Bundesliga",      "league_id": 78},
            {"code": "SA",  "name": "Serie A",         "league_id": 135},
            {"code": "PD",  "name": "La Liga",         "league_id": 140},
            {"code": "FL1", "name": "Ligue 1",         "league_id": 61},
        ]

    for comp in comps:
        try:
            # Get upcoming
            data = football_data_get(
                f"competitions/{comp['code']}/matches",
                {"dateFrom": date.today().isoformat(),
                 "dateTo": (date.today() + timedelta(days=14)).isoformat(),
                 "status": "SCHEDULED,TIMED"}
            )
            count = 0
            if data and "matches" in data:
                for m in data["matches"]:
                    mid  = m.get("id")
                    if not mid: continue
                    uid  = f"fd_{mid}"
                    if uid in {f.get("api_fixture_id") for f in upcoming_data["fixtures"]}:
                        continue
                    ht = m.get("homeTeam", {})
                    at = m.get("awayTeam", {})
                    utc_date = m.get("utcDate", "")
                    try:
                        dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
                        date_ymd = dt.strftime("%Y%m%d")
                    except Exception:
                        date_ymd = date.today().strftime("%Y%m%d")
                    upcoming_data["fixtures"].append({
                        "id": f"{comp['league_id']}_{ht.get('id')}_{at.get('id')}_{date_ymd}",
                        "api_fixture_id": uid, "fixture_date": utc_date,
                        "league_id": comp["league_id"], "league_name": comp["name"],
                        "league_country": "", "league_logo": None,
                        "season": CURRENT_SEASON, "round": str(m.get("matchday", "")),
                        "venue": None,
                        "home_team_id": f"fd_{ht.get('id')}", "home_team_name": ht.get("name", "?"),
                        "home_team_logo": ht.get("crest"),
                        "away_team_id": f"fd_{at.get('id')}", "away_team_name": at.get("name", "?"),
                        "away_team_logo": at.get("crest"),
                        "referee_name": None, "status": "SCHEDULED", "is_featured": False,
                        "data_source": "football_data",
                        "home_xg_adjustment": 1.0, "away_xg_adjustment": 1.0,
                    })
                    count += 1
            if count:
                log.info(f"  [FD] {comp['name']}: {count} upcoming fixtures")
            time.sleep(7)
        except Exception as e:
            log.error(f"  [FD] {comp['name']} failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run():
    log.info("=" * 60)
    log.info("Step 1: Import data — api-sports.io (all leagues) + football-data.org")
    log.info("=" * 60)

    match_history = get_match_history()
    if "matches" not in match_history:
        match_history["matches"] = {}
    existing_count = len(match_history["matches"])
    log.info(f"Existing match history: {existing_count} matches")

    existing_upcoming = get_upcoming_fixtures()
    now_utc = datetime.now(timezone.utc)
    upcoming_data = {
        "fixtures": [
            f for f in existing_upcoming.get("fixtures", [])
            if _is_future_fixture(f, now_utc)
        ]
    }
    log.info(f"Existing upcoming fixtures: {len(upcoming_data['fixtures'])} (past removed)")

    referee_data = get_referee_data()
    if "referees" not in referee_data:
        referee_data["referees"] = {}

    if not APISPORTS_KEY:
        log.error("FOOTBALL_DATA_API_KEY (api-sports key) not set — cannot fetch fixtures")
        return {}

    # Check API quota before starting
    status_data = apisports_get("status")
    remaining = 100
    if status_data:
        try:
            resp = status_data.get("response", {})
            # response can be a list or dict depending on API version
            if isinstance(resp, list):
                resp = resp[0] if resp else {}
            acct      = resp.get("requests", {})
            used      = acct.get("current", "?")
            limit     = acct.get("limit_day", "?")
            remaining = int(acct.get("remaining", 100))
            log.info(f"API-Sports quota: {used}/{limit} used today, {remaining} remaining")
        except Exception as e:
            log.warning(f"Could not parse quota status: {e}")
            remaining = 100

    # ── STEP A: Today's fixtures (1 request) ─────────────────────────────────
    log.info("\n--- STEP A: Today's fixtures (all leagues, 1 API call) ---")
    h1, u1 = fetch_todays_fixtures(match_history, upcoming_data, now_utc)

    # ── STEP B: Recent results for scoring (up to 3 requests) ────────────────
    log.info("\n--- STEP B: Recent results (last 3 days) ---")
    h2 = fetch_recent_results(match_history, upcoming_data, now_utc, days_back=2)

    # ── STEP C: Upcoming fixtures next 7 days (7 requests) ───────────────────
    log.info("\n--- STEP C: Upcoming fixtures next 7 days ---")
    u2 = fetch_upcoming_next_days(match_history, upcoming_data, now_utc, days_ahead=7)

    # ── STEP D: History backfill for new leagues (up to 15 requests) ─────────
    log.info("\n--- STEP D: History backfill for leagues with insufficient data ---")
    backfill_reqs = run_history_backfill(match_history, upcoming_data, now_utc)

    # ── STEP E: football-data.org supplement (no quota cost) ─────────────────
    log.info("\n--- STEP E: football-data.org supplement ---")
    run_football_data_supplement(match_history, upcoming_data, now_utc)

    # Save
    save_match_history(match_history)
    save_upcoming_fixtures(upcoming_data)
    save_referee_data(referee_data)

    final_count = len(match_history["matches"])
    log.info("\n" + "=" * 60)
    log.info("Step 1 Complete")
    log.info(f"  Match history before:  {existing_count}")
    log.info(f"  New matches added:     {final_count - existing_count}")
    log.info(f"  Match history after:   {final_count}")
    log.info(f"  Upcoming fixtures:     {len(upcoming_data['fixtures'])}")
    log.info(f"  API requests used:     ~{4 + backfill_reqs} (daily + backfill)")
    log.info("=" * 60)

    return {
        "existing_matches": existing_count,
        "new_matches":      final_count - existing_count,
        "total_matches":    final_count,
        "upcoming_fixtures": len(upcoming_data["fixtures"]),
    }


def _is_future_fixture(fixture, now_utc):
    try:
        ds = fixture.get("fixture_date", "")
        if not ds: return True
        dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt > (now_utc - timedelta(hours=2))
    except Exception:
        return True


if __name__ == "__main__":
    run()
