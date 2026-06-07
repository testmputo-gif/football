"""
pipeline/step1_import_data.py

Imports match data from multiple free sources:

SOURCE 1: football-data.org (free tier, no daily cap)
  - Brasileirao Serie A, Copa Libertadores (always active)
  - All European leagues auto-enable 1 August
  - Champions League auto-enables 1 September

SOURCE 2: BSD API — sports.bzzoiro.com (free, no rate limits)
  - Norway, Sweden, Japan, South Korea (active now)

SOURCE 3: TheSportsDB — thesportsdb.com (completely free, no key needed)
  - Finland Veikkausliiga, Denmark Superliga, Turkey Super Lig,
    Austria Bundesliga, Iceland Urvalsdeild, MLS, Argentina Primera,
    Greek Super League, Scottish Premiership, Swiss Super League
  - Covers leagues BSD and football-data.org don't have
  - No API key required

HISTORICAL BACKFILL:
  On first run (or when a team has < 8 matches), the pipeline automatically
  pulls up to 12 months of historical data instead of just 60 days.
  This gives new leagues enough history to start predicting immediately.
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

FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
BSD_KEY           = os.environ.get("BSD_API_KEY", "")

FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
BSD_BASE           = "https://sports.bzzoiro.com/api"
TSDB_BASE          = "https://www.thesportsdb.com/api/v1/json/3"  # free public key = 3


# ─────────────────────────────────────────────────────────────────────────────
# COMPETITION LISTS
# ─────────────────────────────────────────────────────────────────────────────

def get_football_data_competitions() -> list:
    today = date.today()
    month = today.month

    always = [
        {"code": "BSA", "name": "Brasileirao Serie A", "country": "Brazil",        "league_id": 71,  "season": 2025, "source": "football_data"},
        {"code": "CLI", "name": "Copa Libertadores",   "country": "South America", "league_id": 13,  "season": 2025, "source": "football_data"},
    ]
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
    ucl = [
        {"code": "CL", "name": "Champions League", "country": "Europe", "league_id": 2, "season": 2025, "source": "football_data"},
    ]

    active = list(always)
    if month >= 8:
        active.extend(european)
        log.info("August+: European leagues ACTIVE on football-data.org")
    else:
        days_left = (date(today.year, 8, 1) - today).days
        log.info(f"Summer break: European leagues auto-enable in {days_left} days (1 August {today.year})")
    if month >= 9:
        active.extend(ucl)
    return active


def get_bsd_competitions() -> list:
    return [
        {"bsd_league_id": 8,  "name": "Eliteserien",  "country": "Norway",       "league_id": 103, "season": 2026, "source": "bsd"},
        {"bsd_league_id": 9,  "name": "Allsvenskan",  "country": "Sweden",       "league_id": 113, "season": 2026, "source": "bsd"},
        {"bsd_league_id": 49, "name": "J1 League",    "country": "Japan",        "league_id": 98,  "season": 2026, "source": "bsd"},
        {"bsd_league_id": 55, "name": "K League 1",   "country": "South Korea",  "league_id": 292, "season": 2026, "source": "bsd"},
    ]


def get_thesportsdb_competitions() -> list:
    """
    TheSportsDB leagues — completely free, no API key needed.
    league_id = their internal ID for fetching fixtures.
    internal_id = our stats engine ID for this league.
    """
    return [
        # ── Active right now (summer / year-round) ─────────────────────────
        {"tsdb_league_id": "4764", "name": "Veikkausliiga",        "country": "Finland",    "league_id": 244, "season": "2026", "source": "thesportsdb"},
        {"tsdb_league_id": "4350", "name": "Denmark Superliga",    "country": "Denmark",    "league_id": 119, "season": "2025-2026", "source": "thesportsdb"},
        {"tsdb_league_id": "4391", "name": "Turkey Super Lig",     "country": "Turkey",     "league_id": 203, "season": "2024-2025", "source": "thesportsdb"},
        {"tsdb_league_id": "4332", "name": "Austrian Bundesliga",  "country": "Austria",    "league_id": 218, "season": "2024-2025", "source": "thesportsdb"},
        {"tsdb_league_id": "4887", "name": "Urvalsdeild",          "country": "Iceland",    "league_id": 164, "season": "2026", "source": "thesportsdb"},
        {"tsdb_league_id": "4346", "name": "Greek Super League",   "country": "Greece",     "league_id": 197, "season": "2024-2025", "source": "thesportsdb"},
        {"tsdb_league_id": "4480", "name": "Scottish Premiership", "country": "Scotland",   "league_id": 179, "season": "2024-2025", "source": "thesportsdb"},
        {"tsdb_league_id": "4335", "name": "MLS",                  "country": "USA",        "league_id": 253, "season": "2026", "source": "thesportsdb"},
        {"tsdb_league_id": "4406", "name": "Argentine Primera",    "country": "Argentina",  "league_id": 128, "season": "2026", "source": "thesportsdb"},
        {"tsdb_league_id": "4368", "name": "Swiss Super League",   "country": "Switzerland","league_id": 207, "season": "2024-2025", "source": "thesportsdb"},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# BACKFILL DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def needs_backfill(match_history: dict, league_id: int, min_matches: int = 8) -> bool:
    """
    Returns True if any team in this league has fewer than min_matches.
    Triggers a 12-month lookback instead of 60 days when True.
    """
    league_matches = [
        m for m in match_history.get("matches", {}).values()
        if m.get("league_id") == league_id
    ]
    if len(league_matches) < min_matches * 2:
        return True  # Whole league is new

    # Count per team
    team_counts = {}
    for m in league_matches:
        for tid in [m.get("home_team_id"), m.get("away_team_id")]:
            if tid:
                team_counts[tid] = team_counts.get(tid, 0) + 1

    low = sum(1 for c in team_counts.values() if c < min_matches)
    return low > len(team_counts) * 0.3  # >30% of teams need more data


def get_lookback_days(match_history: dict, league_id: int) -> int:
    """Returns 365 for new leagues, 60 for established ones."""
    if needs_backfill(match_history, league_id):
        log.info(f"  ↩ League {league_id} needs backfill — pulling 12 months of history")
        return 365
    return 60


# ─────────────────────────────────────────────────────────────────────────────
# HTTP HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def football_data_get(endpoint, params=None):
    url = f"{FOOTBALL_DATA_BASE}/{endpoint}"
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    try:
        r = httpx.get(url, headers=headers, params=params or {}, timeout=30.0)
        if r.status_code == 429:
            log.warning("football-data.org rate limited — waiting 65s")
            time.sleep(65)
            r = httpx.get(url, headers=headers, params=params or {}, timeout=30.0)
        if r.status_code == 200:
            return r.json()
        log.error(f"football-data HTTP {r.status_code} on {endpoint}: {r.text[:120]}")
        return None
    except Exception as e:
        log.error(f"football-data request failed: {e}")
        return None


def bsd_get(endpoint, params=None):
    url = f"{BSD_BASE}/{endpoint}"
    headers = {"Authorization": f"Token {BSD_KEY}"}
    try:
        r = httpx.get(url, headers=headers, params=params or {}, timeout=30.0)
        if r.status_code == 200:
            return r.json()
        log.error(f"BSD HTTP {r.status_code} on {endpoint}: {r.text[:120]}")
        return None
    except Exception as e:
        log.error(f"BSD request failed: {e}")
        return None


def tsdb_get(endpoint, params=None):
    """TheSportsDB — no auth needed, free public API."""
    url = f"{TSDB_BASE}/{endpoint}"
    try:
        r = httpx.get(url, params=params or {}, timeout=30.0)
        if r.status_code == 200:
            return r.json()
        log.error(f"TheSportsDB HTTP {r.status_code} on {endpoint}")
        return None
    except Exception as e:
        log.error(f"TheSportsDB request failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# FOOTBALL-DATA.ORG IMPORTERS
# ─────────────────────────────────────────────────────────────────────────────

def import_from_football_data(comp, match_history, upcoming_data):
    code    = comp["code"]
    results = {"completed": 0, "upcoming": 0, "skipped": 0}
    lookback = get_lookback_days(match_history, comp["league_id"])

    # Completed matches
    try:
        date_from = (date.today() - timedelta(days=lookback)).isoformat()
        date_to   = date.today().isoformat()
        data = football_data_get(f"competitions/{code}/matches",
            {"dateFrom": date_from, "dateTo": date_to, "status": "FINISHED"})
        if data and "matches" in data:
            for m in data["matches"]:
                r = _parse_fd_match(m, comp, match_history)
                if r == "imported": results["completed"] += 1
                else:               results["skipped"]   += 1
            log.info(f"  [FD] {comp['name']}: {results['completed']} new matches ({lookback}d lookback)")
        time.sleep(7)
    except Exception as e:
        log.error(f"  [FD] completed failed for {comp['name']}: {e}")

    # Upcoming
    try:
        date_from = date.today().isoformat()
        date_to   = (date.today() + timedelta(days=14)).isoformat()
        data = football_data_get(f"competitions/{code}/matches",
            {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED,TIMED"})
        if data and "matches" in data:
            for m in data["matches"]:
                r = _parse_fd_fixture(m, comp, upcoming_data)
                if r == "imported": results["upcoming"] += 1
            log.info(f"  [FD] {comp['name']}: {results['upcoming']} upcoming fixtures")
        time.sleep(7)
    except Exception as e:
        log.error(f"  [FD] upcoming failed for {comp['name']}: {e}")

    return results


def _parse_fd_match(match, comp, match_history):
    mid = match.get("id")
    if not mid: return "skipped"
    key = f"fd_{mid}"
    if key in match_history["matches"]: return "skipped"
    ft     = match.get("score", {}).get("fullTime", {})
    home_g = ft.get("home")
    away_g = ft.get("away")
    if home_g is None or away_g is None: return "skipped"
    ht  = match.get("homeTeam", {})
    at  = match.get("awayTeam", {})
    ref = (match.get("referees") or [{}])[0].get("name")
    match_history["matches"][key] = {
        "api_fixture_id": key, "league_id": comp["league_id"],
        "league_name": comp["name"],
        "home_team_id": f"fd_{ht.get('id')}", "home_team_name": ht.get("name") or ht.get("shortName"),
        "away_team_id": f"fd_{at.get('id')}", "away_team_name": at.get("name") or at.get("shortName"),
        "match_date": match.get("utcDate", ""), "season": comp.get("season", CURRENT_SEASON),
        "home_goals": int(home_g), "away_goals": int(away_g), "referee_name": ref,
        "data_source": "football_data",
        "home_corners": None, "away_corners": None,
        "home_yellow_cards": None, "away_yellow_cards": None,
        "home_red_cards": None, "away_red_cards": None,
        "possession_home": None, "possession_away": None,
        "shots_home": None, "shots_away": None,
        "shots_on_target_home": None, "shots_on_target_away": None,
        "fouls_home": None, "fouls_away": None,
    }
    return "imported"


def _parse_fd_fixture(match, comp, upcoming_data):
    mid = match.get("id")
    if not mid: return "skipped"
    ht = match.get("homeTeam", {})
    at = match.get("awayTeam", {})
    if not ht.get("id") or not at.get("id"): return "skipped"
    utc_date = match.get("utcDate", "")
    try:
        fixture_dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
    except Exception:
        return "skipped"
    uid = f"fd_{mid}"
    if uid in {f["api_fixture_id"] for f in upcoming_data["fixtures"]}: return "skipped"
    upcoming_data["fixtures"].append({
        "id": f"{comp['league_id']}_{ht.get('id')}_{at.get('id')}_{fixture_dt.strftime('%Y%m%d')}",
        "api_fixture_id": uid, "fixture_date": utc_date,
        "league_id": comp["league_id"], "league_name": comp["name"],
        "league_country": comp["country"], "league_logo": None,
        "season": comp.get("season", CURRENT_SEASON),
        "round": str(match.get("matchday", "")), "venue": None,
        "home_team_id": f"fd_{ht.get('id')}", "home_team_name": ht.get("name") or ht.get("shortName"),
        "home_team_logo": ht.get("crest"),
        "away_team_id": f"fd_{at.get('id')}", "away_team_name": at.get("name") or at.get("shortName"),
        "away_team_logo": at.get("crest"), "referee_name": None,
        "status": match.get("status", "SCHEDULED"), "is_featured": False,
        "data_source": "football_data", "home_xg_adjustment": 1.0, "away_xg_adjustment": 1.0,
    })
    return "imported"


# ─────────────────────────────────────────────────────────────────────────────
# BSD API IMPORTERS
# ─────────────────────────────────────────────────────────────────────────────

def import_from_bsd(comp, match_history, upcoming_data):
    lid     = comp["bsd_league_id"]
    results = {"completed": 0, "upcoming": 0, "skipped": 0}
    lookback = get_lookback_days(match_history, comp["league_id"])

    try:
        date_from = (date.today() - timedelta(days=lookback)).isoformat()
        data = bsd_get("events/", {"league": lid, "date_from": date_from,
                                    "date_to": date.today().isoformat(), "status": "finished"})
        if data:
            matches = data if isinstance(data, list) else data.get("events", data.get("results", []))
            if isinstance(matches, list):
                for m in matches:
                    r = _parse_bsd_match(m, comp, match_history)
                    if r == "imported": results["completed"] += 1
                    else:               results["skipped"]   += 1
                log.info(f"  [BSD] {comp['name']}: {results['completed']} new matches ({lookback}d lookback)")
        time.sleep(1)
    except Exception as e:
        log.error(f"  [BSD] completed failed {comp['name']}: {e}")

    try:
        date_from = date.today().isoformat()
        date_to   = (date.today() + timedelta(days=14)).isoformat()
        data = bsd_get("events/", {"league": lid, "date_from": date_from,
                                    "date_to": date_to, "status": "notstarted"})
        if data:
            fixtures = data if isinstance(data, list) else data.get("events", data.get("results", []))
            if isinstance(fixtures, list):
                for m in fixtures:
                    r = _parse_bsd_fixture(m, comp, upcoming_data)
                    if r == "imported": results["upcoming"] += 1
                log.info(f"  [BSD] {comp['name']}: {results['upcoming']} upcoming fixtures")
        time.sleep(1)
    except Exception as e:
        log.error(f"  [BSD] upcoming failed {comp['name']}: {e}")

    return results


def _parse_bsd_match(match, comp, match_history):
    mid = match.get("id")
    if not mid: return "skipped"
    key = f"bsd_{mid}"
    if key in match_history["matches"]: return "skipped"
    home_score = match.get("home_score")
    away_score = match.get("away_score")
    if home_score is None or away_score is None: return "skipped"
    hname = match.get("home_team") or match.get("home_team_name") or match.get("homeTeam", {}).get("name", "Unknown")
    aname = match.get("away_team") or match.get("away_team_name") or match.get("awayTeam", {}).get("name", "Unknown")
    hid   = match.get("home_team_id") or match.get("homeTeam", {}).get("id", 0)
    aid   = match.get("away_team_id") or match.get("awayTeam", {}).get("id", 0)
    match_history["matches"][key] = {
        "api_fixture_id": key, "league_id": comp["league_id"], "league_name": comp["name"],
        "home_team_id": f"bsd_{hid}", "home_team_name": hname,
        "away_team_id": f"bsd_{aid}", "away_team_name": aname,
        "match_date": match.get("event_date") or match.get("date") or "",
        "season": comp.get("season", CURRENT_SEASON),
        "home_goals": int(home_score), "away_goals": int(away_score),
        "referee_name": None, "data_source": "bsd",
        "home_corners": None, "away_corners": None,
        "home_yellow_cards": None, "away_yellow_cards": None,
        "home_red_cards": None, "away_red_cards": None,
        "possession_home": None, "possession_away": None,
        "shots_home": None, "shots_away": None,
        "shots_on_target_home": None, "shots_on_target_away": None,
        "fouls_home": None, "fouls_away": None,
    }
    return "imported"


def _parse_bsd_fixture(match, comp, upcoming_data):
    mid = match.get("id")
    if not mid: return "skipped"
    uid = f"bsd_{mid}"
    if uid in {f["api_fixture_id"] for f in upcoming_data["fixtures"]}: return "skipped"
    hname = match.get("home_team") or match.get("home_team_name") or match.get("homeTeam", {}).get("name", "Unknown")
    aname = match.get("away_team") or match.get("away_team_name") or match.get("awayTeam", {}).get("name", "Unknown")
    hid   = match.get("home_team_id") or match.get("homeTeam", {}).get("id") or mid
    aid   = match.get("away_team_id") or match.get("awayTeam", {}).get("id") or f"a{mid}"
    edate = match.get("event_date") or match.get("date") or ""
    try:
        dt = datetime.fromisoformat(edate.replace("Z", "+00:00")) if edate else datetime.utcnow()
        date_str = dt.strftime("%Y%m%d")
    except Exception:
        date_str = date.today().strftime("%Y%m%d")
    upcoming_data["fixtures"].append({
        "id": f"{comp['league_id']}_{hid}_{aid}_{date_str}",
        "api_fixture_id": uid, "fixture_date": edate,
        "league_id": comp["league_id"], "league_name": comp["name"],
        "league_country": comp["country"], "league_logo": None,
        "season": comp.get("season", CURRENT_SEASON),
        "round": str(match.get("round") or match.get("matchday") or ""),
        "venue": match.get("venue") or match.get("stadium"),
        "home_team_id": f"bsd_{hid}", "home_team_name": hname,
        "home_team_logo": match.get("home_team_logo") or match.get("home_badge"),
        "away_team_id": f"bsd_{aid}", "away_team_name": aname,
        "away_team_logo": match.get("away_team_logo") or match.get("away_badge"),
        "referee_name": None, "status": match.get("status", "notstarted"),
        "is_featured": False, "data_source": "bsd",
        "home_xg_adjustment": 1.0, "away_xg_adjustment": 1.0,
    })
    return "imported"


# ─────────────────────────────────────────────────────────────────────────────
# THESPORTSDB IMPORTERS — no key needed
# ─────────────────────────────────────────────────────────────────────────────

def import_from_thesportsdb(comp, match_history, upcoming_data):
    """
    TheSportsDB free API. Endpoints:
    - Past results: /eventsseason.php?id=LEAGUE_ID&s=SEASON
    - Upcoming:     /eventsnextleague.php?id=LEAGUE_ID
    No rate limit on the public free key (key=3).
    """
    lid     = comp["tsdb_league_id"]
    season  = comp["season"]
    results = {"completed": 0, "upcoming": 0, "skipped": 0}
    lookback = get_lookback_days(match_history, comp["league_id"])

    # Past results for current season
    try:
        data = tsdb_get("eventsseason.php", {"id": lid, "s": season})
        events = (data or {}).get("events") or []
        cutoff = (date.today() - timedelta(days=lookback)).isoformat()

        for ev in events:
            # Only import finished matches within lookback window
            status = (ev.get("strStatus") or "").lower()
            if status not in ("match finished", "ft", "aet", "pen", "finished"):
                continue
            ev_date = ev.get("dateEvent", "")
            if ev_date < cutoff[:10]:
                continue
            r = _parse_tsdb_match(ev, comp, match_history)
            if r == "imported": results["completed"] += 1
            else:               results["skipped"]   += 1

        log.info(f"  [TSDB] {comp['name']}: {results['completed']} new matches ({lookback}d lookback)")
        time.sleep(0.5)
    except Exception as e:
        log.error(f"  [TSDB] completed failed {comp['name']}: {e}")

    # Upcoming fixtures
    try:
        data = tsdb_get("eventsnextleague.php", {"id": lid})
        events = (data or {}).get("events") or []
        for ev in events:
            r = _parse_tsdb_fixture(ev, comp, upcoming_data)
            if r == "imported": results["upcoming"] += 1
        log.info(f"  [TSDB] {comp['name']}: {results['upcoming']} upcoming fixtures")
        time.sleep(0.5)
    except Exception as e:
        log.error(f"  [TSDB] upcoming failed {comp['name']}: {e}")

    return results


def _parse_tsdb_match(ev, comp, match_history):
    eid = ev.get("idEvent")
    if not eid: return "skipped"
    key = f"tsdb_{eid}"
    if key in match_history["matches"]: return "skipped"

    home_g = ev.get("intHomeScore")
    away_g = ev.get("intAwayScore")
    if home_g is None or away_g is None: return "skipped"
    try:
        home_g = int(home_g)
        away_g = int(away_g)
    except (ValueError, TypeError):
        return "skipped"

    hname  = ev.get("strHomeTeam", "Unknown")
    aname  = ev.get("strAwayTeam", "Unknown")
    hid    = ev.get("idHomeTeam", eid)
    aid    = ev.get("idAwayTeam", eid)
    ev_date = ev.get("dateEvent", "")
    ev_time = ev.get("strTime", "00:00:00")
    match_dt = f"{ev_date}T{ev_time}Z" if ev_date else ""

    match_history["matches"][key] = {
        "api_fixture_id": key, "league_id": comp["league_id"], "league_name": comp["name"],
        "home_team_id": f"tsdb_{hid}", "home_team_name": hname,
        "away_team_id": f"tsdb_{aid}", "away_team_name": aname,
        "match_date": match_dt, "season": comp.get("season", CURRENT_SEASON),
        "home_goals": home_g, "away_goals": away_g,
        "referee_name": None, "data_source": "thesportsdb",
        "home_corners": None, "away_corners": None,
        "home_yellow_cards": None, "away_yellow_cards": None,
        "home_red_cards": None, "away_red_cards": None,
        "possession_home": None, "possession_away": None,
        "shots_home": None, "shots_away": None,
        "shots_on_target_home": None, "shots_on_target_away": None,
        "fouls_home": None, "fouls_away": None,
    }
    return "imported"


def _parse_tsdb_fixture(ev, comp, upcoming_data):
    eid = ev.get("idEvent")
    if not eid: return "skipped"
    uid = f"tsdb_{eid}"
    if uid in {f["api_fixture_id"] for f in upcoming_data["fixtures"]}: return "skipped"

    hname  = ev.get("strHomeTeam", "Unknown")
    aname  = ev.get("strAwayTeam", "Unknown")
    hid    = ev.get("idHomeTeam", eid)
    aid    = ev.get("idAwayTeam", eid)
    ev_date = ev.get("dateEvent", "")
    ev_time = ev.get("strTime", "00:00:00") or "00:00:00"
    fixture_dt_str = f"{ev_date}T{ev_time}Z" if ev_date else ""

    try:
        dt = datetime.fromisoformat(fixture_dt_str.replace("Z", "+00:00")) if fixture_dt_str else datetime.utcnow().replace(tzinfo=timezone.utc)
        date_str = dt.strftime("%Y%m%d")
    except Exception:
        date_str = date.today().strftime("%Y%m%d")

    upcoming_data["fixtures"].append({
        "id": f"{comp['league_id']}_{hid}_{aid}_{date_str}",
        "api_fixture_id": uid, "fixture_date": fixture_dt_str,
        "league_id": comp["league_id"], "league_name": comp["name"],
        "league_country": comp["country"], "league_logo": None,
        "season": comp.get("season", CURRENT_SEASON),
        "round": str(ev.get("intRound") or ""),
        "venue": ev.get("strVenue"),
        "home_team_id": f"tsdb_{hid}", "home_team_name": hname,
        "home_team_logo": ev.get("strHomeTeamBadge"),
        "away_team_id": f"tsdb_{aid}", "away_team_name": aname,
        "away_team_logo": ev.get("strAwayTeamBadge"),
        "referee_name": None, "status": "scheduled",
        "is_featured": False, "data_source": "thesportsdb",
        "home_xg_adjustment": 1.0, "away_xg_adjustment": 1.0,
    })
    return "imported"


# ─────────────────────────────────────────────────────────────────────────────
# FUTURE FIXTURE FILTER
# ─────────────────────────────────────────────────────────────────────────────

def _is_future_fixture(fixture, now_utc):
    date_str = fixture.get("fixture_date", "")
    if not date_str: return True
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt > (now_utc - timedelta(hours=2))
    except Exception:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run():
    log.info("=" * 60)
    log.info("Step 1: Importing data — football-data.org + BSD + TheSportsDB")
    log.info("=" * 60)

    match_history    = get_match_history()
    if "matches" not in match_history:
        match_history["matches"] = {}

    existing_count   = len(match_history["matches"])
    log.info(f"Existing match history: {existing_count} matches (preserved)")

    existing_upcoming = get_upcoming_fixtures()
    upcoming_data = {"fixtures": list(existing_upcoming.get("fixtures", []))}

    now_utc = datetime.now(timezone.utc)
    upcoming_data["fixtures"] = [
        f for f in upcoming_data["fixtures"] if _is_future_fixture(f, now_utc)
    ]
    log.info(f"Existing upcoming fixtures kept: {len(upcoming_data['fixtures'])} (past removed)")

    referee_data = get_referee_data()
    if "referees" not in referee_data:
        referee_data["referees"] = {}

    total_new = 0
    total_upcoming = 0
    total_skipped  = 0
    sources_used   = []

    # ── SOURCE 1: football-data.org ───────────────────────────────────────────
    if FOOTBALL_DATA_KEY:
        log.info("\n--- SOURCE 1: football-data.org ---")
        for comp in get_football_data_competitions():
            log.info(f"\nProcessing: {comp['name']}")
            r = import_from_football_data(comp, match_history, upcoming_data)
            total_new      += r["completed"]
            total_upcoming += r["upcoming"]
            total_skipped  += r["skipped"]
        sources_used.append("football-data.org")
    else:
        log.error("FOOTBALL_DATA_API_KEY not set — skipping football-data.org")

    # ── SOURCE 2: BSD API ─────────────────────────────────────────────────────
    if BSD_KEY:
        log.info("\n--- SOURCE 2: BSD API ---")
        for comp in get_bsd_competitions():
            log.info(f"\nProcessing: {comp['name']}")
            r = import_from_bsd(comp, match_history, upcoming_data)
            total_new      += r["completed"]
            total_upcoming += r["upcoming"]
            total_skipped  += r["skipped"]
        sources_used.append("BSD API")
    else:
        log.warning("BSD_API_KEY not set — skipping Norway/Sweden/Japan/Korea")

    # ── SOURCE 3: TheSportsDB (NO KEY NEEDED) ─────────────────────────────────
    log.info("\n--- SOURCE 3: TheSportsDB (free, no key) ---")
    for comp in get_thesportsdb_competitions():
        log.info(f"\nProcessing: {comp['name']}")
        r = import_from_thesportsdb(comp, match_history, upcoming_data)
        total_new      += r["completed"]
        total_upcoming += r["upcoming"]
        total_skipped  += r["skipped"]
    sources_used.append("TheSportsDB")

    # Save
    save_match_history(match_history)
    save_upcoming_fixtures(upcoming_data)
    save_referee_data(referee_data)

    final_count = len(match_history["matches"])

    log.info("\n" + "=" * 60)
    log.info("Step 1 Complete")
    log.info(f"  Sources:               {', '.join(sources_used)}")
    log.info(f"  Match history before:  {existing_count}")
    log.info(f"  New matches added:     {total_new}")
    log.info(f"  Match history after:   {final_count}")
    log.info(f"  Already known skipped: {total_skipped}")
    log.info(f"  Upcoming fixtures:     {total_upcoming}")
    log.info("=" * 60)

    return {
        "sources_used": sources_used,
        "existing_matches": existing_count,
        "new_matches": total_new,
        "total_matches": final_count,
        "upcoming_fixtures": total_upcoming,
        "skipped": total_skipped,
    }


if __name__ == "__main__":
    run()
