"""
pipeline/step1_import_data.py  — MULTI-SOURCE DATA IMPORTER

Works with only FOOTBALL_DATA_API_KEY set (free tier covers 12 competitions).
Add FOOTBALL_API_KEY to unlock 80+ leagues/day via api-sports.io.

SOURCE 1: football-data.org  (FOOTBALL_DATA_API_KEY) — no daily cap
  Always: Brasileirao, Copa Libertadores
  Aug-May: PL, Bundesliga, Serie A, La Liga, Ligue 1, CL, EL, etc.
  Jun-Jul: Any competition that has active fixtures will be fetched.

SOURCE 2: api-sports.io  (FOOTBALL_API_KEY) — 100 req/day free
  8 date calls = all leagues, all countries for next 8 days.
  3 back-fill calls = recent results.
  Remaining budget = backfill thin leagues.

SOURCE 3: OpenLigaDB  — completely FREE, no key
  Bundesliga 1 & 2, Austrian Bundesliga.
  Always runs.
"""

import httpx, logging, os, re, time
from datetime import datetime, timedelta, date, timezone
from pipeline.config import PATHS, CURRENT_SEASON
from pipeline.data_store import (
    get_match_history, save_match_history,
    get_upcoming_fixtures, save_upcoming_fixtures,
    get_referee_data, save_referee_data,
)

log = logging.getLogger(__name__)

FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
APISPORTS_KEY     = os.environ.get("FOOTBALL_API_KEY", "")

FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
APISPORTS_BASE     = "https://v3.football.api-sports.io"
OPENLIGADB_BASE    = "https://api.openligadb.de"


# ── Canonical team ID ─────────────────────────────────────────────────────────
def canonical_team_id(league_id, team_name: str) -> str:
    norm = re.sub(r'[^a-z0-9]+', '_', (team_name or '').lower().strip()).strip('_')
    return f"team_{league_id}_{norm}"


# ── Date helpers ──────────────────────────────────────────────────────────────
def is_future(fixture: dict, now_utc: datetime) -> bool:
    ds = fixture.get("fixture_date", "")
    if not ds:
        return True
    try:
        dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt > (now_utc - timedelta(hours=2))
    except Exception:
        return True


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def fd_get(endpoint: str, params: dict = None):
    """football-data.org GET with automatic rate-limit retry."""
    if not FOOTBALL_DATA_KEY:
        return None
    try:
        r = httpx.get(
            f"{FOOTBALL_DATA_BASE}/{endpoint}",
            headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
            params=params or {},
            timeout=30.0,
        )
        if r.status_code == 429:
            log.warning("FD rate-limited — sleeping 65s")
            time.sleep(65)
            r = httpx.get(
                f"{FOOTBALL_DATA_BASE}/{endpoint}",
                headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
                params=params or {},
                timeout=30.0,
            )
        if r.status_code == 200:
            return r.json()
        log.warning(f"FD {r.status_code} on /{endpoint}")
        return None
    except Exception as e:
        log.error(f"FD request error: {e}")
        return None


def apisports_get(endpoint: str, params: dict = None):
    """api-sports.io GET with automatic rate-limit retry."""
    if not APISPORTS_KEY:
        return None
    try:
        r = httpx.get(
            f"{APISPORTS_BASE}/{endpoint}",
            headers={"x-apisports-key": APISPORTS_KEY},
            params=params or {},
            timeout=30.0,
        )
        if r.status_code == 429:
            log.warning("API-Sports rate-limited — sleeping 65s")
            time.sleep(65)
            r = httpx.get(
                f"{APISPORTS_BASE}/{endpoint}",
                headers={"x-apisports-key": APISPORTS_KEY},
                params=params or {},
                timeout=30.0,
            )
        if r.status_code == 200:
            remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
            log.info(f"  API-Sports /{endpoint} OK · {remaining} req remaining")
            return r.json()
        log.warning(f"API-Sports {r.status_code} on /{endpoint}")
        return None
    except Exception as e:
        log.error(f"API-Sports request error: {e}")
        return None


def openligadb_get(endpoint: str):
    """OpenLigaDB GET — no auth, always free."""
    try:
        r = httpx.get(f"{OPENLIGADB_BASE}/{endpoint}", timeout=30.0)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.error(f"OpenLigaDB error: {e}")
        return None


# ── football-data.org competition list ───────────────────────────────────────
# always=True  → fetch every month of the year
# always=False → only fetch when the European season is active (Aug–May)
#                BUT: we now also try ALL competitions in June/July by
#                checking whether they actually have fixtures in the window.
FD_COMPETITIONS = [
    {"code": "BSA", "name": "Brasileirao Serie A", "league_id": 71,  "always": True},
    {"code": "CLI", "name": "Copa Libertadores",   "league_id": 13,  "always": True},
    {"code": "CSA", "name": "Copa Sudamericana",   "league_id": 11,  "always": True},
    {"code": "PL",  "name": "Premier League",      "league_id": 39,  "always": False},
    {"code": "BL1", "name": "Bundesliga",          "league_id": 78,  "always": False},
    {"code": "SA",  "name": "Serie A",             "league_id": 135, "always": False},
    {"code": "PD",  "name": "La Liga",             "league_id": 140, "always": False},
    {"code": "FL1", "name": "Ligue 1",             "league_id": 61,  "always": False},
    {"code": "DED", "name": "Eredivisie",          "league_id": 88,  "always": False},
    {"code": "PPL", "name": "Primeira Liga",       "league_id": 94,  "always": False},
    {"code": "ELC", "name": "Championship",        "league_id": 40,  "always": False},
    {"code": "CL",  "name": "Champions League",    "league_id": 2,   "always": False},
    {"code": "EL",  "name": "Europa League",       "league_id": 3,   "always": False},
]

# ── api-sports.io backfill targets ────────────────────────────────────────────
# Any league with fewer than 40 matches in history gets a full-season pull.
# Season values here match the actual API season parameter for each league.
APISPORTS_BACKFILL = [
    {"id": 71,  "name": "Brasileirao Serie A",   "season": 2025},
    {"id": 13,  "name": "Copa Libertadores",     "season": 2025},
    {"id": 11,  "name": "Copa Sudamericana",     "season": 2025},
    {"id": 128, "name": "Argentine Primera",     "season": 2025},
    {"id": 253, "name": "MLS",                   "season": 2025},
    {"id": 98,  "name": "J1 League",             "season": 2026},
    {"id": 292, "name": "K League 1",            "season": 2026},
    {"id": 103, "name": "Eliteserien Norway",    "season": 2026},
    {"id": 113, "name": "Allsvenskan Sweden",    "season": 2026},
    {"id": 244, "name": "Veikkausliiga Finland", "season": 2026},
    {"id": 164, "name": "Urvalsdeild Iceland",   "season": 2026},
    {"id": 119, "name": "Denmark Superliga",     "season": "2025-2026"},
    {"id": 203, "name": "Turkey Super Lig",      "season": "2024-2025"},
    {"id": 218, "name": "Austrian Bundesliga",   "season": "2024-2025"},
    {"id": 197, "name": "Greek Super League",    "season": "2024-2025"},
    {"id": 179, "name": "Scottish Premiership",  "season": "2024-2025"},
    {"id": 131, "name": "Venezuela Primera",     "season": 2025},
    {"id": 301, "name": "Morocco Botola",        "season": 2025},
]


# ── football-data.org source ──────────────────────────────────────────────────
def run_football_data(match_history: dict, upcoming_data: dict, now_utc: datetime):
    if not FOOTBALL_DATA_KEY:
        log.error("FOOTBALL_DATA_API_KEY not set — skipping football-data.org")
        return

    today = date.today()
    month = today.month

    # Always-active competitions + European ones when in season (Aug–May)
    # In June/July we still try all competitions — the API returns 0 fixtures
    # for off-season leagues gracefully, so this is safe and catches edge cases
    # like Champions League qualifying that starts in late June/July.
    active = [c for c in FD_COMPETITIONS if c["always"] or month >= 8 or month <= 5]

    # In Jun/Jul, also attempt all "always=False" comps — costs only API time
    # and catches any league that may have late fixtures or early restarts.
    if 6 <= month <= 7:
        extra = [c for c in FD_COMPETITIONS if not c["always"] and c not in active]
        if extra:
            log.info(f"  Jun/Jul: also attempting {len(extra)} European comps (may return 0)")
            active += extra

    log.info(f"football-data.org: {len(active)} competitions to check")

    for comp in active:
        lid  = comp["league_id"]
        code = comp["code"]
        name = comp["name"]

        existing = sum(1 for m in match_history["matches"].values()
                       if m.get("league_id") == lid)
        lookback = 365 if existing < 40 else 60
        log.info(f"  {name} ({code}): {existing} matches in history, {lookback}d lookback")

        # History
        try:
            date_from = (today - timedelta(days=lookback)).isoformat()
            data = fd_get(f"competitions/{code}/matches", {
                "dateFrom": date_from,
                "dateTo":   today.isoformat(),
                "status":   "FINISHED",
            })
            new_h = 0
            if data and "matches" in data:
                for m in data["matches"]:
                    if _fd_match_to_history(m, comp, match_history):
                        new_h += 1
            if new_h:
                log.info(f"    +{new_h} historical matches")
            time.sleep(7)  # FD free tier: 10 req/min
        except Exception as e:
            log.error(f"  {name} history error: {e}")

        # Upcoming
        try:
            data = fd_get(f"competitions/{code}/matches", {
                "dateFrom": today.isoformat(),
                "dateTo":   (today + timedelta(days=14)).isoformat(),
                "status":   "SCHEDULED,TIMED",
            })
            new_u = 0
            if data and "matches" in data:
                for m in data["matches"]:
                    if _fd_match_to_upcoming(m, comp, upcoming_data, now_utc):
                        new_u += 1
            if new_u:
                log.info(f"    +{new_u} upcoming fixtures")
            time.sleep(7)
        except Exception as e:
            log.error(f"  {name} upcoming error: {e}")


def _fd_match_to_history(m: dict, comp: dict, match_history: dict) -> bool:
    mid = m.get("id")
    if not mid:
        return False
    key = f"fd_{mid}"
    if key in match_history["matches"]:
        return False
    ft     = m.get("score", {}).get("fullTime", {})
    home_g = ft.get("home")
    away_g = ft.get("away")
    if home_g is None or away_g is None:
        return False
    ht    = m.get("homeTeam", {})
    at    = m.get("awayTeam", {})
    lid   = comp["league_id"]
    hname = ht.get("name") or ht.get("shortName") or "?"
    aname = at.get("name") or at.get("shortName") or "?"
    match_history["matches"][key] = {
        "api_fixture_id":        key,
        "league_id":             lid,
        "league_name":           comp["name"],
        "home_team_id":          canonical_team_id(lid, hname),
        "home_team_name":        hname,
        "away_team_id":          canonical_team_id(lid, aname),
        "away_team_name":        aname,
        "match_date":            m.get("utcDate", ""),
        "season":                comp.get("season", CURRENT_SEASON),
        "home_goals":            int(home_g),
        "away_goals":            int(away_g),
        "referee_name":          (m.get("referees") or [{}])[0].get("name"),
        "venue":                 None,
        "data_source":           "football_data",
        "home_corners":          None, "away_corners":          None,
        "home_yellow_cards":     None, "away_yellow_cards":     None,
        "home_red_cards":        None, "away_red_cards":        None,
        "possession_home":       None, "possession_away":       None,
        "shots_home":            None, "shots_away":            None,
        "shots_on_target_home":  None, "shots_on_target_away":  None,
        "fouls_home":            None, "fouls_away":            None,
    }
    return True


def _fd_match_to_upcoming(m: dict, comp: dict, upcoming_data: dict, now_utc: datetime) -> bool:
    mid = m.get("id")
    if not mid:
        return False
    uid = f"fd_{mid}"
    existing_ids = {f.get("api_fixture_id") for f in upcoming_data["fixtures"]}
    if uid in existing_ids:
        return False
    ht       = m.get("homeTeam", {})
    at       = m.get("awayTeam", {})
    utc_date = m.get("utcDate", "")
    try:
        dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt < (now_utc - timedelta(hours=2)):
            return False
        date_ymd = dt.strftime("%Y%m%d")
    except Exception:
        return False
    lid   = comp["league_id"]
    hname = ht.get("name") or ht.get("shortName") or "?"
    aname = at.get("name") or at.get("shortName") or "?"
    hid   = canonical_team_id(lid, hname)
    aid   = canonical_team_id(lid, aname)
    upcoming_data["fixtures"].append({
        "id":                 f"{lid}_{hid}_{aid}_{date_ymd}",
        "api_fixture_id":     uid,
        "fixture_date":       utc_date,
        "league_id":          lid,
        "league_name":        comp["name"],
        "league_country":     "",
        "league_logo":        None,
        "season":             comp.get("season", CURRENT_SEASON),
        "round":              str(m.get("matchday", "")),
        "venue":              None,
        "home_team_id":       hid,
        "home_team_name":     hname,
        "home_team_logo":     ht.get("crest"),
        "away_team_id":       aid,
        "away_team_name":     aname,
        "away_team_logo":     at.get("crest"),
        "referee_name":       None,
        "status":             "SCHEDULED",
        "is_featured":        False,
        "data_source":        "football_data",
        "home_xg_adjustment": 1.0,
        "away_xg_adjustment": 1.0,
    })
    return True


# ── api-sports.io source ──────────────────────────────────────────────────────
# Keywords that identify non-football (American sports) leagues to skip
_NON_FOOTBALL_KW = {"nfl", "nba", "nhl", "mlb", "rugby", "american football",
                    "basketball", "baseball", "hockey"}

def _is_football(fix: dict) -> bool:
    name = (fix.get("league", {}).get("name") or "").lower()
    sport = (fix.get("league", {}).get("type") or "").lower()
    return not any(kw in name for kw in _NON_FOOTBALL_KW) and sport != "american-football"


def _parse_apisports(fix: dict, match_history: dict, upcoming_data: dict,
                     now_utc: datetime, mode: str = "both") -> str:
    """Parse one api-sports fixture into history or upcoming. Returns status string."""
    if not _is_football(fix):
        return "skipped"
    fdata  = fix.get("fixture", {})
    fid    = fdata.get("id")
    if not fid:
        return "skipped"
    status = fdata.get("status", {}).get("short", "")
    ds     = fdata.get("date", "")
    league = fix.get("league", {})
    teams  = fix.get("teams", {})
    goals  = fix.get("goals", {})
    lid    = league.get("id")
    lname  = league.get("name", "?")
    season = league.get("season", CURRENT_SEASON)
    home   = teams.get("home", {})
    away   = teams.get("away", {})
    hname  = home.get("name", "?")
    aname  = away.get("name", "?")
    hid    = canonical_team_id(lid, hname)
    aid    = canonical_team_id(lid, aname)
    key    = f"ap_{fid}"
    venue_r = fdata.get("venue")
    venue_s = venue_r.get("name") if isinstance(venue_r, dict) else venue_r

    if status in ("FT", "AET", "PEN") and mode in ("both", "history"):
        if key in match_history["matches"]:
            return "dup"
        hg = goals.get("home")
        ag = goals.get("away")
        if hg is None or ag is None:
            return "skipped"
        match_history["matches"][key] = {
            "api_fixture_id":        key,
            "league_id":             lid,
            "league_name":           lname,
            "home_team_id":          hid,
            "home_team_name":        hname,
            "away_team_id":          aid,
            "away_team_name":        aname,
            "match_date":            ds,
            "season":                season,
            "home_goals":            int(hg),
            "away_goals":            int(ag),
            "referee_name":          fdata.get("referee"),
            "venue":                 venue_s,
            "data_source":           "apisports",
            "home_corners":          None, "away_corners":          None,
            "home_yellow_cards":     None, "away_yellow_cards":     None,
            "home_red_cards":        None, "away_red_cards":        None,
            "possession_home":       None, "possession_away":       None,
            "shots_home":            None, "shots_away":            None,
            "shots_on_target_home":  None, "shots_on_target_away":  None,
            "fouls_home":            None, "fouls_away":            None,
        }
        return "history"

    elif status in ("NS", "TBD", "PST", "") and mode in ("both", "upcoming"):
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < (now_utc - timedelta(hours=2)):
                return "past"
            date_ymd = dt.strftime("%Y%m%d")
        except Exception:
            return "skipped"
        existing_ids = {f.get("api_fixture_id") for f in upcoming_data["fixtures"]}
        if key in existing_ids:
            return "dup"
        upcoming_data["fixtures"].append({
            "id":                 f"{lid}_{hid}_{aid}_{date_ymd}",
            "api_fixture_id":     key,
            "fixture_date":       ds,
            "league_id":          lid,
            "league_name":        lname,
            "league_country":     league.get("country", ""),
            "league_logo":        league.get("logo"),
            "season":             season,
            "round":              league.get("round", ""),
            "venue":              venue_s,
            "home_team_id":       hid,
            "home_team_name":     hname,
            "home_team_logo":     home.get("logo"),
            "away_team_id":       aid,
            "away_team_name":     aname,
            "away_team_logo":     away.get("logo"),
            "referee_name":       fdata.get("referee"),
            "status":             status,
            "is_featured":        False,
            "data_source":        "apisports",
            "home_xg_adjustment": 1.0,
            "away_xg_adjustment": 1.0,
        })
        return "upcoming"
    return "skipped"


def run_apisports(match_history: dict, upcoming_data: dict, now_utc: datetime):
    if not APISPORTS_KEY:
        log.warning(
            "FOOTBALL_API_KEY not set — skipping api-sports.io.\n"
            "  → This is the key that unlocks 80+ leagues/day.\n"
            "  → Get it free at: https://dashboard.api-football.com\n"
            "  → Add it as FOOTBALL_API_KEY in GitHub Secrets."
        )
        return

    # Check remaining quota first
    quota = 95  # conservative default
    sd = apisports_get("status")
    if sd:
        try:
            resp = sd.get("response", {})
            if isinstance(resp, list):
                resp = resp[0] if resp else {}
            acct  = resp.get("requests", {})
            quota = int(acct.get("remaining", 95))
            log.info(
                f"API-Sports quota: {acct.get('current','?')} used / "
                f"{acct.get('limit_day','?')} limit, "
                f"{quota} remaining today"
            )
        except Exception:
            pass

    used = 1  # status call

    # ── Upcoming: today + next 7 days (8 calls = all leagues worldwide) ───────
    log.info("Fetching today + 7 days ahead (all leagues)...")
    for i in range(8):
        if used >= quota - 15:
            log.warning(f"  Quota low ({quota - used} left) — stopping upcoming fetch")
            break
        d    = (date.today() + timedelta(days=i)).isoformat()
        data = apisports_get("fixtures", {"date": d})
        used += 1
        if data:
            h = u = 0
            leagues_seen = set()
            for fix in data.get("response", []):
                r = _parse_apisports(fix, match_history, upcoming_data, now_utc)
                if r == "history":
                    h += 1
                elif r == "upcoming":
                    u += 1
                leagues_seen.add(fix.get("league", {}).get("name", "?"))
            if u or h:
                log.info(f"  {d}: +{u} upcoming, +{h} finished across {len(leagues_seen)} leagues")
        time.sleep(0.5)

    # ── Recent results: last 3 days ────────────────────────────────────────────
    log.info("Fetching recent results (last 3 days)...")
    for i in range(1, 4):
        if used >= quota - 10:
            break
        d    = (date.today() - timedelta(days=i)).isoformat()
        data = apisports_get("fixtures", {"date": d, "status": "FT-AET-PEN"})
        used += 1
        if data:
            h = sum(
                1 for fix in data.get("response", [])
                if _parse_apisports(fix, match_history, upcoming_data, now_utc, "history") == "history"
            )
            if h:
                log.info(f"  {d}: +{h} results added to history")
        time.sleep(0.5)

    # ── Backfill thin leagues ──────────────────────────────────────────────────
    # Count existing matches per league, then fetch full season for any with < 40
    existing_counts = {}
    for lg in APISPORTS_BACKFILL:
        existing_counts[lg["id"]] = sum(
            1 for m in match_history["matches"].values()
            if m.get("league_id") == lg["id"]
        )

    needs_backfill = sorted(
        [(existing_counts[lg["id"]], lg) for lg in APISPORTS_BACKFILL
         if existing_counts[lg["id"]] < 40],
        key=lambda x: x[0]  # fewest matches first
    )

    if needs_backfill:
        budget = min(len(needs_backfill), max(0, quota - used - 5))
        log.info(f"Backfilling {budget} leagues (of {len(needs_backfill)} that need it)...")
        for cnt, lg in needs_backfill[:budget]:
            if used >= quota - 3:
                log.warning("  Quota nearly exhausted — stopping backfill")
                break
            data = apisports_get("fixtures", {
                "league": lg["id"],
                "season": lg["season"],
                "status": "FT-AET-PEN",
            })
            used += 1
            if data:
                new = sum(
                    1 for fix in data.get("response", [])
                    if _parse_apisports(fix, match_history, upcoming_data, now_utc, "history") == "history"
                )
                log.info(f"  {lg['name']} (had {cnt}): +{new} historical matches")
            time.sleep(1)

    log.info(f"API-Sports total requests used today: {used}")


# ── OpenLigaDB source ─────────────────────────────────────────────────────────
def run_openligadb(match_history: dict, upcoming_data: dict, now_utc: datetime):
    """
    OpenLigaDB — completely free, no API key.
    Covers Bundesliga 1 & 2, Austrian Bundesliga.
    Season 2025 = the 2025/26 season (OpenLigaDB uses start-year).
    """
    today = date.today()
    # OpenLigaDB uses the season start year
    # 2025/26 season started Aug 2025 → season = 2025
    # We may also want previous season for history
    _season = today.year - 1 if today.month < 8 else today.year

    configs = [
        {"shortcut": "bl1",  "league_id": 78,  "name": "Bundesliga",          "season": _season},
        {"shortcut": "bl2",  "league_id": 79,  "name": "2. Bundesliga",        "season": _season},
        {"shortcut": "oefb", "league_id": 218, "name": "Austrian Bundesliga",  "season": _season},
    ]

    for cfg in configs:
        try:
            data = openligadb_get(f"getmatchdata/{cfg['shortcut']}/{cfg['season']}")
            if not data:
                log.warning(f"  OpenLigaDB {cfg['name']}: no data returned")
                continue

            h = u = 0
            for m in data:
                dt_str = m.get("matchDateTimeUTC", "")
                try:
                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                t1   = (m.get("team1") or {}).get("teamName", "?")
                t2   = (m.get("team2") or {}).get("teamName", "?")
                lid  = cfg["league_id"]
                hid  = canonical_team_id(lid, t1)
                aid  = canonical_team_id(lid, t2)
                key  = f"oldb_{m.get('matchID', '')}"

                results = m.get("matchResults") or []
                final   = next((r for r in results if r.get("resultTypeID") == 2), None)

                if final and m.get("matchIsFinished"):
                    if key not in match_history["matches"]:
                        match_history["matches"][key] = {
                            "api_fixture_id":        key,
                            "league_id":             lid,
                            "league_name":           cfg["name"],
                            "home_team_id":          hid,
                            "home_team_name":        t1,
                            "away_team_id":          aid,
                            "away_team_name":        t2,
                            "match_date":            dt_str,
                            "season":                cfg["season"],
                            "home_goals":            final.get("pointsTeam1", 0),
                            "away_goals":            final.get("pointsTeam2", 0),
                            "referee_name":          None,
                            "venue":                 None,
                            "data_source":           "openligadb",
                            "home_corners":          None, "away_corners":          None,
                            "home_yellow_cards":     None, "away_yellow_cards":     None,
                            "home_red_cards":        None, "away_red_cards":        None,
                            "possession_home":       None, "possession_away":       None,
                            "shots_home":            None, "shots_away":            None,
                            "shots_on_target_home":  None, "shots_on_target_away":  None,
                            "fouls_home":            None, "fouls_away":            None,
                        }
                        h += 1

                elif not m.get("matchIsFinished") and dt > (now_utc - timedelta(hours=2)):
                    existing_ids = {f.get("api_fixture_id") for f in upcoming_data["fixtures"]}
                    if key not in existing_ids:
                        upcoming_data["fixtures"].append({
                            "id":                 f"{lid}_{hid}_{aid}_{dt.strftime('%Y%m%d')}",
                            "api_fixture_id":     key,
                            "fixture_date":       dt_str,
                            "league_id":          lid,
                            "league_name":        cfg["name"],
                            "league_country":     "Germany" if "liga" in cfg["name"].lower() else "Austria",
                            "league_logo":        None,
                            "season":             cfg["season"],
                            "round":              str((m.get("group") or {}).get("groupName", "")),
                            "venue":              None,
                            "home_team_id":       hid,
                            "home_team_name":     t1,
                            "home_team_logo":     (m.get("team1") or {}).get("teamIconUrl"),
                            "away_team_id":       aid,
                            "away_team_name":     t2,
                            "away_team_logo":     (m.get("team2") or {}).get("teamIconUrl"),
                            "referee_name":       None,
                            "status":             "NS",
                            "is_featured":        False,
                            "data_source":        "openligadb",
                            "home_xg_adjustment": 1.0,
                            "away_xg_adjustment": 1.0,
                        })
                        u += 1

            log.info(f"  OpenLigaDB {cfg['name']}: +{h} history, +{u} upcoming")

        except Exception as e:
            log.error(f"  OpenLigaDB {cfg['name']} error: {e}")


# ── Post-processing ───────────────────────────────────────────────────────────
def normalize_all(match_history: dict, upcoming_data: dict):
    """Re-derive canonical team IDs from team names to ensure consistency."""
    fixed = 0
    for m in match_history["matches"].values():
        lid = m.get("league_id")
        nh  = canonical_team_id(lid, m.get("home_team_name", ""))
        na  = canonical_team_id(lid, m.get("away_team_name", ""))
        if m.get("home_team_id") != nh or m.get("away_team_id") != na:
            m["home_team_id"] = nh
            m["away_team_id"] = na
            fixed += 1
    for fx in upcoming_data["fixtures"]:
        lid = fx.get("league_id")
        nh  = canonical_team_id(lid, fx.get("home_team_name", ""))
        na  = canonical_team_id(lid, fx.get("away_team_name", ""))
        if fx.get("home_team_id") != nh or fx.get("away_team_id") != na:
            fx["home_team_id"] = nh
            fx["away_team_id"] = na
            fixed += 1
    if fixed:
        log.info(f"  Normalized {fixed} team IDs")


def filter_past(upcoming_data: dict, now_utc: datetime):
    """Remove fixtures that have already started (with 2-hour grace period)."""
    before = len(upcoming_data["fixtures"])
    upcoming_data["fixtures"] = [
        f for f in upcoming_data["fixtures"] if is_future(f, now_utc)
    ]
    removed = before - len(upcoming_data["fixtures"])
    if removed:
        log.info(f"  Removed {removed} past fixtures from upcoming")


def deduplicate_upcoming(upcoming_data: dict):
    """
    Remove duplicate fixtures (same teams + same date from multiple sources).
    Prefers api-sports fixtures over others when duplicates exist.
    """
    seen    = {}  # canonical_key → index in fixtures list
    priority = {"apisports": 0, "football_data": 1, "openligadb": 2, "thesportsdb": 3, "bsd": 4}

    deduped   = []
    removed   = 0
    for fx in upcoming_data["fixtures"]:
        hid      = fx.get("home_team_id", "")
        aid      = fx.get("away_team_id", "")
        date_str = fx.get("fixture_date", "")[:10]
        canon_key = f"{hid}_vs_{aid}_{date_str}"

        if canon_key not in seen:
            seen[canon_key] = len(deduped)
            deduped.append(fx)
        else:
            # Keep the one from the higher-priority source
            existing      = deduped[seen[canon_key]]
            existing_prio = priority.get(existing.get("data_source", ""), 99)
            new_prio      = priority.get(fx.get("data_source", ""), 99)
            if new_prio < existing_prio:
                deduped[seen[canon_key]] = fx
            removed += 1

    upcoming_data["fixtures"] = deduped
    if removed:
        log.info(f"  Removed {removed} duplicate upcoming fixtures")


# ── MAIN ──────────────────────────────────────────────────────────────────────
def run():
    log.info("=" * 60)
    log.info("Step 1: Import data")
    log.info(f"  FOOTBALL_DATA_API_KEY : {'SET ✓' if FOOTBALL_DATA_KEY else 'NOT SET ✗'}")
    log.info(f"  FOOTBALL_API_KEY      : {'SET ✓' if APISPORTS_KEY else 'NOT SET ✗ (set this for 80+ leagues)'}")
    log.info(f"  CURRENT_SEASON        : {CURRENT_SEASON}")
    log.info("=" * 60)

    if not FOOTBALL_DATA_KEY and not APISPORTS_KEY:
        log.error(
            "CRITICAL: No API keys set.\n"
            "  At minimum, set FOOTBALL_DATA_API_KEY in GitHub Secrets.\n"
            "  Get it free at: https://www.football-data.org/client/register\n"
            "  Without it, pipeline will produce no new fixtures."
        )
        # Don't exit — OpenLigaDB still runs without any key

    match_history = get_match_history()
    if "matches" not in match_history:
        match_history["matches"] = {}
    existing_history = len(match_history["matches"])
    log.info(f"Existing history: {existing_history} matches")

    existing_upcoming = get_upcoming_fixtures()
    now_utc           = datetime.now(timezone.utc)
    upcoming_data     = {"fixtures": list(existing_upcoming.get("fixtures", []))}

    filter_past(upcoming_data, now_utc)
    log.info(f"Existing upcoming: {len(upcoming_data['fixtures'])} fixtures (after removing past)")

    # ── Run all sources ────────────────────────────────────────────────────────
    log.info("\n--- SOURCE 1: football-data.org ---")
    run_football_data(match_history, upcoming_data, now_utc)

    log.info("\n--- SOURCE 2: api-sports.io ---")
    run_apisports(match_history, upcoming_data, now_utc)

    log.info("\n--- SOURCE 3: OpenLigaDB (free, no key) ---")
    run_openligadb(match_history, upcoming_data, now_utc)

    # ── Post-processing ────────────────────────────────────────────────────────
    log.info("\n--- Post-processing ---")
    normalize_all(match_history, upcoming_data)
    filter_past(upcoming_data, now_utc)
    deduplicate_upcoming(upcoming_data)

    # ── Save ──────────────────────────────────────────────────────────────────
    save_match_history(match_history)
    save_upcoming_fixtures(upcoming_data)

    final_history  = len(match_history["matches"])
    final_upcoming = len(upcoming_data["fixtures"])

    log.info("\n" + "=" * 60)
    log.info("Step 1 Complete")
    log.info(f"  History:  {existing_history} → {final_history} (+{final_history - existing_history})")
    log.info(f"  Upcoming: {final_upcoming} fixtures")

    if final_upcoming == 0:
        log.warning(
            "  ⚠ No upcoming fixtures found.\n"
            "  → Check that FOOTBALL_API_KEY is set in GitHub Secrets.\n"
            "  → football-data.org has limited June/July coverage.\n"
            "  → OpenLigaDB returns no fixtures during the summer break."
        )

    # League breakdown
    lgs: dict[str, int] = {}
    for fx in upcoming_data["fixtures"]:
        l = fx.get("league_name", "?")
        lgs[l] = lgs.get(l, 0) + 1
    if lgs:
        log.info("  Upcoming by league:")
        for l, c in sorted(lgs.items(), key=lambda x: -x[1]):
            log.info(f"    {l}: {c}")

    # Source breakdown
    srcs: dict[str, int] = {}
    for fx in upcoming_data["fixtures"]:
        s = fx.get("data_source", "?")
        srcs[s] = srcs.get(s, 0) + 1
    if srcs:
        log.info("  Upcoming by source:")
        for s, c in sorted(srcs.items(), key=lambda x: -x[1]):
            log.info(f"    {s}: {c}")

    log.info("=" * 60)

    return {
        "existing": existing_history,
        "total":    final_history,
        "upcoming": final_upcoming,
    }


if __name__ == "__main__":
    run()
