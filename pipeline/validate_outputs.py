"""
pipeline/validate_outputs.py
Runs after step3. Validates JSON outputs before git commit.
Exits with code 1 on CRITICAL failures (blocks commit).
Exits with code 0 on warnings (allows commit but logs issues).

Called from GitHub Actions after step3:
  python -m pipeline.validate_outputs
"""

import json
import sys
import logging
from pathlib import Path
from collections import Counter

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

CRITICAL = []
WARNINGS = []


def check(condition: bool, level: str, message: str):
    if not condition:
        if level == "CRITICAL":
            CRITICAL.append(message)
            log.error(f"CRITICAL: {message}")
        else:
            WARNINGS.append(message)
            log.warning(f"WARNING: {message}")
    else:
        log.info(f"  OK: {message}")


def load(path: Path, default=None):
    try:
        if path.exists() and path.stat().st_size > 2:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        CRITICAL.append(f"{path.name} is unreadable: {e}")
        log.error(f"CRITICAL: {path.name} unreadable — {e}")
    return default


def validate():
    log.info("=" * 50)
    log.info("Validating pipeline outputs...")
    log.info("=" * 50)

    # ── upcoming.json ─────────────────────────────────────────────────────────
    u = load(DATA / "fixtures" / "upcoming.json", {"fixtures": []})
    fx = u.get("fixtures", [])
    check(len(fx) > 0, "CRITICAL", f"upcoming.json has {len(fx)} fixtures (need > 0)")

    if len(fx) > 0:
        leagues = Counter(f.get("league_name", "?") for f in fx)
        log.info(f"  Leagues in upcoming ({len(leagues)} total):")
        for l, c in leagues.most_common(10):
            log.info(f"    {l}: {c}")

        sources = Counter(f.get("data_source", "?") for f in fx)
        log.info(f"  Sources: {dict(sources)}")

        # Warn if very few leagues
        check(len(leagues) >= 3, "WARNING",
              f"Only {len(leagues)} league(s) in upcoming — check source availability")

    # ── predictions/latest.json ───────────────────────────────────────────────
    p = load(DATA / "predictions" / "latest.json", {"fixtures": []})
    pf = p.get("fixtures", [])

    check(len(pf) > 0, "CRITICAL", f"latest.json has {len(pf)} fixtures")

    if len(pf) > 0:
        predicted    = [f for f in pf if not f.get("no_prediction_reason")]
        no_pred      = [f for f in pf if f.get("no_prediction_reason")]
        check(
            len(predicted) > 0,
            "WARNING",
            f"{len(pf)} fixtures but 0 predictions made — team stats may be broken"
        )
        log.info(f"  Predictions: {len(predicted)} made, {len(no_pred)} skipped")

        # Check predictions have expected keys
        if predicted:
            sample = predicted[0].get("predictions", {})
            for market in ("winner", "over25", "btts"):
                check(market in sample, "WARNING", f"Prediction missing '{market}' market")

    # ── teams/statistics.json ─────────────────────────────────────────────────
    ts = load(DATA / "teams" / "statistics.json", {"teams": {}})
    teams = ts.get("teams", {})

    check(len(teams) > 0, "WARNING", f"statistics.json has {len(teams)} teams")

    if teams:
        null_elo  = sum(1 for t in teams.values() if t.get("elo_rating") is None)
        null_home = sum(1 for t in teams.values() if t.get("home_matches_played") is None)
        check(
            null_elo == 0,
            "WARNING",
            f"{null_elo}/{len(teams)} teams have null elo_rating — step2 Elo merge may have failed"
        )
        check(
            null_home == 0,
            "WARNING",
            f"{null_home}/{len(teams)} teams have null home_matches_played — step2 may have failed"
        )
        log.info(f"  Teams: {len(teams)}, elo_null={null_elo}, home_null={null_home}")

    # ── leagues/baselines.json ────────────────────────────────────────────────
    lb = load(DATA / "leagues" / "baselines.json", {"leagues": {}})
    leagues = lb.get("leagues", {})
    check(len(leagues) > 0, "WARNING", f"baselines.json has {len(leagues)} leagues")

    # ── matches/history.json ──────────────────────────────────────────────────
    h = load(DATA / "matches" / "history.json", {"matches": {}})
    matches = h.get("matches", {})
    check(len(matches) >= 100, "WARNING",
          f"history.json has only {len(matches)} matches — predictions may be unreliable")
    log.info(f"  History: {len(matches)} matches")

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("=" * 50)
    if CRITICAL:
        log.error(f"VALIDATION FAILED: {len(CRITICAL)} critical error(s)")
        for e in CRITICAL:
            log.error(f"  ✗ {e}")
        sys.exit(1)

    if WARNINGS:
        log.warning(f"Validation passed with {len(WARNINGS)} warning(s):")
        for w in WARNINGS:
            log.warning(f"  ⚠ {w}")
    else:
        log.info("All checks passed ✓")

    sys.exit(0)


if __name__ == "__main__":
    validate()
