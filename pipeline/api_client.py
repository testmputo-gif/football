"""
pipeline/api_client.py
Football data API client.
Rate limit tracking stored in data/logs/api_usage.json
— no database needed.
"""

import httpx
import asyncio
import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Optional
from pipeline.config import (
    FOOTBALL_API_KEY, FOOTBALL_API_BASE_URL, FOOTBALL_API_HOST,
    FOOTBALL_API_DAILY_LIMIT, FOOTBALL_API_SAFETY_BUFFER,
    FOOTBALL_DATA_API_KEY, FOOTBALL_DATA_BASE_URL, PATHS
)

log = logging.getLogger(__name__)

# API usage tracked in a simple JSON file
API_USAGE_FILE = PATHS["logs_dir"] / "api_usage.json"


class RateLimitExceeded(Exception):
    pass


def _get_usage_today() -> int:
    """Read today's API call count from file."""
    today = date.today().isoformat()
    try:
        if API_USAGE_FILE.exists():
            data = json.loads(API_USAGE_FILE.read_text())
            return data.get(today, {}).get("calls", 0)
    except Exception:
        pass
    return 0


def _record_call(endpoint: str):
    """Increment today's API call count."""
    today = date.today().isoformat()
    data = {}
    try:
        if API_USAGE_FILE.exists():
            data = json.loads(API_USAGE_FILE.read_text())
    except Exception:
        pass

    if today not in data:
        data[today] = {"calls": 0, "endpoints": []}

    data[today]["calls"] += 1
    data[today]["endpoints"].append(endpoint)

    # Keep only last 7 days
    keys = sorted(data.keys())
    if len(keys) > 7:
        for old_key in keys[:-7]:
            del data[old_key]

    API_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    API_USAGE_FILE.write_text(json.dumps(data, indent=2))


def get_calls_remaining() -> int:
    used = _get_usage_today()
    return max(0, FOOTBALL_API_DAILY_LIMIT - used)


class ApiFootballClient:
    """
    Primary: api-football.com via RapidAPI
    Free: 100 requests/day
    """
    HEADERS = {
        "X-RapidAPI-Key": FOOTBALL_API_KEY,
        "X-RapidAPI-Host": FOOTBALL_API_HOST,
    }

    def _check_limit(self):
        used = _get_usage_today()
        if used >= (FOOTBALL_API_DAILY_LIMIT - FOOTBALL_API_SAFETY_BUFFER):
            raise RateLimitExceeded(
                f"Daily limit approached: {used}/{FOOTBALL_API_DAILY_LIMIT} used. "
                f"Stopping to preserve {FOOTBALL_API_SAFETY_BUFFER} buffer."
            )

    def get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Synchronous GET — pipeline runs sync, not async."""
        self._check_limit()
        url = f"{FOOTBALL_API_BASE_URL}/{endpoint}"
        try:
            response = httpx.get(
                url,
                headers=self.HEADERS,
                params=params or {},
                timeout=30.0
            )
            response.raise_for_status()
            _record_call(endpoint)
            data = response.json()
            if data.get("errors"):
                log.error(f"API error on {endpoint}: {data['errors']}")
                return None
            remaining = data.get("response", [])
            log.info(f"API {endpoint}: {len(remaining)} results ({_get_usage_today()}/{FOOTBALL_API_DAILY_LIMIT} calls used)")
            return data
        except RateLimitExceeded:
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                log.error("HTTP 429 — hard rate limit hit")
            else:
                log.error(f"HTTP {e.response.status_code} on {endpoint}")
            return None
        except Exception as e:
            log.error(f"Request failed for {endpoint}: {e}")
            return None

    def get_fixtures(self, league_id: int, season: int, next_n: int = None, status: str = None) -> list:
        params = {"league": league_id, "season": season}
        if next_n:
            params["next"] = next_n
        if status:
            params["status"] = status
        data = self.get("fixtures", params)
        return data.get("response", []) if data else []

    def get_fixture_statistics(self, fixture_id: int) -> list:
        data = self.get("fixtures/statistics", {"fixture": fixture_id})
        return data.get("response", []) if data else []

    def get_h2h(self, team1_id: int, team2_id: int, last: int = 10) -> list:
        data = self.get("fixtures/headtohead", {
            "h2h": f"{team1_id}-{team2_id}", "last": last
        })
        return data.get("response", []) if data else []

    def get_teams(self, league_id: int, season: int) -> list:
        data = self.get("teams", {"league": league_id, "season": season})
        return data.get("response", []) if data else []


class FootballDataClient:
    """
    Secondary: football-data.org
    Free: 10 req/min, no daily cap, 12 competitions
    """
    HEADERS = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    LEAGUE_MAP = {
        39: "PL", 78: "BL1", 140: "PD", 135: "SA", 61: "FL1"
    }

    def get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        url = f"{FOOTBALL_DATA_BASE_URL}/{endpoint}"
        try:
            response = httpx.get(url, headers=self.HEADERS, params=params or {}, timeout=30.0)
            if response.status_code == 429:
                log.warning("football-data.org rate limited — waiting 65s")
                time.sleep(65)
                response = httpx.get(url, headers=self.HEADERS, params=params or {}, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error(f"football-data.org failed for {endpoint}: {e}")
            return None

    def get_matches(self, league_api_id: int, date_from: str, date_to: str) -> list:
        comp = self.LEAGUE_MAP.get(league_api_id)
        if not comp:
            return []
        data = self.get(f"competitions/{comp}/matches", {"dateFrom": date_from, "dateTo": date_to})
        return data.get("matches", []) if data else []


# Singleton instances
primary_api = ApiFootballClient()
secondary_api = FootballDataClient()
