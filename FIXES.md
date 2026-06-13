# Fixes Applied — June 2026

## Critical Fixes

### 1. Elo Rating Merge Bug (step2_calculate_stats.py)
**What was broken:** The original code had a Python ternary expression that evaluated
`team_stats[str(team_id)].update(elo_data)` inside a conditional, but the outer `if`
used the raw key while the inner used `str(key)`. The result was that no Elo data was
ever merged — all teams had `elo_rating: null` in statistics.json.

**Fix:** Replaced with a clean, explicit merge loop:
```python
for team_id, elo_data in elo_ratings.items():
    tid = str(team_id)
    if tid in team_stats:
        team_stats[tid].update(elo_data)
```

### 2. CURRENT_SEASON Hardcoded to 2025 (config.py + daily_pipeline.yml)
**What was broken:** Year-round leagues (Finnish Veikkausliiga, Norwegian Eliteserien,
Swedish Allsvenskan, J1 League, etc.) are in their **2026** season in June 2026.
All season-based API calls were fetching the wrong season.

**Fix:** config.py now auto-detects season from the current date:
```python
_auto_season = _today.year if _today.month >= 6 else _today.year - 1
CURRENT_SEASON = int(os.environ.get("CURRENT_SEASON", str(_auto_season)))
```
The workflow no longer hardcodes `CURRENT_SEASON: "2025"` — it passes an empty
string, letting config.py auto-detect.

### 3. apply_updates.yml Deleted
**What was broken:** An 86 KB workflow file containing the entire Python pipeline
encoded as base64 strings. It was a security risk (impossible to code-review),
a maintenance trap (diverged from actual pipeline/ files), and could silently
overwrite fixed code on the next manual trigger.

**Fix:** Deleted. Code changes belong in pull requests.

### 4. vercel.json outputDirectory
**What was broken:** `"outputDirectory": "dist"` but Vite outputs to `frontend/dist`.
This would cause a blank Vercel deployment.

**Fix:** `"outputDirectory": "frontend/dist"`

## High Priority Fixes

### 5. Copa Sudamericana Added to FD_COMPETITIONS
**What was added:** Copa Sudamericana (code "CSA", league_id 11) added as always-active.
Runs Feb–Nov. Provides additional year-round South American fixtures.

### 6. Deduplication Logic Added (step1)
**What was added:** `deduplicate_upcoming()` removes fixtures where the same match
appears from multiple sources. Prefers api-sports > football_data > openligadb.
Previously the same match could appear 2-3 times in upcoming.json.

### 7. Nordic Leagues Added to ACTIVE_LEAGUES Config
**What was added:** Eliteserien (Norway) and Allsvenskan (Sweden) added to config.py
ACTIVE_LEAGUES with `year_round: True`. They were in APISPORTS_BACKFILL but not in
ACTIVE_LEAGUES, causing them to be fetched for backfill but not consistently tracked.

### 8. Referee Statistics Built from History (step2)
**What was added:** `_calculate_referee_stats()` in step2 builds referee profiles
from the match history data — no extra API calls. Uses referee_name fields already
present in history records. Profiles saved to referees/profiles.json.

### 9. Rest Days Calculated (step2)
**What was added:** `rest_days` field computed for each team from match_date fields
in history. Used in predictions for fatigue adjustments.

### 10. validate_outputs.py
**What was added:** New validation script that runs after step3. Checks:
- upcoming.json has > 0 fixtures
- latest.json has predictions
- statistics.json has non-null Elo ratings
- history.json has sufficient matches
Exits with code 1 on critical failures, blocking the git commit.

### 11. Failure Alerting in GitHub Actions
**What was added:** `Create failure issue` step using github-script. Opens a GitHub
Issue when the pipeline fails, labelled `pipeline-failure`. De-duplicates so only
one issue per day is created.

### 12. Concurrency Guard in GitHub Actions
**What was added:** `concurrency: group: pipeline` prevents two pipeline runs from
overlapping and corrupting JSON data files.

## How to Complete the Fix

The code changes above are complete. The one remaining action is entirely in
your GitHub repository settings — **no code changes needed**.

### Required: Set FOOTBALL_API_KEY in GitHub Secrets

See README_SETUP.md for step-by-step instructions.

Without this key, the pipeline will only have:
- football-data.org coverage (Brazil + Copa Libertadores in June/July)
- OpenLigaDB coverage (Bundesliga — summer break until August)

With this key, you get 80+ leagues worldwide every day.
