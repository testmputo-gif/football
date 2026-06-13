"""
pipeline/step1_import_data.py — 100% KEYLESS MULTI-SOURCE IMPORTER

Every source here is completely free with no API key required.
If one source fails or returns nothing, the next one runs automatically.
Deduplication is done by (league_id, home_team_id, away_team_id, date) so
no match ever appears twice regardless of which source found it first.

SOURCES (in priority order):
  1. OpenLigaDB         — Bundesliga 1&2, Austrian Bundesliga. Always free.
  2. TheSportsDB v1     — 1000+ leagues worldwide. Free tier, no key.
  3. ESPN hidden API    — Scores and fixtures, no auth required.
  4. ClubElo            — Elo ratings supplement (no key, free).

DEDUPLICATION STRATEGY:
  canonical key = f"{league_id}:{home_team_id}:{away_team_id}:{date_ymd}"
  Within a league, a team can only appear once per day.
  Source priority: openligadb > thesportsdb > espn > clubelo

TEAM ID STRATEGY:
  canonical_team_id(league_id, team_name) → "team_{lid}_{normalized_name}"
  This guarantees the same team is always the same ID regardless of source.

PIPELINE REPORT:
  At the end of each run, writes data/logs/import_report.json with:
  - Each source: success/fail/skipped, fixtures_added, matches_added, error
  - Total fixtures, total history, leagues covered
  This file is read by the frontend Data Sources page.
"""

import httpx
import json
import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, date, timezone
from pipeline.config import PATHS, CURRENT_SEASON
from pipeline.data_store import (
    get_match_history, save_match_history,
    get_upcoming_fixtures, save_upcoming_fixtures,
)

log = logging.getLogger(__name__)

# ── Team ID helpers ───────────────────────────────────────────────────────────

def canonical_team_id(league_id, team_name: str) -> str:
    """
    Stable team ID derived from league + team name.
    Same team name in same league = same ID, regardless of source.
    """
    norm = re.sub(r'[^a-z0-9]+', '_', (team_name or '').lower().strip()).strip('_')
    return f"team_{league_id}_{norm}"


def canonical_fixture_key(league_id, home_team_id: str, away_team_id: str, date_ymd: str) -> str:
    """
    Deduplication key. Within a league, the same two teams on the same date
    can only appear once.
    """
    return f"{league_id}:{home_team_id}:{away_team_id}:{date_ymd}"


# ── HTTP helper ───────────────────────────────────────────────────────────────

def http_get(url: str, params: dict = None, headers: dict = None,
             timeout: float = 20.0, retries: int = 2) -> dict | list | None:
    """
    GET with retry. Returns parsed JSON or None on any error.
    Never raises — all errors are caught and logged.
    """
    h = {"User-Agent": "StatPredict/2.0 (football prediction research)"}
    if headers:
        h.update(headers)
    for attempt in range(retries + 1):
        try:
            r = httpx.get(url, params=params or {}, headers=h,
                          timeout=timeout, follow_redirects=True)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = min(60, 10 * (attempt + 1))
                log.warning(f"  Rate limited on {url} — sleeping {wait}s")
                time.sleep(wait)
                continue
            if r.status_code in (403, 404):
                return None
            log.debug(f"  HTTP {r.status_code} on {url}")
            return None
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
            else:
                log.debug(f"  Request failed {url}: {e}")
    return None


# ── Date helpers ──────────────────────────────────────────────────────────────

def is_future_fixture(date_str: str, now_utc: datetime, grace_hours: int = 2) -> bool:
    if not date_str:
        return True
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt > (now_utc - timedelta(hours=grace_hours))
    except Exception:
        return True


def parse_date_ymd(date_str: str) -> str | None:
    """Extract YYYYMMDD from any ISO date string."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%Y%m%d")
    except Exception:
        return None


def make_iso(date_str: str) -> str | None:
    """Normalise date string to ISO 8601 UTC."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return date_str


# ── SOURCE 1: OpenLigaDB — Bundesliga 1&2, Austrian Bundesliga ───────────────

OPENLIGADB_COMPS = [
    {"shortcut": "bl1",  "league_id": 78,  "name": "Bundesliga",         "country": "Germany"},
    {"shortcut": "bl2",  "league_id": 79,  "name": "2. Bundesliga",       "country": "Germany"},
    {"shortcut": "oefb", "league_id": 218, "name": "Austrian Bundesliga", "country": "Austria"},
]

def source_openligadb(match_history: dict, upcoming_data: dict,
                       dedup_keys: set, now_utc: datetime) -> dict:
    report = {"source": "openligadb", "fixtures": 0, "history": 0,
               "leagues": [], "errors": [], "status": "ok"}
    today = date.today()
    # OpenLigaDB uses season start year: 2025/26 = 2025
    season = today.year - 1 if today.month < 8 else today.year

    for cfg in OPENLIGADB_COMPS:
        lid = cfg["league_id"]
        data = http_get(f"https://api.openligadb.de/getmatchdata/{cfg['shortcut']}/{season}")
        if not data:
            report["errors"].append(f"{cfg['name']}: no data")
            continue

        league_fixtures = league_history = 0
        for m in data:
            dt_str = m.get("matchDateTimeUTC", "")
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            t1    = (m.get("team1") or {}).get("teamName", "?")
            t2    = (m.get("team2") or {}).get("teamName", "?")
            hid   = canonical_team_id(lid, t1)
            aid   = canonical_team_id(lid, t2)
            d_ymd = dt.strftime("%Y%m%d")
            key   = canonical_fixture_key(lid, hid, aid, d_ymd)
            src_key = f"oldb_{m.get('matchID', '')}"

            results = m.get("matchResults") or []
            final   = next((r for r in results if r.get("resultTypeID") == 2), None)
            finished = m.get("matchIsFinished", False)

            base = {
                "league_id": lid, "league_name": cfg["name"],
                "home_team_id": hid, "home_team_name": t1,
                "away_team_id": aid, "away_team_name": t2,
                "match_date": dt.isoformat(), "season": season,
                "referee_name": None, "venue": None,
                "data_source": "openligadb",
                "home_corners": None, "away_corners": None,
                "home_yellow_cards": None, "away_yellow_cards": None,
                "home_red_cards": None, "away_red_cards": None,
            }

            if finished and final:
                if src_key not in match_history["matches"] and key not in dedup_keys:
                    match_history["matches"][src_key] = {
                        **base,
                        "api_fixture_id": src_key,
                        "home_goals": final.get("pointsTeam1", 0),
                        "away_goals": final.get("pointsTeam2", 0),
                    }
                    dedup_keys.add(key)
                    league_history += 1

            elif not finished and is_future_fixture(dt_str, now_utc):
                if key not in dedup_keys:
                    upcoming_data["fixtures"].append({
                        **base,
                        "id": f"{lid}_{hid}_{aid}_{d_ymd}",
                        "api_fixture_id": src_key,
                        "fixture_date": dt.isoformat(),
                        "league_country": cfg["country"],
                        "league_logo": None,
                        "round": str((m.get("group") or {}).get("groupName", "")),
                        "venue": None,
                        "home_team_logo": (m.get("team1") or {}).get("teamIconUrl"),
                        "away_team_logo": (m.get("team2") or {}).get("teamIconUrl"),
                        "status": "NS",
                        "is_featured": False,
                        "home_xg_adjustment": 1.0,
                        "away_xg_adjustment": 1.0,
                    })
                    dedup_keys.add(key)
                    league_fixtures += 1

        if league_fixtures or league_history:
            report["leagues"].append(cfg["name"])
        report["fixtures"] += league_fixtures
        report["history"] += league_history
        log.info(f"  OpenLigaDB {cfg['name']}: +{league_fixtures} fixtures, +{league_history} history")

    return report


# ── SOURCE 2: TheSportsDB — free, no key ─────────────────────────────────────

# TheSportsDB free endpoints that don't need a key:
# /api/v1/json/3/eventsnextleague.php?id=LEAGUE_ID
# /api/v1/json/3/eventspastleague.php?id=LEAGUE_ID

THESPORTSDB_LEAGUES = [
    {"id": "4328", "league_id": 39,  "name": "Premier League",         "country": "England"},
    {"id": "4329", "league_id": 40,  "name": "Championship",           "country": "England"},
    {"id": "4335", "league_id": 135, "name": "Serie A",                "country": "Italy"},
    {"id": "4332", "league_id": 140, "name": "La Liga",                "country": "Spain"},
    {"id": "4334", "league_id": 61,  "name": "Ligue 1",                "country": "France"},
    {"id": "4331", "league_id": 78,  "name": "Bundesliga",             "country": "Germany"},
    {"id": "4337", "league_id": 88,  "name": "Eredivisie",             "country": "Netherlands"},
    {"id": "4480", "league_id": 94,  "name": "Primeira Liga",          "country": "Portugal"},
    {"id": "4346", "league_id": 71,  "name": "Brasileirao Serie A",    "country": "Brazil"},
    {"id": "4356", "league_id": 253, "name": "MLS",                    "country": "USA"},
    {"id": "4358", "league_id": 98,  "name": "J1 League",              "country": "Japan"},
    {"id": "4397", "league_id": 113, "name": "Allsvenskan",            "country": "Sweden"},
    {"id": "4396", "league_id": 103, "name": "Eliteserien",            "country": "Norway"},
    {"id": "4422", "league_id": 244, "name": "Veikkausliiga",          "country": "Finland"},
    {"id": "4350", "league_id": 128, "name": "Argentine Primera",      "country": "Argentina"},
    {"id": "4399", "league_id": 203, "name": "Turkey Super Lig",       "country": "Turkey"},
    {"id": "4351", "league_id": 218, "name": "Austrian Bundesliga",    "country": "Austria"},
    {"id": "4388", "league_id": 197, "name": "Greek Super League",     "country": "Greece"},
    {"id": "4408", "league_id": 119, "name": "Denmark Superliga",      "country": "Denmark"},
    {"id": "4344", "league_id": 292, "name": "K League 1",             "country": "South Korea"},
    {"id": "4468", "league_id": 11,  "name": "Copa Libertadores",      "country": "South America"},
]

TSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"

def _parse_tsdb_event(ev: dict, league_cfg: dict, kind: str,
                       match_history: dict, upcoming_data: dict,
                       dedup_keys: set, now_utc: datetime) -> str:
    lid   = league_cfg["league_id"]
    hname = ev.get("strHomeTeam", "?")
    aname = ev.get("strAwayTeam", "?")
    hid   = canonical_team_id(lid, hname)
    aid   = canonical_team_id(lid, aname)
    eid   = ev.get("idEvent", "")
    src_key = f"tsdb_{eid}"
    date_str = ev.get("dateEvent", "")
    time_str = ev.get("strTime", "00:00:00")
    if not date_str:
        return "skipped"

    full_dt_str = f"{date_str}T{time_str}+00:00" if time_str else f"{date_str}T00:00:00+00:00"
    d_ymd = date_str.replace("-", "")
    key   = canonical_fixture_key(lid, hid, aid, d_ymd)

    base = {
        "league_id": lid, "league_name": league_cfg["name"],
        "home_team_id": hid, "home_team_name": hname,
        "away_team_id": aid, "away_team_name": aname,
        "match_date": full_dt_str, "season": CURRENT_SEASON,
        "referee_name": None, "venue": ev.get("strVenue"),
        "data_source": "thesportsdb",
        "home_corners": None, "away_corners": None,
        "home_yellow_cards": None, "away_yellow_cards": None,
        "home_red_cards": None, "away_red_cards": None,
    }

    if kind == "history":
        hg = ev.get("intHomeScore")
        ag = ev.get("intAwayScore")
        if hg is None or ag is None:
            return "skipped"
        if src_key not in match_history["matches"] and key not in dedup_keys:
            try:
                match_history["matches"][src_key] = {
                    **base,
                    "api_fixture_id": src_key,
                    "home_goals": int(hg),
                    "away_goals": int(ag),
                }
                dedup_keys.add(key)
                return "history"
            except (ValueError, TypeError):
                return "skipped"
    else:
        if key not in dedup_keys and is_future_fixture(full_dt_str, now_utc):
            upcoming_data["fixtures"].append({
                **base,
                "id": f"{lid}_{hid}_{aid}_{d_ymd}",
                "api_fixture_id": src_key,
                "fixture_date": full_dt_str,
                "league_country": league_cfg.get("country", ""),
                "league_logo": ev.get("strLeagueBadge"),
                "round": ev.get("intRound", ""),
                "home_team_logo": ev.get("strHomeTeamBadge"),
                "away_team_logo": ev.get("strAwayTeamBadge"),
                "status": "NS",
                "is_featured": False,
                "home_xg_adjustment": 1.0,
                "away_xg_adjustment": 1.0,
            })
            dedup_keys.add(key)
            return "upcoming"
    return "skipped"


def source_thesportsdb(match_history: dict, upcoming_data: dict,
                        dedup_keys: set, now_utc: datetime) -> dict:
    report = {"source": "thesportsdb", "fixtures": 0, "history": 0,
               "leagues": [], "errors": [], "status": "ok"}

    for cfg in THESPORTSDB_LEAGUES:
        lid = cfg["id"]
        f = h = 0

        # Upcoming
        data = http_get(f"{TSDB_BASE}/eventsnextleague.php", {"id": lid})
        if data and data.get("events"):
            for ev in data["events"]:
                r = _parse_tsdb_event(ev, cfg, "upcoming",
                                      match_history, upcoming_data, dedup_keys, now_utc)
                if r == "upcoming": f += 1
        time.sleep(0.3)

        # Recent history (past events)
        data = http_get(f"{TSDB_BASE}/eventspastleague.php", {"id": lid})
        if data and data.get("events"):
            for ev in data["events"]:
                r = _parse_tsdb_event(ev, cfg, "history",
                                      match_history, upcoming_data, dedup_keys, now_utc)
                if r == "history": h += 1
        time.sleep(0.3)

        if f or h:
            report["leagues"].append(cfg["name"])
            log.info(f"  TheSportsDB {cfg['name']}: +{f} fixtures, +{h} history")

        report["fixtures"] += f
        report["history"]  += h

    return report


# ── SOURCE 3: ESPN public API — no auth ───────────────────────────────────────

ESPN_LEAGUES = [
    {"slug": "eng.1",  "league_id": 39,  "name": "Premier League",      "country": "England"},
    {"slug": "eng.2",  "league_id": 40,  "name": "Championship",        "country": "England"},
    {"slug": "esp.1",  "league_id": 140, "name": "La Liga",             "country": "Spain"},
    {"slug": "ger.1",  "league_id": 78,  "name": "Bundesliga",          "country": "Germany"},
    {"slug": "ita.1",  "league_id": 135, "name": "Serie A",             "country": "Italy"},
    {"slug": "fra.1",  "league_id": 61,  "name": "Ligue 1",             "country": "France"},
    {"slug": "ned.1",  "league_id": 88,  "name": "Eredivisie",          "country": "Netherlands"},
    {"slug": "por.1",  "league_id": 94,  "name": "Primeira Liga",       "country": "Portugal"},
    {"slug": "usa.1",  "league_id": 253, "name": "MLS",                 "country": "USA"},
    {"slug": "bra.1",  "league_id": 71,  "name": "Brasileirao",         "country": "Brazil"},
    {"slug": "arg.1",  "league_id": 128, "name": "Argentine Primera",   "country": "Argentina"},
    {"slug": "jpn.1",  "league_id": 98,  "name": "J1 League",           "country": "Japan"},
    {"slug": "tur.1",  "league_id": 203, "name": "Turkey Super Lig",    "country": "Turkey"},
    {"slug": "swe.1",  "league_id": 113, "name": "Allsvenskan",         "country": "Sweden"},
    {"slug": "nor.1",  "league_id": 103, "name": "Eliteserien",         "country": "Norway"},
    {"slug": "mex.1",  "league_id": 262, "name": "Liga MX",             "country": "Mexico"},
    {"slug": "aus.1",  "league_id": 188, "name": "A-League",            "country": "Australia"},
    {"slug": "sco.1",  "league_id": 179, "name": "Scottish Prem",       "country": "Scotland"},
    {"slug": "gre.1",  "league_id": 197, "name": "Greek Super League",  "country": "Greece"},
]

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

def source_espn(match_history: dict, upcoming_data: dict,
                dedup_keys: set, now_utc: datetime) -> dict:
    report = {"source": "espn", "fixtures": 0, "history": 0,
               "leagues": [], "errors": [], "status": "ok"}

    today = date.today()
    # Fetch next 14 days and past 14 days
    date_ranges = []
    for delta in range(-14, 15):
        d = today + timedelta(days=delta)
        date_ranges.append(d.strftime("%Y%m%d"))

    for cfg in ESPN_LEAGUES:
        slug = cfg["slug"]
        lid  = cfg["league_id"]
        f = h = 0

        for d_str in date_ranges:
            data = http_get(
                f"{ESPN_BASE}/{slug}/scoreboard",
                {"dates": d_str, "limit": 50}
            )
            if not data:
                continue

            for event in data.get("events", []):
                comps = event.get("competitions", [{}])
                comp  = comps[0] if comps else {}
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue

                # ESPN uses competitor[0] = home if "homeAway" == "home"
                home_comp = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away_comp = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

                hname = home_comp.get("team", {}).get("displayName", "?")
                aname = away_comp.get("team", {}).get("displayName", "?")
                hid   = canonical_team_id(lid, hname)
                aid   = canonical_team_id(lid, aname)
                eid   = event.get("id", "")
                src_key = f"espn_{eid}"
                dt_str = event.get("date", "")
                d_ymd  = parse_date_ymd(dt_str) or d_str
                key    = canonical_fixture_key(lid, hid, aid, d_ymd)

                status_type = comp.get("status", {}).get("type", {})
                completed   = status_type.get("completed", False)
                state       = status_type.get("state", "")  # pre / in / post

                base = {
                    "league_id": lid, "league_name": cfg["name"],
                    "home_team_id": hid, "home_team_name": hname,
                    "away_team_id": aid, "away_team_name": aname,
                    "match_date": make_iso(dt_str) or dt_str,
                    "season": CURRENT_SEASON,
                    "referee_name": None,
                    "venue": (comp.get("venue") or {}).get("fullName"),
                    "data_source": "espn",
                    "home_corners": None, "away_corners": None,
                    "home_yellow_cards": None, "away_yellow_cards": None,
                    "home_red_cards": None, "away_red_cards": None,
                }

                if completed and state == "post":
                    hg_str = home_comp.get("score", "")
                    ag_str = away_comp.get("score", "")
                    try:
                        hg = int(hg_str)
                        ag = int(ag_str)
                    except (ValueError, TypeError):
                        continue
                    if src_key not in match_history["matches"] and key not in dedup_keys:
                        match_history["matches"][src_key] = {
                            **base,
                            "api_fixture_id": src_key,
                            "home_goals": hg,
                            "away_goals": ag,
                        }
                        dedup_keys.add(key)
                        h += 1

                elif state == "pre" and is_future_fixture(dt_str, now_utc):
                    if key not in dedup_keys:
                        upcoming_data["fixtures"].append({
                            **base,
                            "id": f"{lid}_{hid}_{aid}_{d_ymd}",
                            "api_fixture_id": src_key,
                            "fixture_date": make_iso(dt_str) or dt_str,
                            "league_country": cfg.get("country", ""),
                            "league_logo": None,
                            "round": "",
                            "home_team_logo": home_comp.get("team", {}).get("logo"),
                            "away_team_logo": away_comp.get("team", {}).get("logo"),
                            "status": "NS",
                            "is_featured": False,
                            "home_xg_adjustment": 1.0,
                            "away_xg_adjustment": 1.0,
                        })
                        dedup_keys.add(key)
                        f += 1

            time.sleep(0.1)

        if f or h:
            report["leagues"].append(cfg["name"])
            log.info(f"  ESPN {cfg['name']}: +{f} fixtures, +{h} history")

        report["fixtures"] += f
        report["history"]  += h

    return report


# (football-data.org source removed — required API key, was returning 403s)


# ── SOURCE 5: ClubElo — free Elo rating data ──────────────────────────────────

def source_clubelo(match_history: dict, upcoming_data: dict,
                   dedup_keys: set, now_utc: datetime) -> dict:
    """
    ClubElo provides historical results with Elo context — CSV, no key.
    We use it to supplement history for major European leagues.
    URL: http://clubelo.com/API
    """
    report = {"source": "clubelo", "fixtures": 0, "history": 0,
               "leagues": [], "errors": [], "status": "ok"}

    # ClubElo recent matches endpoint: returns CSV with date, home, away, hg, ag
    clubs_to_check = [
        # These are the club slugs ClubElo uses
        # We query each major league's recent results
        ("ENG1", 39, "Premier League"),
        ("ESP1", 140, "La Liga"),
        ("GER1", 78, "Bundesliga"),
        ("ITA1", 135, "Serie A"),
        ("FRA1", 61, "Ligue 1"),
    ]

    today = date.today()
    date_from = (today - timedelta(days=30)).strftime("%Y-%m-%d")

    for code, lid, name in clubs_to_check:
        try:
            r = httpx.get(
                f"http://clubelo.com/{date_from}/{code}",
                headers={"User-Agent": "StatPredict/2.0"},
                timeout=15.0,
                follow_redirects=True,
            )
            if r.status_code != 200:
                continue

            lines = r.text.strip().split("\n")
            h = 0
            for line in lines[1:]:  # skip header
                parts = line.split(";")
                if len(parts) < 8:
                    continue
                try:
                    dt_str = parts[0].strip()
                    hname  = parts[2].strip()
                    aname  = parts[3].strip()
                    hg     = int(parts[5].strip())
                    ag     = int(parts[6].strip())
                except (ValueError, IndexError):
                    continue

                hid      = canonical_team_id(lid, hname)
                aid      = canonical_team_id(lid, aname)
                d_ymd    = dt_str.replace("-", "")
                key      = canonical_fixture_key(lid, hid, aid, d_ymd)
                src_key  = f"celo_{code}_{d_ymd}_{hid}_{aid}"

                if src_key not in match_history["matches"] and key not in dedup_keys:
                    match_history["matches"][src_key] = {
                        "api_fixture_id": src_key,
                        "league_id": lid, "league_name": name,
                        "home_team_id": hid, "home_team_name": hname,
                        "away_team_id": aid, "away_team_name": aname,
                        "match_date": f"{dt_str}T15:00:00+00:00",
                        "season": CURRENT_SEASON,
                        "home_goals": hg, "away_goals": ag,
                        "referee_name": None, "venue": None,
                        "data_source": "clubelo",
                        "home_corners": None, "away_corners": None,
                        "home_yellow_cards": None, "away_yellow_cards": None,
                        "home_red_cards": None, "away_red_cards": None,
                    }
                    dedup_keys.add(key)
                    h += 1

            if h:
                report["leagues"].append(name)
                report["history"] += h
                log.info(f"  ClubElo {name}: +{h} history")

        except Exception as e:
            report["errors"].append(f"{name}: {e}")
        time.sleep(1)

    return report


# ── Post-processing ───────────────────────────────────────────────────────────

def normalize_team_ids(match_history: dict, upcoming_data: dict):
    """Re-derive canonical IDs to ensure consistency across sources."""
    for m in match_history["matches"].values():
        lid = m.get("league_id")
        m["home_team_id"] = canonical_team_id(lid, m.get("home_team_name", ""))
        m["away_team_id"] = canonical_team_id(lid, m.get("away_team_name", ""))
    for fx in upcoming_data["fixtures"]:
        lid = fx.get("league_id")
        fx["home_team_id"] = canonical_team_id(lid, fx.get("home_team_name", ""))
        fx["away_team_id"] = canonical_team_id(lid, fx.get("away_team_name", ""))


def filter_past_fixtures(upcoming_data: dict, now_utc: datetime):
    before = len(upcoming_data["fixtures"])
    upcoming_data["fixtures"] = [
        f for f in upcoming_data["fixtures"]
        if is_future_fixture(f.get("fixture_date", ""), now_utc)
    ]
    removed = before - len(upcoming_data["fixtures"])
    if removed:
        log.info(f"  Removed {removed} past fixtures")


def sort_upcoming(upcoming_data: dict):
    upcoming_data["fixtures"].sort(key=lambda f: f.get("fixture_date", ""))


# ── MAIN ──────────────────────────────────────────────────────────────────────

SOURCES = [
    ("OpenLigaDB",     source_openligadb,     "Bundesliga 1&2, Austrian Bundesliga"),
    ("TheSportsDB",    source_thesportsdb,    "1000+ leagues worldwide"),
    ("ESPN",           source_espn,           "Major leagues, scoreboard API"),
    ("ClubElo",        source_clubelo,        "Top 5 European league history"),
]


def run():
    log.info("=" * 60)
    log.info("Step 1: Import data — 100% keyless multi-source")
    log.info("=" * 60)

    match_history = get_match_history()
    if "matches" not in match_history:
        match_history["matches"] = {}
    existing_history = len(match_history["matches"])

    existing_upcoming = get_upcoming_fixtures()
    now_utc           = datetime.now(timezone.utc)
    upcoming_data     = {"fixtures": list(existing_upcoming.get("fixtures", []))}

    filter_past_fixtures(upcoming_data, now_utc)
    log.info(f"Starting: {existing_history} historical matches, "
             f"{len(upcoming_data['fixtures'])} existing upcoming")

    # Build dedup set from existing data to prevent re-adding known fixtures
    dedup_keys: set[str] = set()
    for fx in upcoming_data["fixtures"]:
        lid   = fx.get("league_id")
        hid   = fx.get("home_team_id")
        aid   = fx.get("away_team_id")
        d_ymd = parse_date_ymd(fx.get("fixture_date", ""))
        if all([lid, hid, aid, d_ymd]):
            dedup_keys.add(canonical_fixture_key(lid, hid, aid, d_ymd))
    for m in match_history["matches"].values():
        lid   = m.get("league_id")
        hid   = m.get("home_team_id")
        aid   = m.get("away_team_id")
        d_ymd = parse_date_ymd(m.get("match_date", ""))
        if all([lid, hid, aid, d_ymd]):
            dedup_keys.add(canonical_fixture_key(lid, hid, aid, d_ymd))

    # ── Run each source — failure of one never stops the others ──────────────
    all_reports = []
    for source_name, source_fn, source_desc in SOURCES:
        log.info(f"\n--- {source_name}: {source_desc} ---")
        try:
            report = source_fn(match_history, upcoming_data, dedup_keys, now_utc)
            all_reports.append(report)
            log.info(f"  {source_name} done: +{report['fixtures']} fixtures, "
                     f"+{report['history']} history")
        except Exception as e:
            log.error(f"  {source_name} FAILED: {e}")
            all_reports.append({
                "source": source_name.lower().replace(" ", "_"),
                "fixtures": 0, "history": 0,
                "leagues": [], "errors": [str(e)], "status": "error",
            })

    # ── Post-processing ───────────────────────────────────────────────────────
    log.info("\n--- Post-processing ---")
    normalize_team_ids(match_history, upcoming_data)
    filter_past_fixtures(upcoming_data, now_utc)
    sort_upcoming(upcoming_data)

    # ── Save ──────────────────────────────────────────────────────────────────
    save_match_history(match_history)
    save_upcoming_fixtures(upcoming_data)

    final_history  = len(match_history["matches"])
    final_upcoming = len(upcoming_data["fixtures"])

    # ── Build import report for frontend ──────────────────────────────────────
    league_counts = defaultdict(int)
    for fx in upcoming_data["fixtures"]:
        league_counts[fx.get("league_name", "?")] += 1

    source_counts = defaultdict(int)
    for fx in upcoming_data["fixtures"]:
        source_counts[fx.get("data_source", "?")] += 1

    import_report = {
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "total_history":      final_history,
        "total_upcoming":     final_upcoming,
        "new_history":        final_history - existing_history,
        "leagues_covered":    len(league_counts),
        "sources":            all_reports,
        "upcoming_by_league": dict(sorted(league_counts.items(), key=lambda x: -x[1])),
        "upcoming_by_source": dict(source_counts),
    }

    import_report_path = PATHS["logs_dir"] / "import_report.json"
    try:
        import_report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(import_report_path, "w") as f:
            json.dump(import_report, f, indent=2, default=str)
    except Exception as e:
        log.warning(f"Could not save import report: {e}")

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("\n" + "=" * 60)
    log.info("Step 1 Complete")
    log.info(f"  History:  {existing_history} → {final_history} (+{final_history - existing_history})")
    log.info(f"  Upcoming: {final_upcoming} fixtures across {len(league_counts)} leagues")
    log.info("  By league:")
    for lg, cnt in sorted(league_counts.items(), key=lambda x: -x[1])[:15]:
        log.info(f"    {lg}: {cnt}")
    log.info("  By source:")
    for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
        log.info(f"    {src}: {cnt}")
    log.info("=" * 60)

    if final_upcoming == 0:
        log.warning(
            "⚠ No upcoming fixtures found after running all sources.\n"
            "  This may be normal during an international break or off-season.\n"
            "  All sources were tried. Check logs above for individual errors."
        )

    return {
        "existing":  existing_history,
        "total":     final_history,
        "upcoming":  final_upcoming,
        "sources":   all_reports,
        "report":    import_report,
    }


if __name__ == "__main__":
    run()
