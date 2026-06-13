"""
pipeline/step4_evaluate_results.py
Scores yesterday's predictions against actual match results.
Updates data/accuracy/results.json with running accuracy stats.
This feeds the self-calibration system and the public accuracy page.

No API calls — reads from match history and prediction files.
"""

import logging
import time
from datetime import date, timedelta
from pipeline.data_store import (
    get_predictions, get_match_history,
    get_accuracy_data, save_accuracy_data,
    get_all_prediction_dates
)

log = logging.getLogger(__name__)

MAX_RECENT_RESULTS = 100   # Keep last 100 evaluated predictions for display


def run():
    start = time.time()
    log.info("Step 4: Evaluate prediction results")

    history = get_match_history()
    matches_by_teams = _index_matches_by_teams(history.get("matches", {}))

    accuracy = get_accuracy_data()

    # Evaluate all un-scored prediction dates (yesterday and earlier)
    evaluated_total = 0
    already_scored = {r["fixture_id"] for r in accuracy.get("recent_results", [])}

    # Check last 14 days of predictions
    for days_ago in range(1, 15):
        pred_date = date.today() - timedelta(days=days_ago)
        pred_data = get_predictions(pred_date)
        fixtures = pred_data.get("fixtures", [])
        if not fixtures:
            continue

        for fixture in fixtures:
            fid = fixture.get("id")
            if fid in already_scored:
                continue

            # Find actual match result
            actual = _find_actual_result(fixture, matches_by_teams)
            if not actual:
                continue  # Match not yet in history

            # Score this prediction
            scored = _score_prediction(fixture, actual)
            if scored:
                _update_accuracy(accuracy, scored)
                evaluated_total += 1

    save_accuracy_data(accuracy)

    elapsed = round(time.time() - start, 1)
    log.info(f"Step 4 complete in {elapsed}s: {evaluated_total} predictions evaluated")
    return {"evaluated": evaluated_total}


def _index_matches_by_teams(matches: dict) -> dict:
    """
    Build lookup: (home_team_id, away_team_id) → match record.
    Makes finding actual results O(1) instead of O(n).
    """
    idx = {}
    for match in matches.values():
        key = (match.get("home_team_id"), match.get("away_team_id"))
        # Keep most recent if duplicates
        if key not in idx or match.get("match_date", "") > idx[key].get("match_date", ""):
            idx[key] = match
    return idx


def _find_actual_result(fixture: dict, matches_by_teams: dict) -> dict | None:
    """Find the actual match result for a given fixture."""
    home_id = fixture.get("home_team_id")
    away_id = fixture.get("away_team_id")
    key = (home_id, away_id)
    match = matches_by_teams.get(key)
    if not match:
        return None
    # Verify it's roughly the right date (within 3 days)
    fixture_date = fixture.get("fixture_date", "")[:10]
    match_date = match.get("match_date", "")[:10]
    if abs((date.fromisoformat(fixture_date) - date.fromisoformat(match_date)).days) > 3:
        return None
    return match


def _score_prediction(fixture: dict, actual: dict) -> dict | None:
    """
    Compare prediction vs actual result.
    Returns scored record or None if no predictions were made.
    """
    predictions = fixture.get("predictions", {})
    if not predictions:
        return None

    hg = actual.get("home_goals", 0) or 0
    ag = actual.get("away_goals", 0) or 0
    total_goals = hg + ag
    total_corners = (actual.get("home_corners") or 0) + (actual.get("away_corners") or 0)
    total_cards = (
        (actual.get("home_yellow_cards") or 0) +
        (actual.get("away_yellow_cards") or 0) +
        (actual.get("home_red_cards") or 0) +
        (actual.get("away_red_cards") or 0)
    )

    # Actual outcomes
    if hg > ag:
        actual_winner = "home"
    elif ag > hg:
        actual_winner = "away"
    else:
        actual_winner = "draw"

    def check(pred_dict: dict, actual_val: bool) -> bool | None:
        """Returns True/False/None (None = no pick was made)."""
        pick = pred_dict.get("pick")
        conf = pred_dict.get("confidence")
        if pick == "no_pick" or pick is None or conf is None:
            return None
        return actual_val

    scored = {
        "fixture_id": fixture.get("id"),
        "fixture_date": fixture.get("fixture_date", "")[:10],
        "home_team": fixture.get("home_team_name"),
        "away_team": fixture.get("away_team_name"),
        "league": fixture.get("league_name"),
        "actual_score": f"{hg}-{ag}",
        "results": {}
    }

    # Score each market
    pred_winner = predictions.get("winner", {})
    winner_correct = check(pred_winner, pred_winner.get("pick") == actual_winner)

    pred_o25 = predictions.get("over25", {})
    o25_correct = check(pred_o25, (pred_o25.get("pick") == "over") == (total_goals > 2.5))

    pred_btts = predictions.get("btts", {})
    btts_actual = hg > 0 and ag > 0
    btts_correct = check(pred_btts, (pred_btts.get("pick") == "yes") == btts_actual)

    pred_c85 = predictions.get("corners_85", {})
    if total_corners > 0:
        c85_correct = check(pred_c85, (pred_c85.get("pick") == "over") == (total_corners > 8.5))
    else:
        c85_correct = None

    pred_cards = predictions.get("cards_35", {})
    if total_cards > 0:
        cards_correct = check(pred_cards, (pred_cards.get("pick") == "over") == (total_cards > 3.5))
    else:
        cards_correct = None

    scored["results"] = {
        "winner":  {"pick": pred_winner.get("pick"),  "confidence": pred_winner.get("confidence"),  "correct": winner_correct,  "actual": actual_winner},
        "over25":  {"pick": pred_o25.get("pick"),     "confidence": pred_o25.get("confidence"),     "correct": o25_correct,     "actual": "over" if total_goals > 2.5 else "under"},
        "btts":    {"pick": pred_btts.get("pick"),    "confidence": pred_btts.get("confidence"),    "correct": btts_correct,    "actual": "yes" if btts_actual else "no"},
        "corners": {"pick": pred_c85.get("pick"),     "confidence": pred_c85.get("confidence"),     "correct": c85_correct,     "actual": "over" if total_corners > 8.5 else "under"},
        "cards":   {"pick": pred_cards.get("pick"),   "confidence": pred_cards.get("confidence"),   "correct": cards_correct,   "actual": "over" if total_cards > 3.5 else "under"},
    }

    # Check if at least one market was scored
    any_scored = any(v["correct"] is not None for v in scored["results"].values())
    if not any_scored:
        return None

    return scored


def _update_accuracy(accuracy: dict, scored: dict):
    """Update running accuracy counters with a newly scored prediction."""
    by_market = accuracy.setdefault("by_market", {})
    calibration = accuracy.setdefault("calibration", {})
    recent = accuracy.setdefault("recent_results", [])

    for market, result in scored["results"].items():
        correct = result.get("correct")
        confidence = result.get("confidence")

        if correct is None:
            continue  # No pick was made for this market

        # Update overall market counters
        if market not in by_market:
            by_market[market] = {"total": 0, "correct": 0}
        by_market[market]["total"] += 1
        if correct:
            by_market[market]["correct"] += 1

        # Update calibration buckets
        if confidence is not None:
            bucket = int(confidence // 5) * 5   # Round down to nearest 5
            cal_key = f"{market}_{bucket}"
            if cal_key not in calibration:
                calibration[cal_key] = {"market": market, "bucket": bucket, "total": 0, "correct": 0}
            calibration[cal_key]["total"] += 1
            if correct:
                calibration[cal_key]["correct"] += 1

    accuracy["total_evaluated"] = accuracy.get("total_evaluated", 0) + 1

    # Add to recent results (newest first)
    recent.insert(0, scored)
    if len(recent) > MAX_RECENT_RESULTS:
        recent.pop()


if __name__ == "__main__":
    run()
