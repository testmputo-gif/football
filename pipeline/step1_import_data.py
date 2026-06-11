"""
pipeline/step1_import_data.py

DATA SOURCES (in order of priority):
======================================
1. API-Football / api-sports.io (FOOTBALL_API_KEY)
   - GET /fixtures?date=TODAY  → ALL leagues, ALL fixtures, 1 request
   - GET /fixtures?date=D  for next 7 days → full week ahead
   - GET /fixtures?league=X&season=Y&status=FT → history backfill
   - 100 requests/day free

2. football-data.org (FOOTBALL_DATA_API_KEY)  
   - No daily cap, 10 req/min
   - Brasileirao, Copa Lib, + European leagues when in season

3. OpenLigaDB (NO KEY NEEDED)
   - German Bundesliga history + upcoming — completely free

CANONICAL TEAM IDs:
===================
All team IDs use format: team_{league_id}_{normalized_name}
e.g. "team_244_hjk", "team_71_flamengo"
This ensures history and fixtures always use the same key,
regardless of which API provided the data.

BACKFILL LOGIC:
===============
Any league with < 10 matches in history triggers a 12-month backfill.
This runs automatically until teams have enough data for predictions.
Budget: up to 20 API calls per run for backfill.
"""

import httpx, json, logging, os, re, time
from datetime import datetime, timedelta, date, timezone
from pipeline.config import PATHS, CURRENT_SEASON
from pipeline.data_store import (
    get_match_history, save_match_history,
    get_upcoming_fixtures, save_upcoming_fixtures,
    get_referee_data, save_referee_data,
)

log = logging.getLogger(__name__)

# ── API Keys ──────────────────────────────────────────────────────────────────
APISPORTS_KEY     = os.environ.get("FOOTBALL_API_KEY", "") or os.environ.get("FOOTBALL_DATA_API_KEY", "")
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")

APISPORTS_BASE     = "https://v3.football.api-sports.io"
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
OPENLIGADB_BASE    = "https://api.openligadb.de"

# ── Canonical team ID ─────────────────────────────────────────────────────────
def canonical_team_id(league_id, team_name):
    norm = re.sub(r'[^a-z0-9]+', '_', (team_name or '').lower().strip()).strip('_')
    return f"team_{league_id}_{norm}"

# ── Leagues for history backfill ──────────────────────────────────────────────
BACKFILL_LEAGUES = [
    # Year-round — highest priority
    {"id": 71,  "name": "Brasileirao Serie A",     "season": 2025},
    {"id": 72,  "name": "Brasileirao Serie B",     "season": 2025},
    {"id": 13,  "name": "Copa Libertadores",       "season": 2025},
    {"id": 11,  "name": "Copa Sudamericana",       "season": 2025},
    {"id": 128, "name": "Argentine Liga Prof",     "season": 2025},
    {"id": 131, "name": "Venezuela Primera",       "season": 2025},
    {"id": 253, "name": "MLS",                     "season": 2025},
    {"id": 98,  "name": "J1 League",               "season": 2026},
    {"id": 292, "name": "K League 1",              "season": 2026},
    {"id": 103, "name": "Eliteserien Norway",      "season": 2026},
    {"id": 113, "name": "Allsvenskan Sweden",      "season": 2026},
    {"id": 244, "name": "Veikkausliiga Finland",   "season": 2026},
    {"id": 164, "name": "Urvalsdeild Iceland",     "season": 2026},
    {"id": 119, "name": "Denmark Superliga",       "season": "2025-2026"},
    {"id": 203, "name": "Turkey Super Lig",        "season": "2024-2025"},
    {"id": 218, "name": "Austrian Bundesliga",     "season": "2024-2025"},
    {"id": 197, "name": "Greek Super League",      "season": "2024-2025"},
    {"id": 179, "name": "Scottish Premiership",    "season": "2024-2025"},
    {"id": 207, "name": "Swiss Super League",      "season": "2024-2025"},
    {"id": 301, "name": "Morocco Botola",          "season": 2025},
    {"id": 383, "name": "Saudi Pro League",        "season": 2025},
    {"id": 169, "name": "South Africa PSL",        "season": 2025},
    {"id": 188, "name": "Nigeria NPFL",            "season": 2025},
    # European top (active Aug+)
    {"id": 39,  "name": "Premier League",          "season": 2025, "month_start": 8},
    {"id": 78,  "name": "Bundesliga",              "season": 2025, "month_start": 8},
    {"id": 135, "name": "Serie A",                 "season": 2025, "month_start": 8},
    {"id": 140, "name": "La Liga",                 "season": 2025, "month_start": 8},
    {"id": 61,  "name": "Ligue 1",                 "season": 2025, "month_start": 8},
    {"id": 88,  "name": "Eredivisie",              "season": 2025, "month_start": 8},
    {"id": 2,   "name": "Champions League",        "season": 2025, "month_start": 9},
    {"id": 3,   "name": "Europa League",           "season": 2025, "month_start": 9},
]

MAX_BACKFILL_PER_RUN = 20

# ── Leagues that are NOT football (filter these out) ─────────────────────────
NON_FOOTBALL_KEYWORDS = [
    'nfl', 'nba', 'nhl', 'mlb', 'rugby', 'american football',
    'basketball', 'baseball', 'ice hockey', 'cricket'
]

def is_football_fixture(fix):
    sport = (fix.get('sport', {}).get('name', '') or '').lower()
    if sport and sport != 'football' and sport != 'soccer':
        return False
    league_name = (fix.get('league', {}).get('name', '') or '').lower()
    for kw in NON_FOOTBALL_KEYWORDS:
        if kw in league_name:
            return False
    return True

# ── HTTP helpers ──────────────────────────────────────────────────────────────
def apisports_get(endpoint, params=None):
    url = f"{APISPORTS_BASE}/{endpoint}"
    headers = {"x-apisports-key": APISPORTS_KEY}
    try:
        r = httpx.get(url, headers=headers, params=params or {}, timeout=30.0)
        if r.status_code == 429:
            log.warning("  Rate limited — waiting 65s")
            time.sleep(65)
            r = httpx.get(url, headers=headers, params=params or {}, timeout=30.0)
        if r.status_code == 200:
            data = r.json()
            remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
            log.info(f"  [{endpoint}] OK · {remaining} req remaining")
            return data
        log.error(f"  API-Sports {r.status_code}: {r.text[:100]}")
        return None
    except Exception as e:
        log.error(f"  API-Sports error: {e}")
        return None

def fd_get(endpoint, params=None):
    try:
        r = httpx.get(f"{FOOTBALL_DATA_BASE}/{endpoint}",
            headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
            params=params or {}, timeout=30.0)
        if r.status_code == 429:
            log.warning("  FD rate limited — waiting 65s"); time.sleep(65)
            r = httpx.get(f"{FOOTBALL_DATA_BASE}/{endpoint}",
                headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
                params=params or {}, timeout=30.0)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.error(f"  football-data error: {e}"); return None

def openligadb_get(endpoint):
    try:
        r = httpx.get(f"{OPENLIGADB_BASE}/{endpoint}", timeout=30.0)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.error(f"  OpenLigaDB error: {e}"); return None

# ── Parse API-Sports fixture ──────────────────────────────────────────────────
def parse_apisports(fix, match_history, upcoming_data, now_utc,
                    only_finished=False, only_upcoming=False):
    if not is_football_fixture(fix):
        return "skipped"

    fdata    = fix.get("fixture", {})
    fid      = fdata.get("id")
    if not fid: return "skipped"

    status   = fdata.get("status", {}).get("short", "")
    date_str = fdata.get("date", "")
    league   = fix.get("league", {})
    teams    = fix.get("teams", {})
    goals    = fix.get("goals", {})

    league_id      = league.get("id")
    league_name    = league.get("name", "Unknown")
    league_country = league.get("country", "")
    league_logo    = league.get("logo")
    season         = league.get("season", CURRENT_SEASON)

    home      = teams.get("home", {})
    away      = teams.get("away", {})
    home_name = home.get("name", "Unknown")
    away_name = away.get("name", "Unknown")
    home_logo = home.get("logo")
    away_logo = away.get("logo")

    # Canonical IDs — consistent regardless of API
    home_id = canonical_team_id(league_id, home_name)
    away_id = canonical_team_id(league_id, away_name)
    key     = f"apisports_{fid}"

    # ── Finished match → history ──────────────────────────────────────────────
    if status in ("FT", "AET", "PEN", "AWD"):
        if only_upcoming: return "skipped"
        if key in match_history["matches"]: return "skipped"
        home_g = goals.get("home")
        away_g = goals.get("away")
        if home_g is None or away_g is None: return "skipped"

        stats    = fix.get("statistics") or []
        hs       = stats[0].get("statistics", []) if stats else []
        as_      = stats[1].get("statistics", []) if len(stats) > 1 else []
        def gs(lst, t):
            for s in lst:
                if s.get("type") == t:
                    v = s.get("value")
                    try: return int(v)
                    except: return None
            return None

        venue_raw = fdata.get("venue")
        venue_str = venue_raw.get("name") if isinstance(venue_raw, dict) else venue_raw

        match_history["matches"][key] = {
            "api_fixture_id": key, "league_id": league_id, "league_name": league_name,
            "home_team_id": home_id, "home_team_name": home_name,
            "away_team_id": away_id, "away_team_name": away_name,
            "match_date": date_str, "season": season,
            "home_goals": int(home_g), "away_goals": int(away_g),
            "referee_name": fdata.get("referee"), "venue": venue_str,
            "data_source": "apisports",
            "home_corners":          gs(hs, "Corner Kicks"),
            "away_corners":          gs(as_, "Corner Kicks"),
            "home_yellow_cards":     gs(hs, "Yellow Cards"),
            "away_yellow_cards":     gs(as_, "Yellow Cards"),
            "home_red_cards":        gs(hs, "Red Cards"),
            "away_red_cards":        gs(as_, "Red Cards"),
            "possession_home":       gs(hs, "Ball Possession"),
            "possession_away":       gs(as_, "Ball Possession"),
            "shots_home":            gs(hs, "Total Shots"),
            "shots_away":            gs(as_, "Total Shots"),
            "shots_on_target_home":  gs(hs, "Shots on Goal"),
            "shots_on_target_away":  gs(as_, "Shots on Goal"),
            "fouls_home":            gs(hs, "Fouls"),
            "fouls_away":            gs(as_, "Fouls"),
        }
        return "history"

    # ── Upcoming → fixtures ───────────────────────────────────────────────────
    elif status in ("NS", "TBD", "PST", "SUSP", "") or not status:
        if only_finished: return "skipped"
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            if dt < (now_utc - timedelta(hours=2)): return "skipped"
            date_ymd = dt.strftime("%Y%m%d")
        except Exception:
            date_ymd = date.today().strftime("%Y%m%d")

        uid = key
        existing_ids = {f.get("api_fixture_id") for f in upcoming_data["fixtures"]}
        if uid in existing_ids: return "skipped"

        venue_raw = fdata.get("venue")
        venue_str = venue_raw.get("name") if isinstance(venue_raw, dict) else venue_raw

        upcoming_data["fixtures"].append({
            "id":             f"{league_id}_{home_id}_{away_id}_{date_ymd}",
            "api_fixture_id": uid,
            "fixture_date":   date_str,
            "league_id":      league_id, "league_name":    league_name,
            "league_country": league_country, "league_logo": league_logo,
            "season":         season,
            "round":          league.get("round", ""),
            "venue":          venue_str,
            "home_team_id":   home_id, "home_team_name": home_name, "home_team_logo": home_logo,
            "away_team_id":   away_id, "away_team_name": away_name, "away_team_logo": away_logo,
            "referee_name":   fdata.get("referee"),
            "status":         status, "is_featured": False,
            "data_source":    "apisports",
            "home_xg_adjustment": 1.0, "away_xg_adjustment": 1.0,
        })
        return "upcoming"

    return "skipped"

# ── Backfill detection ────────────────────────────────────────────────────────
def league_match_count(match_history, league_id):
    return sum(1 for m in match_history.get("matches", {}).values()
               if m.get("league_id") == league_id)

def leagues_needing_backfill(match_history):
    today_month = date.today().month
    needs = []
    for lg in BACKFILL_LEAGUES:
        if "month_start" in lg and today_month < lg["month_start"]:
            continue
        cnt = league_match_count(match_history, lg["id"])
        if cnt < 40:  # Needs backfill
            needs.append((cnt, lg))
    needs.sort(key=lambda x: x[0])  # Least data first
    return needs

# ── Football-data.org supplement ──────────────────────────────────────────────
def run_football_data(match_history, upcoming_data, now_utc):
    if not FOOTBALL_DATA_KEY:
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
            {"code": "DED", "name": "Eredivisie",      "league_id": 88},
        ]

    for comp in comps:
        try:
            data = fd_get(f"competitions/{comp['code']}/matches", {
                "dateFrom": date.today().isoformat(),
                "dateTo": (date.today() + timedelta(days=14)).isoformat(),
                "status": "SCHEDULED,TIMED"
            })
            count = 0
            if data and "matches" in data:
                for m in data["matches"]:
                    mid = m.get("id")
                    if not mid: continue
                    uid = f"fd_{mid}"
                    if uid in {f.get("api_fixture_id") for f in upcoming_data["fixtures"]}:
                        continue
                    ht = m.get("homeTeam", {}); at = m.get("awayTeam", {})
                    utc_date = m.get("utcDate", "")
                    try:
                        dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
                        if dt < (now_utc - timedelta(hours=2)): continue
                        date_ymd = dt.strftime("%Y%m%d")
                    except: continue
                    hname = ht.get("name","?"); aname = at.get("name","?")
                    hid = canonical_team_id(comp["league_id"], hname)
                    aid = canonical_team_id(comp["league_id"], aname)
                    upcoming_data["fixtures"].append({
                        "id": f"{comp['league_id']}_{hid}_{aid}_{date_ymd}",
                        "api_fixture_id": uid, "fixture_date": utc_date,
                        "league_id": comp["league_id"], "league_name": comp["name"],
                        "league_country": "", "league_logo": None,
                        "season": CURRENT_SEASON, "round": str(m.get("matchday","")),
                        "venue": None,
                        "home_team_id": hid, "home_team_name": hname,
                        "home_team_logo": ht.get("crest"),
                        "away_team_id": aid, "away_team_name": aname,
                        "away_team_logo": at.get("crest"),
                        "referee_name": None, "status": "SCHEDULED",
                        "is_featured": False, "data_source": "football_data",
                        "home_xg_adjustment": 1.0, "away_xg_adjustment": 1.0,
                    })
                    count += 1
            if count: log.info(f"  [FD] {comp['name']}: {count} upcoming")
            time.sleep(7)
        except Exception as e:
            log.error(f"  [FD] {comp['name']}: {e}")

# ── OpenLigaDB (free, no key) ─────────────────────────────────────────────────
def run_openligadb(match_history, upcoming_data, now_utc):
    """German Bundesliga — completely free, no API key needed."""
    configs = [
        {"shortcut": "bl1", "league_id": 78, "name": "Bundesliga", "season": 2025},
        {"shortcut": "bl2", "league_id": 79, "name": "2. Bundesliga", "season": 2025},
    ]
    for cfg in configs:
        try:
            # Get upcoming matches
            data = openligadb_get(f"getmatchdata/{cfg['shortcut']}/{cfg['season']}")
            if not data: continue
            count_h = 0; count_u = 0
            for m in data:
                match_dt_str = m.get("matchDateTimeUTC","")
                try:
                    dt = datetime.fromisoformat(match_dt_str.replace("Z","+00:00"))
                    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                except: continue

                team1 = (m.get("team1") or {}).get("teamName","?")
                team2 = (m.get("team2") or {}).get("teamName","?")
                hid   = canonical_team_id(cfg["league_id"], team1)
                aid   = canonical_team_id(cfg["league_id"], team2)
                key   = f"oldb_{m.get('matchID','')}"

                results = m.get("matchResults") or []
                final   = next((r for r in results if r.get("resultTypeID") == 2), None)

                if final and m.get("matchIsFinished"):
                    # Finished match
                    if key not in match_history["matches"]:
                        match_history["matches"][key] = {
                            "api_fixture_id": key,
                            "league_id": cfg["league_id"], "league_name": cfg["name"],
                            "home_team_id": hid, "home_team_name": team1,
                            "away_team_id": aid, "away_team_name": team2,
                            "match_date": match_dt_str, "season": cfg["season"],
                            "home_goals": final.get("pointsTeam1",0),
                            "away_goals": final.get("pointsTeam2",0),
                            "referee_name": None, "venue": None,
                            "data_source": "openligadb",
                            "home_corners": None, "away_corners": None,
                            "home_yellow_cards": None, "away_yellow_cards": None,
                            "home_red_cards": None, "away_red_cards": None,
                            "possession_home": None, "possession_away": None,
                            "shots_home": None, "shots_away": None,
                            "shots_on_target_home": None, "shots_on_target_away": None,
                            "fouls_home": None, "fouls_away": None,
                        }
                        count_h += 1
                elif not m.get("matchIsFinished") and dt > (now_utc - timedelta(hours=2)):
                    # Upcoming
                    if key not in {f.get("api_fixture_id") for f in upcoming_data["fixtures"]}:
                        upcoming_data["fixtures"].append({
                            "id": f"{cfg['league_id']}_{hid}_{aid}_{dt.strftime('%Y%m%d')}",
                            "api_fixture_id": key, "fixture_date": match_dt_str,
                            "league_id": cfg["league_id"], "league_name": cfg["name"],
                            "league_country": "Germany", "league_logo": None,
                            "season": cfg["season"], "round": str(m.get("group",{}).get("groupName","")),
                            "venue": None,
                            "home_team_id": hid, "home_team_name": team1,
                            "home_team_logo": (m.get("team1") or {}).get("teamIconUrl"),
                            "away_team_id": aid, "away_team_name": team2,
                            "away_team_logo": (m.get("team2") or {}).get("teamIconUrl"),
                            "referee_name": None, "status": "NS", "is_featured": False,
                            "data_source": "openligadb",
                            "home_xg_adjustment": 1.0, "away_xg_adjustment": 1.0,
                        })
                        count_u += 1
            if count_h or count_u:
                log.info(f"  [OpenLigaDB] {cfg['name']}: +{count_h} history, +{count_u} upcoming")
        except Exception as e:
            log.error(f"  [OpenLigaDB] {cfg['name']}: {e}")

# ── Future fixture filter ─────────────────────────────────────────────────────
def is_future(fixture, now_utc):
    try:
        ds = fixture.get("fixture_date","")
        if not ds: return True
        dt = datetime.fromisoformat(ds.replace("Z","+00:00"))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt > (now_utc - timedelta(hours=2))
    except: return True

# ── MAIN ──────────────────────────────────────────────────────────────────────
def run():
    log.info("="*60)
    log.info("Step 1: Import data")
    log.info("="*60)

    match_history = get_match_history()
    if "matches" not in match_history:
        match_history["matches"] = {}
    existing_count = len(match_history["matches"])
    log.info(f"Existing history: {existing_count} matches")

    existing_upcoming = get_upcoming_fixtures()
    now_utc = datetime.now(timezone.utc)
    upcoming_data = {
        "fixtures": [f for f in existing_upcoming.get("fixtures",[]) if is_future(f, now_utc)]
    }
    log.info(f"Existing upcoming: {len(upcoming_data['fixtures'])} (past removed)")

    referee_data = get_referee_data()
    if "referees" not in referee_data:
        referee_data["referees"] = {}

    api_requests_used = 0

    # ── A: Check quota ────────────────────────────────────────────────────────
    remaining_quota = 95
    if APISPORTS_KEY:
        status_data = apisports_get("status")
        api_requests_used += 1
        if status_data:
            try:
                resp = status_data.get("response", {})
                if isinstance(resp, list): resp = resp[0] if resp else {}
                acct = resp.get("requests", {})
                remaining_quota = int(acct.get("remaining", 95))
                log.info(f"API quota: {acct.get('current','?')}/{acct.get('limit_day','?')} used, {remaining_quota} remaining")
            except Exception as e:
                log.warning(f"Could not parse quota: {e}")
    else:
        log.error("No FOOTBALL_API_KEY — api-sports.io disabled")

    # ── B: Today's fixtures (1 request = ALL leagues) ─────────────────────────
    if APISPORTS_KEY and remaining_quota > 10:
        today = date.today().isoformat()
        log.info(f"\n--- B: All fixtures for {today} ---")
        data = apisports_get("fixtures", {"date": today})
        api_requests_used += 1
        if data:
            fixtures = data.get("response", [])
            h_count = u_count = leagues_count = 0
            leagues_today = set()
            for fix in fixtures:
                r = parse_apisports(fix, match_history, upcoming_data, now_utc)
                if r == "history":   h_count += 1
                elif r == "upcoming": u_count += 1
                leagues_today.add((fix.get("league",{}).get("name","?")))
            log.info(f"  Today: {u_count} upcoming, {h_count} finished across {len(leagues_today)} leagues")
            for ln in sorted(leagues_today)[:20]:
                log.info(f"    · {ln}")

    # ── C: Next 7 days (7 requests) ───────────────────────────────────────────
    if APISPORTS_KEY and remaining_quota > 20:
        log.info("\n--- C: Next 7 days ---")
        for i in range(1, 8):
            if api_requests_used >= remaining_quota - 5: break
            d = (date.today() + timedelta(days=i)).isoformat()
            data = apisports_get("fixtures", {"date": d})
            api_requests_used += 1
            if data:
                count = sum(1 for fix in data.get("response",[])
                           if parse_apisports(fix, match_history, upcoming_data, now_utc,
                                             only_upcoming=True) == "upcoming")
                if count: log.info(f"  {d}: +{count} upcoming")
            time.sleep(0.3)

    # ── D: Recent results (last 3 days) ───────────────────────────────────────
    if APISPORTS_KEY and remaining_quota > 30:
        log.info("\n--- D: Recent results (last 3 days) ---")
        for i in range(1, 4):
            if api_requests_used >= remaining_quota - 5: break
            d = (date.today() - timedelta(days=i)).isoformat()
            data = apisports_get("fixtures", {"date": d, "status": "FT-AET-PEN"})
            api_requests_used += 1
            if data:
                count = sum(1 for fix in data.get("response",[])
                           if parse_apisports(fix, match_history, upcoming_data, now_utc,
                                             only_finished=True) == "history")
                if count: log.info(f"  {d}: +{count} results")
            time.sleep(0.3)

    # ── E: History backfill ───────────────────────────────────────────────────
    needs_backfill = leagues_needing_backfill(match_history)
    if APISPORTS_KEY and needs_backfill and remaining_quota > 40:
        log.info(f"\n--- E: Backfill ({len(needs_backfill)} leagues need history) ---")
        backfill_budget = min(MAX_BACKFILL_PER_RUN, remaining_quota - api_requests_used - 5)
        done = 0
        for cnt, lg in needs_backfill:
            if done >= backfill_budget: break
            if api_requests_used >= remaining_quota - 3: break
            log.info(f"  Backfilling {lg['name']} (currently {cnt} matches)...")
            data = apisports_get("fixtures", {
                "league": lg["id"], "season": lg["season"], "status": "FT-AET-PEN"
            })
            api_requests_used += 1; done += 1
            if data:
                new = sum(1 for fix in data.get("response",[])
                         if parse_apisports(fix, match_history, upcoming_data, now_utc,
                                           only_finished=True) == "history")
                log.info(f"    → +{new} historical matches")
            time.sleep(1)

    # ── F: football-data.org supplement (no quota cost) ──────────────────────
    log.info("\n--- F: football-data.org supplement ---")
    run_football_data(match_history, upcoming_data, now_utc)

    # ── G: OpenLigaDB (free, no key) ─────────────────────────────────────────
    log.info("\n--- G: OpenLigaDB (German Bundesliga, free) ---")
    run_openligadb(match_history, upcoming_data, now_utc)

    # ── H: Normalize all team IDs to canonical format ─────────────────────────
    log.info("\n--- H: Normalizing team IDs ---")
    normalized = 0
    for m in match_history["matches"].values():
        lid = m.get("league_id")
        new_h = canonical_team_id(lid, m.get("home_team_name",""))
        new_a = canonical_team_id(lid, m.get("away_team_name",""))
        if m.get("home_team_id") != new_h or m.get("away_team_id") != new_a:
            m["home_team_id"] = new_h; m["away_team_id"] = new_a
            normalized += 1
    for fx in upcoming_data["fixtures"]:
        lid = fx.get("league_id")
        new_h = canonical_team_id(lid, fx.get("home_team_name",""))
        new_a = canonical_team_id(lid, fx.get("away_team_name",""))
        if fx.get("home_team_id") != new_h or fx.get("away_team_id") != new_a:
            fx["home_team_id"] = new_h; fx["away_team_id"] = new_a
            normalized += 1
    if normalized: log.info(f"  Normalized {normalized} team IDs")

    # ── Save ──────────────────────────────────────────────────────────────────
    save_match_history(match_history)
    save_upcoming_fixtures(upcoming_data)
    save_referee_data(referee_data)

    final_count = len(match_history["matches"])
    log.info("\n" + "="*60)
    log.info("Step 1 Complete")
    log.info(f"  History:   {existing_count} → {final_count} (+{final_count-existing_count})")
    log.info(f"  Upcoming:  {len(upcoming_data['fixtures'])} fixtures")
    log.info(f"  API calls: {api_requests_used}")
    log.info("="*60)

    return {
        "existing": existing_count, "total": final_count,
        "new": final_count - existing_count,
        "upcoming": len(upcoming_data["fixtures"]),
        "api_calls": api_requests_used,
    }

if __name__ == "__main__":
    run()
