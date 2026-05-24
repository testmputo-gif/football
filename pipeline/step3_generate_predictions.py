"""
pipeline/step3_generate_predictions.py
The prediction engine. Reads all statistics from JSON files,
runs Dixon-Coles Poisson + ML ensemble, writes predictions JSON.

No API calls. Pure computation.
Output: data/predictions/YYYY-MM-DD.json + latest.json
"""

import logging
import math
import time
import joblib
import numpy as np
from datetime import date, datetime
from pathlib import Path
from scipy.stats import poisson
from pipeline.config import (
    PATHS, MODEL_VERSION, MIN_MATCHES_FOR_PREDICTION,
    MIN_HOME_AWAY_MATCHES, WINNER_GATE_MARGIN,
    CONFIDENCE_CAPS, CONFIDENCE_FLOORS
)
from pipeline.data_store import (
    get_upcoming_fixtures, get_team_statistics,
    get_league_baselines, get_h2h_data, get_referee_data,
    get_model_meta, save_predictions
)

log = logging.getLogger(__name__)

# Dixon-Coles rho correction parameter (empirically fitted)
DC_RHO = -0.13
MAX_GOALS = 6   # Model 0-6 goals per team (covers 99.9%+ of outcomes)


# ── Dixon-Coles Core ──────────────────────────────────────────────────────────

def dc_correction(i: int, j: int, xg_home: float, xg_away: float) -> float:
    """
    Dixon-Coles low-score correction factor.
    Fixes Poisson underestimation of 0-0 and 1-1 draws.
    Only applied when total goals <= 1.
    """
    if i == 0 and j == 0:
        return 1 - (xg_home * xg_away * DC_RHO)
    elif i == 0 and j == 1:
        return 1 + (xg_home * DC_RHO)
    elif i == 1 and j == 0:
        return 1 + (xg_away * DC_RHO)
    elif i == 1 and j == 1:
        return 1 - DC_RHO
    return 1.0


def build_score_matrix(xg_home: float, xg_away: float) -> np.ndarray:
    """
    Build 7x7 scoreline probability matrix using Dixon-Coles Poisson.
    matrix[i][j] = P(home scores i, away scores j)
    """
    matrix = np.zeros((MAX_GOALS + 1, MAX_GOALS + 1))
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p_home = poisson.pmf(i, xg_home)
            p_away = poisson.pmf(j, xg_away)
            tau = dc_correction(i, j, xg_home, xg_away)
            matrix[i][j] = p_home * p_away * tau
    # Normalize — DC correction shifts total slightly off 1.0
    total = matrix.sum()
    if total > 0:
        matrix = matrix / total
    return matrix


def derive_markets(matrix: np.ndarray) -> dict:
    """Derive all prediction markets from the score matrix."""
    # Match result
    home_win = float(np.sum(np.tril(matrix, -1)))   # i > j
    away_win = float(np.sum(np.triu(matrix, 1)))    # j > i
    draw     = float(np.trace(matrix))              # i == j

    # Goals markets — sum cells where total goals meets threshold
    def p_over(n: float) -> float:
        return float(sum(
            matrix[i][j]
            for i in range(MAX_GOALS + 1)
            for j in range(MAX_GOALS + 1)
            if i + j > n
        ))

    over15 = p_over(1.5)
    over25 = p_over(2.5)
    over35 = p_over(3.5)

    # BTTS — both teams score at least 1
    btts = float(1.0
        - np.sum(matrix[0, :])    # P(home scores 0)
        - np.sum(matrix[:, 0])    # P(away scores 0)
        + matrix[0][0]            # Add back the double-counted 0-0
    )

    # Most likely scoreline
    idx = np.unravel_index(np.argmax(matrix), matrix.shape)
    most_likely = f"{idx[0]}-{idx[1]}"
    most_likely_prob = float(matrix[idx])

    return {
        "home_win": round(home_win, 5),
        "draw": round(draw, 5),
        "away_win": round(away_win, 5),
        "over15": round(over15, 5),
        "over25": round(over25, 5),
        "over35": round(over35, 5),
        "btts": round(btts, 5),
        "most_likely_score": most_likely,
        "most_likely_score_prob": round(most_likely_prob, 5),
    }


def predict_corners(home_avg_for: float, home_avg_against: float,
                    away_avg_for: float, away_avg_against: float,
                    league_avg: float = 10.0) -> dict:
    """Poisson model for corners market."""
    exp_home = (home_avg_for * away_avg_against) / league_avg * 1.05
    exp_away = (away_avg_for * home_avg_against) / league_avg * 0.95
    total = max(4.0, min(exp_home + exp_away, 18.0))
    return {
        "expected_corners": round(total, 2),
        "over85": round(1.0 - float(poisson.cdf(8, total)), 5),
        "over95": round(1.0 - float(poisson.cdf(9, total)), 5),
    }


def predict_cards(home_avg_yellow: float, away_avg_yellow: float,
                  referee_avg: float = None, league_avg: float = 3.5,
                  is_derby: bool = False) -> dict:
    """Cards market with referee adjustment."""
    base = home_avg_yellow + away_avg_yellow
    if referee_avg is not None and league_avg > 0:
        ref_factor = referee_avg / (league_avg * 0.8)
        base *= max(0.7, min(ref_factor, 1.5))
    if is_derby:
        base *= 1.25
    expected = max(1.0, min(base, 8.0))
    red_prob = max(0.05, min(0.15 * (expected / 3.5), 0.60))
    return {
        "expected_cards": round(expected, 2),
        "over35": round(1.0 - float(poisson.cdf(3, expected)), 5),
        "red_card_probability": round(red_prob, 4),
    }


def predict_first_half(xg_home: float, xg_away: float) -> dict:
    """First half markets — ~42% of goals occur before 45'."""
    fh = 0.42
    xgh = xg_home * fh
    xga = xg_away * fh
    over05 = 1.0 - float(poisson.pmf(0, xgh) * poisson.pmf(0, xga))
    btts_fh = (1 - float(poisson.pmf(0, xgh))) * (1 - float(poisson.pmf(0, xga)))
    return {
        "fh_over05": round(over05, 5),
        "fh_btts": round(btts_fh, 5),
    }


# ── ML Model Loading ──────────────────────────────────────────────────────────

_ml_models = {}

def _load_ml_models() -> bool:
    """Load trained ML models from disk. Returns True if available."""
    global _ml_models
    models_dir = PATHS["models_dir"]
    model_files = {
        "winner":  models_dir / "winner_model.joblib",
        "goals":   models_dir / "goals_model.joblib",
        "btts":    models_dir / "btts_model.joblib",
        "corners": models_dir / "corners_model.joblib",
        "cards":   models_dir / "cards_model.joblib",
    }
    loaded = 0
    for name, path in model_files.items():
        if path.exists():
            try:
                _ml_models[name] = joblib.load(path)
                loaded += 1
            except Exception as e:
                log.warning(f"Could not load {name} model: {e}")

    if loaded > 0:
        log.info(f"Loaded {loaded}/{len(model_files)} ML models")
        return True
    log.info("No ML models available — using Dixon-Coles only (normal for first run)")
    return False


def _build_feature_vector(
    poisson_markets: dict,
    home_stats: dict, away_stats: dict,
    league: dict, h2h: dict,
    referee: dict,
    days_rest_home: int = 7, days_rest_away: int = 7,
) -> np.ndarray:
    """Build feature vector for ML models."""
    elo_home = home_stats.get("elo_rating", 1500.0)
    elo_away = away_stats.get("elo_rating", 1500.0)
    elo_diff = elo_home - elo_away
    elo_exp_home = 1.0 / (1.0 + 10 ** (-elo_diff / 400.0))

    h2h_n = h2h.get("matches_played", 0)

    return np.array([
        # Poisson base
        poisson_markets.get("home_win", 0.33),
        poisson_markets.get("draw", 0.33),
        poisson_markets.get("away_win", 0.33),
        poisson_markets.get("over25", 0.5),
        poisson_markets.get("btts", 0.5),
        poisson_markets.get("xg_home", 1.2),
        poisson_markets.get("xg_away", 1.0),
        poisson_markets.get("xg_diff", 0.2),

        # Elo
        elo_home, elo_away, elo_diff, elo_exp_home,

        # Home team stats
        home_stats.get("home_avg_goals_scored", 1.2),
        home_stats.get("home_avg_goals_conceded", 1.0),
        home_stats.get("home_attack_strength", 1.0),
        home_stats.get("home_defense_strength", 1.0),
        home_stats.get("home_avg_corners", 5.0),
        home_stats.get("home_avg_yellow_cards", 1.5),
        home_stats.get("home_matches_played", 0),
        home_stats.get("home_wins", 0) / max(home_stats.get("home_matches_played", 1), 1),
        home_stats.get("home_clean_sheet_rate", 0.3),
        home_stats.get("home_form_score", 0.5),
        home_stats.get("goals_momentum", 1.0),

        # Away team stats
        away_stats.get("away_avg_goals_scored", 1.0),
        away_stats.get("away_avg_goals_conceded", 1.2),
        away_stats.get("away_attack_strength", 1.0),
        away_stats.get("away_defense_strength", 1.0),
        away_stats.get("away_avg_corners", 4.5),
        away_stats.get("away_avg_yellow_cards", 1.5),
        away_stats.get("away_matches_played", 0),
        away_stats.get("away_wins", 0) / max(away_stats.get("away_matches_played", 1), 1),
        away_stats.get("away_clean_sheet_rate", 0.3),
        away_stats.get("away_form_score", 0.5),

        # Market rates
        home_stats.get("btts_percentage", 0.5),
        away_stats.get("btts_percentage", 0.5),
        home_stats.get("over25_percentage", 0.5),
        away_stats.get("over25_percentage", 0.5),

        # H2H
        h2h.get("home_wins", 0) / max(h2h_n, 1),
        h2h.get("draws", 0) / max(h2h_n, 1),
        h2h.get("away_wins", 0) / max(h2h_n, 1),
        h2h.get("avg_goals", 2.5),
        h2h.get("btts_rate", 0.5),
        float(h2h_n),

        # Referee
        referee.get("avg_yellow_cards", 3.5),
        referee.get("avg_red_cards", 0.15),
        float(referee.get("matches_officiated", 0) >= 5),

        # Context
        float(days_rest_home), float(days_rest_away),
        league.get("home_win_rate", 0.46),
        league.get("avg_goals_total", 2.6),
        league.get("avg_corners", 10.0),
        league.get("avg_cards", 3.5),
    ], dtype=np.float32)


# ── Confidence Scoring ────────────────────────────────────────────────────────

def compute_confidence(
    raw_probability: float,
    market: str,
    sample_size: int,
    stat_gap: float,
    data_freshness: float = 1.0,
    calibration_factor: float = 1.0,
) -> float:
    """
    Convert raw probability to calibrated confidence score 0-100.

    Components:
      sample_size_factor:  scales 0-1 based on matches available
      consistency_factor:  how close raw_probability is to certainty
      gap_factor:          gap between top and second outcome
      freshness_factor:    penalize stale data
    """
    # Sample size factor: 8 matches = 0.5, 20+ = 1.0
    sample_factor = min(1.0, sample_size / 20.0)

    # Probability distance from 50/50
    distance_from_random = abs(raw_probability - 0.5) * 2  # 0-1

    # Base confidence
    base = (
        raw_probability * 0.40 +       # Raw probability weight
        distance_from_random * 0.30 +  # How far from coin flip
        stat_gap * 0.20 +              # Statistical gap
        sample_factor * 0.10           # Data adequacy
    )

    # Scale to 0-100
    confidence = base * 100

    # Apply freshness penalty
    confidence *= data_freshness

    # Apply calibration factor from historical accuracy
    confidence *= calibration_factor

    # Apply per-market cap
    cap = CONFIDENCE_CAPS.get(market, 80.0)
    confidence = min(confidence, cap)

    return round(max(0.0, confidence), 1)


def make_pick(probability: float, market: str, sample_size: int,
              stat_gap: float, calibration_factor: float = 1.0) -> tuple:
    """
    Convert probability to (pick, confidence).
    Returns (None, None) if confidence below floor.
    """
    confidence = compute_confidence(
        probability, market, sample_size, stat_gap,
        calibration_factor=calibration_factor
    )
    floor = CONFIDENCE_FLOORS.get(market, 52.0)
    if confidence < floor:
        return "no_pick", None
    return None, confidence  # caller sets actual pick string


# ── Reasoning Generator ───────────────────────────────────────────────────────

def generate_reasoning(fixture: dict, home_stats: dict, away_stats: dict,
                        markets: dict, poisson: dict, league: dict) -> dict:
    """Generate plain-English reasoning for each market."""
    ht = fixture.get("home_team_name", "Home")
    at = fixture.get("away_team_name", "Away")
    elo_diff = home_stats.get("elo_rating", 1500) - away_stats.get("elo_rating", 1500)
    xgh = poisson.get("xg_home", 0)
    xga = poisson.get("xg_away", 0)

    reasoning = {}

    # Winner
    hw = markets.get("home_win", 0.33)
    dw = markets.get("draw", 0.33)
    aw = markets.get("away_win", 0.33)
    top = max(hw, dw, aw)
    if top == hw:
        leader = f"{ht} win ({hw:.0%})"
    elif top == aw:
        leader = f"{at} win ({aw:.0%})"
    else:
        leader = f"Draw ({dw:.0%})"
    elo_txt = f"Elo gap of {abs(elo_diff):.0f} pts favours {'home' if elo_diff > 0 else 'away'}." if abs(elo_diff) > 30 else "Teams are closely matched on Elo."
    reasoning["winner"] = (
        f"Model favours {leader}. xG: {ht} {xgh:.2f} — {at} {xga:.2f}. "
        f"{elo_txt} "
        f"Home form: {home_stats.get('home_form_score', 0):.0%}, "
        f"Away form: {away_stats.get('away_form_score', 0):.0%}."
    )

    # Over 2.5
    total_xg = xgh + xga
    o25 = markets.get("over25", 0.5)
    reasoning["over25"] = (
        f"Combined xG {total_xg:.2f} goals expected. "
        f"Poisson model gives Over 2.5 a {o25:.0%} probability. "
        f"{ht} scores {home_stats.get('home_avg_goals_scored', 0):.1f}/game at home, "
        f"{at} concedes {away_stats.get('away_avg_goals_conceded', 0):.1f}/game away."
    )

    # BTTS
    btts_val = markets.get("btts", 0.5)
    home_score_rate = home_stats.get("home_scoring_rate", 0.7)
    away_score_rate = away_stats.get("away_scoring_rate", 0.6)
    reasoning["btts"] = (
        f"{ht} scored in {home_score_rate:.0%} of home games. "
        f"{at} scored in {away_score_rate:.0%} of away games. "
        f"BTTS probability: {btts_val:.0%}."
    )

    # Corners
    exp_c = markets.get("expected_corners", 10.0)
    reasoning["corners"] = (
        f"Expected {exp_c:.1f} total corners. "
        f"{ht} avg {home_stats.get('home_avg_corners', 5):.1f} at home, "
        f"{at} avg {away_stats.get('away_avg_corners', 4.5):.1f} away."
    )

    # Cards
    exp_cards = markets.get("expected_cards", 3.5)
    reasoning["cards"] = (
        f"Expected {exp_cards:.1f} total cards. "
        f"{ht} avg {home_stats.get('home_avg_yellow_cards', 1.5):.1f} yellows at home, "
        f"{at} avg {away_stats.get('away_avg_yellow_cards', 1.5):.1f} away."
    )

    return reasoning


# ── Main Orchestrator ─────────────────────────────────────────────────────────

def run():
    start = time.time()
    log.info("Step 3: Generate predictions")

    # Load all data
    upcoming = get_upcoming_fixtures()
    team_data = get_team_statistics()
    league_data = get_league_baselines()
    h2h_data = get_h2h_data()
    referee_data = get_referee_data()
    model_meta = get_model_meta()

    fixtures = upcoming.get("fixtures", [])
    team_stats = team_data.get("teams", {})
    league_baselines = league_data.get("leagues", {})
    h2h_records = h2h_data.get("records", {})
    referees = referee_data.get("referees", {})

    # Load ML models if available
    ml_available = _load_ml_models()

    log.info(f"Generating predictions for {len(fixtures)} fixtures")

    results = []
    skipped = 0
    predicted = 0

    for fixture in fixtures:
        try:
            pred = _predict_fixture(
                fixture, team_stats, league_baselines,
                h2h_records, referees, ml_available
            )
            results.append(pred)
            if pred.get("no_prediction_reason") is None:
                predicted += 1
            else:
                skipped += 1
        except Exception as e:
            log.error(f"Failed to predict {fixture.get('id', '?')}: {e}", exc_info=True)
            skipped += 1

    # Sort by fixture date
    results.sort(key=lambda x: x.get("fixture_date", ""))

    predictions_output = {
        "model_version": MODEL_VERSION,
        "ml_active": ml_available,
        "total_fixtures": len(fixtures),
        "predictions_made": predicted,
        "fixtures": results,
    }

    save_predictions(predictions_output)

    elapsed = round(time.time() - start, 1)
    log.info(f"Step 3 complete in {elapsed}s: {predicted} predictions, {skipped} skipped")
    return {"predicted": predicted, "skipped": skipped}


def _predict_fixture(
    fixture: dict, team_stats: dict, league_baselines: dict,
    h2h_records: dict, referees: dict, ml_available: bool
) -> dict:
    """Generate complete prediction for one fixture."""

    home_id = fixture.get("home_team_id")
    away_id = fixture.get("away_team_id")
    league_id = fixture.get("league_id")

    # Build base result with fixture info
    result = {**fixture}

    # ── Data sufficiency check ────────────────────────────────────────────────
    home_stats = team_stats.get(home_id, {})
    away_stats = team_stats.get(away_id, {})
    league = league_baselines.get(league_id, {})

    home_total = home_stats.get("total_matches_played", 0)
    away_total = away_stats.get("total_matches_played", 0)
    home_home = home_stats.get("home_matches_played", 0)
    away_away = away_stats.get("away_matches_played", 0)

    if home_total < MIN_MATCHES_FOR_PREDICTION:
        result["no_prediction_reason"] = f"Insufficient data: {fixture.get('home_team_name')} has only {home_total} matches (need {MIN_MATCHES_FOR_PREDICTION})"
        result["predictions"] = {}
        return result

    if away_total < MIN_MATCHES_FOR_PREDICTION:
        result["no_prediction_reason"] = f"Insufficient data: {fixture.get('away_team_name')} has only {away_total} matches (need {MIN_MATCHES_FOR_PREDICTION})"
        result["predictions"] = {}
        return result

    if home_home < MIN_HOME_AWAY_MATCHES or away_away < MIN_HOME_AWAY_MATCHES:
        result["no_prediction_reason"] = "Insufficient home/away specific data"
        result["predictions"] = {}
        return result

    if not league:
        result["no_prediction_reason"] = "League baseline data not yet available"
        result["predictions"] = {}
        return result

    # ── Dixon-Coles xG calculation ────────────────────────────────────────────
    la_home = league.get("avg_goals_home", 1.5)
    la_away = league.get("avg_goals_away", 1.1)
    ha_factor = league.get("home_advantage_factor", 1.20)

    # Apply injury/suspension adjustments from fixture notes
    home_adj = fixture.get("home_xg_adjustment", 1.0)
    away_adj = fixture.get("away_xg_adjustment", 1.0)

    xg_home = (
        home_stats.get("home_attack_strength", 1.0) *
        away_stats.get("away_defense_strength", 1.0) *
        la_home * ha_factor * home_adj
    )
    xg_away = (
        away_stats.get("away_attack_strength", 1.0) *
        home_stats.get("home_defense_strength", 1.0) *
        la_away * away_adj
    )

    # Clamp xG to realistic range
    xg_home = max(0.1, min(xg_home, 5.0))
    xg_away = max(0.1, min(xg_away, 5.0))

    # ── Build score matrix + derive markets ───────────────────────────────────
    matrix = build_score_matrix(xg_home, xg_away)
    poisson_markets = derive_markets(matrix)
    poisson_markets["xg_home"] = round(xg_home, 3)
    poisson_markets["xg_away"] = round(xg_away, 3)
    poisson_markets["xg_diff"] = round(xg_home - xg_away, 3)

    # ── Corners ───────────────────────────────────────────────────────────────
    corner_result = predict_corners(
        home_avg_for=home_stats.get("home_avg_corners", 5.0),
        home_avg_against=home_stats.get("away_avg_corners", 4.5),  # opponent corners against
        away_avg_for=away_stats.get("away_avg_corners", 4.5),
        away_avg_against=away_stats.get("home_avg_corners", 5.0),
        league_avg=league.get("avg_corners", 10.0),
    )

    # ── Cards ─────────────────────────────────────────────────────────────────
    ref_name = fixture.get("referee_name")
    ref_profile = referees.get(ref_name, {}) if ref_name else {}
    card_result = predict_cards(
        home_avg_yellow=home_stats.get("home_avg_yellow_cards", 1.5),
        away_avg_yellow=away_stats.get("away_avg_yellow_cards", 1.5),
        referee_avg=ref_profile.get("avg_yellow_cards") if ref_profile.get("matches_officiated", 0) >= 5 else None,
        league_avg=league.get("avg_cards", 3.5),
    )

    # ── First half ────────────────────────────────────────────────────────────
    fh_result = predict_first_half(xg_home, xg_away)

    # ── ML ensemble blend (if models available) ───────────────────────────────
    final_markets = dict(poisson_markets)

    if ml_available and _ml_models:
        try:
            h2h_key = f"{min(home_id, away_id)}_{max(home_id, away_id)}"
            h2h = h2h_records.get(h2h_key, {})
            features = _build_feature_vector(
                poisson_markets, home_stats, away_stats,
                league, h2h, ref_profile,
            )
            X = features.reshape(1, -1)

            # Winner model (60% Poisson + 40% ML)
            if "winner" in _ml_models:
                ml_probs = _ml_models["winner"].predict_proba(X)[0]
                classes = _ml_models["winner"].classes_
                ml_home = ml_probs[list(classes).index("home")] if "home" in classes else poisson_markets["home_win"]
                ml_draw = ml_probs[list(classes).index("draw")] if "draw" in classes else poisson_markets["draw"]
                ml_away = ml_probs[list(classes).index("away")] if "away" in classes else poisson_markets["away_win"]
                final_markets["home_win"] = round(0.60 * poisson_markets["home_win"] + 0.40 * ml_home, 5)
                final_markets["draw"]     = round(0.60 * poisson_markets["draw"]     + 0.40 * ml_draw, 5)
                final_markets["away_win"] = round(0.60 * poisson_markets["away_win"] + 0.40 * ml_away, 5)

            # Goals model
            if "goals" in _ml_models:
                ml_over25 = _ml_models["goals"].predict_proba(X)[0][1]
                final_markets["over25"] = round(0.50 * poisson_markets["over25"] + 0.50 * ml_over25, 5)

            # BTTS model
            if "btts" in _ml_models:
                ml_btts = _ml_models["btts"].predict_proba(X)[0][1]
                final_markets["btts"] = round(0.50 * poisson_markets["btts"] + 0.50 * ml_btts, 5)

        except Exception as e:
            log.warning(f"ML ensemble failed for {fixture.get('id', '?')}, using Poisson only: {e}")

    # ── Build prediction picks ────────────────────────────────────────────────
    sample = min(home_total, away_total)

    def gap(p1, p2, p3): return p1 - max(p2, p3)

    # Winner
    hw = final_markets["home_win"]
    dw = final_markets["draw"]
    aw = final_markets["away_win"]
    winner_gap = max(hw, dw, aw) - sorted([hw, dw, aw])[-2]
    if winner_gap < WINNER_GATE_MARGIN:
        winner_pick, winner_conf = "no_pick", None
    else:
        top_val = max(hw, dw, aw)
        pick_str = "home" if top_val == hw else ("draw" if top_val == dw else "away")
        winner_conf = compute_confidence(top_val, "winner", sample, winner_gap)
        winner_pick = pick_str if winner_conf >= CONFIDENCE_FLOORS["winner"] else "no_pick"
        if winner_pick == "no_pick": winner_conf = None

    def goals_pick(prob, market):
        conf = compute_confidence(prob, market, sample, abs(prob - 0.5) * 2)
        if conf < CONFIDENCE_FLOORS.get(market, 52.0):
            return "no_pick", None
        return ("over" if prob >= 0.5 else "under"), conf

    o15_pick, o15_conf = goals_pick(final_markets["over15"], "over15")
    o25_pick, o25_conf = goals_pick(final_markets["over25"], "over25")
    o35_pick, o35_conf = goals_pick(final_markets["over35"], "over35")
    btts_raw = final_markets["btts"]
    btts_conf = compute_confidence(btts_raw, "btts", sample, abs(btts_raw - 0.5) * 2)
    btts_pick = ("yes" if btts_raw >= 0.5 else "no") if btts_conf >= CONFIDENCE_FLOORS["btts"] else "no_pick"
    if btts_pick == "no_pick": btts_conf = None

    # Corners — only predict if enough data
    if home_stats.get("home_matches_played", 0) >= 6 and away_stats.get("away_matches_played", 0) >= 6:
        c85_prob = corner_result["over85"]
        c85_conf = compute_confidence(c85_prob, "corners", sample, abs(c85_prob - 0.5) * 2)
        c85_pick = ("over" if c85_prob >= 0.5 else "under") if c85_conf >= CONFIDENCE_FLOORS["corners"] else "no_pick"
        if c85_pick == "no_pick": c85_conf = None
        c95_prob = corner_result["over95"]
        c95_conf = compute_confidence(c95_prob, "corners", sample, abs(c95_prob - 0.5) * 2)
        c95_pick = ("over" if c95_prob >= 0.5 else "under") if c95_conf >= CONFIDENCE_FLOORS["corners"] else "no_pick"
        if c95_pick == "no_pick": c95_conf = None
    else:
        c85_pick = c95_pick = "no_pick"
        c85_conf = c95_conf = None

    # Cards — only predict when referee data available
    cards_prob = card_result["over35"]
    if ref_profile.get("matches_officiated", 0) >= 5:
        cards_conf = compute_confidence(cards_prob, "cards", sample, abs(cards_prob - 0.5) * 2)
        cards_pick = ("over" if cards_prob >= 0.5 else "under") if cards_conf >= CONFIDENCE_FLOORS["cards"] else "no_pick"
        if cards_pick == "no_pick": cards_conf = None
    else:
        cards_pick = "no_pick"
        cards_conf = None

    # First half
    fh_prob = fh_result["fh_over05"]
    fh_conf = compute_confidence(fh_prob, "fh_over05", sample, abs(fh_prob - 0.5) * 2)
    fh_pick = ("over" if fh_prob >= 0.5 else "under") if fh_conf >= CONFIDENCE_FLOORS.get("fh_over05", 52.0) else "no_pick"
    if fh_pick == "no_pick": fh_conf = None

    # ── Generate reasoning ────────────────────────────────────────────────────
    all_markets = {**final_markets, **corner_result, **card_result}
    reasoning = generate_reasoning(fixture, home_stats, away_stats, all_markets, poisson_markets, league)

    # ── Assemble final prediction record ─────────────────────────────────────
    result.update({
        "xg_home": round(xg_home, 3),
        "xg_away": round(xg_away, 3),
        "home_win_probability": final_markets["home_win"],
        "draw_probability": final_markets["draw"],
        "away_win_probability": final_markets["away_win"],
        "most_likely_score": final_markets["most_likely_score"],
        "score_matrix": matrix.tolist(),

        # Team context snapshot
        "home_elo": round(home_stats.get("elo_rating", 1500), 1),
        "away_elo": round(away_stats.get("elo_rating", 1500), 1),
        "home_form": home_stats.get("form_string", ""),
        "away_form": away_stats.get("form_string", ""),
        "home_attack_strength": round(home_stats.get("home_attack_strength", 1.0), 3),
        "away_attack_strength": round(away_stats.get("away_attack_strength", 1.0), 3),
        "home_defense_strength": round(home_stats.get("home_defense_strength", 1.0), 3),
        "away_defense_strength": round(away_stats.get("away_defense_strength", 1.0), 3),

        "predictions": {
            "winner":     {"pick": winner_pick, "confidence": winner_conf},
            "over15":     {"pick": o15_pick,    "confidence": o15_conf},
            "over25":     {"pick": o25_pick,    "confidence": o25_conf},
            "over35":     {"pick": o35_pick,    "confidence": o35_conf},
            "btts":       {"pick": btts_pick,   "confidence": btts_conf},
            "corners_85": {"pick": c85_pick,    "confidence": c85_conf},
            "corners_95": {"pick": c95_pick,    "confidence": c95_conf},
            "cards_35":   {"pick": cards_pick,  "confidence": cards_conf},
            "fh_over05":  {"pick": fh_pick,     "confidence": fh_conf},
        },
        "expected_corners": corner_result["expected_corners"],
        "expected_cards": card_result["expected_cards"],
        "red_card_probability": card_result["red_card_probability"],
        "reasoning": reasoning,
        "no_prediction_reason": None,
        "data_freshness_score": 100.0,
        "home_matches_used": home_total,
        "away_matches_used": away_total,
        "ml_used": ml_available,
    })

    return result


if __name__ == "__main__":
    run()
