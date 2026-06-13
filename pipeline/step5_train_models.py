"""
pipeline/step5_train_models.py
Trains XGBoost/LightGBM models on accumulated match history.
Runs on the 1st of each month via GitHub Actions.
Requires MIN_TRAINING_SAMPLES completed matches.

Saves trained models to data/models/*.joblib
These are committed back to the git repo and persist between runs.

Uses TimeSeriesSplit cross-validation — never trains on future data.
"""

import logging
import time
import json
import numpy as np
import pandas as pd
import joblib
from datetime import datetime
from pathlib import Path
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier, XGBRegressor
from lightgbm import LGBMClassifier

from pipeline.config import PATHS, MODEL_VERSION, MIN_TRAINING_SAMPLES
from pipeline.data_store import (
    get_match_history, get_team_statistics,
    get_league_baselines, get_h2h_data,
    get_model_meta, save_model_meta
)
from pipeline.step3_generate_predictions import (
    build_score_matrix, derive_markets, predict_corners,
    predict_cards, ELO_DEFAULT
)

log = logging.getLogger(__name__)


def run():
    start = time.time()
    log.info("Step 5: Train ML models (monthly)")

    # Load all data
    history = get_match_history()
    team_data = get_team_statistics()
    league_data = get_league_baselines()
    h2h_data = get_h2h_data()

    matches = list(history.get("matches", {}).values())
    team_stats = team_data.get("teams", {})
    league_baselines = league_data.get("leagues", {})
    h2h_records = h2h_data.get("records", {})

    # Sort by date — critical for TimeSeriesSplit
    matches.sort(key=lambda m: m.get("match_date", ""))

    if len(matches) < MIN_TRAINING_SAMPLES:
        log.warning(
            f"Only {len(matches)} matches available. "
            f"Need {MIN_TRAINING_SAMPLES} to train ML models. "
            f"Skipping — Dixon-Coles will be used until enough data accumulates."
        )
        return {"trained": False, "reason": "insufficient_data", "matches": len(matches)}

    log.info(f"Building training dataset from {len(matches)} matches")

    # ── Build feature matrix ──────────────────────────────────────────────────
    rows = []
    for match in matches:
        try:
            row = _build_training_row(match, team_stats, league_baselines, h2h_records)
            if row:
                rows.append(row)
        except Exception as e:
            log.debug(f"Skipped match in training: {e}")

    df = pd.DataFrame(rows)
    log.info(f"Training dataset: {len(df)} rows, {len(df.columns)} features")

    if len(df) < MIN_TRAINING_SAMPLES:
        log.warning(f"After feature building, only {len(df)} valid rows — skipping")
        return {"trained": False, "reason": "insufficient_valid_rows"}

    # Feature columns (all except label columns)
    label_cols = ["label_winner", "label_over25", "label_btts", "label_corners_over85", "label_cards_over35", "label_total_corners"]
    feature_cols = [c for c in df.columns if c not in label_cols]
    X = df[feature_cols].fillna(0).values.astype(np.float32)

    models_dir = PATHS["models_dir"]
    models_dir.mkdir(parents=True, exist_ok=True)

    tscv = TimeSeriesSplit(n_splits=5)
    accuracy_report = {}

    # ── Train winner model (XGBoost, 3-class) ────────────────────────────────
    log.info("Training winner model...")
    y_winner = df["label_winner"].values
    le = LabelEncoder()
    y_winner_enc = le.fit_transform(y_winner)

    winner_base = XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        use_label_encoder=False, eval_metric="mlogloss",
        random_state=42, n_jobs=2
    )
    # Calibrate for honest probabilities
    winner_model = CalibratedClassifierCV(winner_base, cv=3, method="isotonic")
    winner_model.fit(X, y_winner)

    cv_scores = cross_val_score(winner_base, X, y_winner_enc, cv=tscv, scoring="accuracy")
    accuracy_report["winner"] = round(float(cv_scores.mean()), 4)
    log.info(f"  Winner model CV accuracy: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    # Store class labels for inference
    winner_model.classes_ = np.array(["away", "draw", "home"])
    joblib.dump(winner_model, models_dir / "winner_model.joblib", compress=3)

    # ── Train goals model (LightGBM, binary over/under 2.5) ──────────────────
    log.info("Training goals model...")
    y_goals = df["label_over25"].values

    goals_base = LGBMClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, n_jobs=2, verbose=-1
    )
    goals_model = CalibratedClassifierCV(goals_base, cv=3, method="isotonic")
    goals_model.fit(X, y_goals)

    cv_scores = cross_val_score(goals_base, X, y_goals, cv=tscv, scoring="accuracy")
    accuracy_report["over25"] = round(float(cv_scores.mean()), 4)
    log.info(f"  Goals model CV accuracy: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
    joblib.dump(goals_model, models_dir / "goals_model.joblib", compress=3)

    # ── Train BTTS model (LightGBM, binary) ──────────────────────────────────
    log.info("Training BTTS model...")
    y_btts = df["label_btts"].values

    btts_base = LGBMClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, n_jobs=2, verbose=-1
    )
    btts_model = CalibratedClassifierCV(btts_base, cv=3, method="isotonic")
    btts_model.fit(X, y_btts)

    cv_scores = cross_val_score(btts_base, X, y_btts, cv=tscv, scoring="accuracy")
    accuracy_report["btts"] = round(float(cv_scores.mean()), 4)
    log.info(f"  BTTS model CV accuracy: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
    joblib.dump(btts_model, models_dir / "btts_model.joblib", compress=3)

    # ── Train corners model (XGBoost regressor → threshold) ──────────────────
    log.info("Training corners model...")
    corner_mask = df["label_total_corners"].notna()
    if corner_mask.sum() >= 100:
        X_c = df.loc[corner_mask, feature_cols].fillna(0).values.astype(np.float32)
        y_corners_total = df.loc[corner_mask, "label_total_corners"].values

        corners_model = XGBRegressor(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            subsample=0.8, random_state=42, n_jobs=2
        )
        corners_model.fit(X_c, y_corners_total)
        joblib.dump(corners_model, models_dir / "corners_model.joblib", compress=3)
        log.info(f"  Corners model trained on {corner_mask.sum()} matches")
    else:
        log.info("  Corners model: insufficient data — skipping")

    # ── Train cards model (Logistic Regression — simpler = better for noisy data) ──
    log.info("Training cards model...")
    y_cards = df["label_cards_over35"].values

    cards_model = LogisticRegression(
        C=0.5,         # Strong regularization — cards are noisy
        max_iter=1000,
        random_state=42
    )
    cards_cal = CalibratedClassifierCV(cards_model, cv=3, method="sigmoid")
    cards_cal.fit(X, y_cards)

    cv_scores = cross_val_score(cards_model, X, y_cards, cv=tscv, scoring="accuracy")
    accuracy_report["cards"] = round(float(cv_scores.mean()), 4)
    log.info(f"  Cards model CV accuracy: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
    joblib.dump(cards_cal, models_dir / "cards_model.joblib", compress=3)

    # ── Save model metadata ───────────────────────────────────────────────────
    meta = {
        "version": MODEL_VERSION,
        "last_trained": datetime.utcnow().isoformat(),
        "training_samples": len(df),
        "ml_available": True,
        "accuracy_on_training": accuracy_report,
        "feature_count": len(feature_cols),
        "feature_names": feature_cols,
    }
    save_model_meta(meta)

    elapsed = round(time.time() - start, 1)
    log.info(f"Step 5 complete in {elapsed}s. Models saved to {models_dir}")
    log.info(f"Accuracy: {accuracy_report}")

    return {"trained": True, "samples": len(df), "accuracy": accuracy_report}


def _build_training_row(match: dict, team_stats: dict, league_baselines: dict, h2h_records: dict) -> dict | None:
    """Build one training row from a completed match."""
    home_id = match.get("home_team_id")
    away_id = match.get("away_team_id")
    league_id = match.get("league_id")
    hg = match.get("home_goals")
    ag = match.get("away_goals")

    if not all([home_id, away_id, league_id, hg is not None, ag is not None]):
        return None

    home_stats = team_stats.get(home_id, {})
    away_stats = team_stats.get(away_id, {})
    league = league_baselines.get(league_id, {})

    if not home_stats or not away_stats or not league:
        return None

    # Must have sufficient data
    if home_stats.get("total_matches_played", 0) < 8:
        return None
    if away_stats.get("total_matches_played", 0) < 8:
        return None

    # Compute Poisson features (same as prediction step)
    la_home = league.get("avg_goals_home", 1.5)
    la_away = league.get("avg_goals_away", 1.1)
    ha = league.get("home_advantage_factor", 1.20)

    xg_home = max(0.1, min(
        home_stats.get("home_attack_strength", 1.0) *
        away_stats.get("away_defense_strength", 1.0) *
        la_home * ha, 5.0
    ))
    xg_away = max(0.1, min(
        away_stats.get("away_attack_strength", 1.0) *
        home_stats.get("home_defense_strength", 1.0) *
        la_away, 5.0
    ))

    matrix = build_score_matrix(xg_home, xg_away)
    pm = derive_markets(matrix)
    pm["xg_home"] = xg_home
    pm["xg_away"] = xg_away
    pm["xg_diff"] = xg_home - xg_away

    h2h_key = f"{min(home_id, away_id)}_{max(home_id, away_id)}"
    h2h = h2h_records.get(h2h_key, {})
    h2h_n = h2h.get("matches_played", 0)

    elo_home = home_stats.get("elo_rating", ELO_DEFAULT)
    elo_away = away_stats.get("elo_rating", ELO_DEFAULT)
    elo_diff = elo_home - elo_away
    elo_exp = 1.0 / (1.0 + 10 ** (-elo_diff / 400.0))

    # Build feature dict
    row = {
        # Poisson
        "poisson_home_win": pm["home_win"],
        "poisson_draw": pm["draw"],
        "poisson_away_win": pm["away_win"],
        "poisson_over25": pm["over25"],
        "poisson_btts": pm["btts"],
        "xg_home": xg_home, "xg_away": xg_away, "xg_diff": xg_home - xg_away,
        # Elo
        "elo_home": elo_home, "elo_away": elo_away,
        "elo_diff": elo_diff, "elo_expected_home": elo_exp,
        # Home stats
        "h_avg_gs": home_stats.get("home_avg_goals_scored", 0),
        "h_avg_gc": home_stats.get("home_avg_goals_conceded", 0),
        "h_atk_str": home_stats.get("home_attack_strength", 1.0),
        "h_def_str": home_stats.get("home_defense_strength", 1.0),
        "h_avg_corners": home_stats.get("home_avg_corners", 5.0),
        "h_avg_yellows": home_stats.get("home_avg_yellow_cards", 1.5),
        "h_mp": home_stats.get("home_matches_played", 0),
        "h_win_rate": home_stats.get("home_wins", 0) / max(home_stats.get("home_matches_played", 1), 1),
        "h_cs_rate": home_stats.get("home_clean_sheet_rate", 0.3),
        "h_form": home_stats.get("home_form_score", 0.5),
        "h_momentum": home_stats.get("goals_momentum", 1.0),
        # Away stats
        "a_avg_gs": away_stats.get("away_avg_goals_scored", 0),
        "a_avg_gc": away_stats.get("away_avg_goals_conceded", 0),
        "a_atk_str": away_stats.get("away_attack_strength", 1.0),
        "a_def_str": away_stats.get("away_defense_strength", 1.0),
        "a_avg_corners": away_stats.get("away_avg_corners", 4.5),
        "a_avg_yellows": away_stats.get("away_avg_yellow_cards", 1.5),
        "a_mp": away_stats.get("away_matches_played", 0),
        "a_win_rate": away_stats.get("away_wins", 0) / max(away_stats.get("away_matches_played", 1), 1),
        "a_cs_rate": away_stats.get("away_clean_sheet_rate", 0.3),
        "a_form": away_stats.get("away_form_score", 0.5),
        # Market rates
        "h_btts_rate": home_stats.get("btts_percentage", 0.5),
        "a_btts_rate": away_stats.get("btts_percentage", 0.5),
        "h_o25_rate": home_stats.get("over25_percentage", 0.5),
        "a_o25_rate": away_stats.get("over25_percentage", 0.5),
        # H2H
        "h2h_home_wr": h2h.get("home_wins", 0) / max(h2h_n, 1),
        "h2h_draw_r": h2h.get("draws", 0) / max(h2h_n, 1),
        "h2h_away_wr": h2h.get("away_wins", 0) / max(h2h_n, 1),
        "h2h_avg_goals": h2h.get("avg_goals", 2.5),
        "h2h_btts": h2h.get("btts_rate", 0.5),
        "h2h_n": float(h2h_n),
        # League
        "lg_home_wr": league.get("home_win_rate", 0.46),
        "lg_avg_goals": league.get("avg_goals_total", 2.6),
        "lg_avg_corners": league.get("avg_corners", 10.0),
        "lg_avg_cards": league.get("avg_cards", 3.5),

        # ── Labels ────────────────────────────────────────────────────────────
        "label_winner":   "home" if hg > ag else ("away" if ag > hg else "draw"),
        "label_over25":   int((hg + ag) > 2.5),
        "label_btts":     int(hg > 0 and ag > 0),
        "label_corners_over85": (
            int((match.get("home_corners", 0) or 0) + (match.get("away_corners", 0) or 0) > 8.5)
            if match.get("home_corners") is not None else None
        ),
        "label_cards_over35": int(
            (match.get("home_yellow_cards", 0) or 0) +
            (match.get("away_yellow_cards", 0) or 0) +
            (match.get("home_red_cards", 0) or 0) +
            (match.get("away_red_cards", 0) or 0) > 3.5
        ),
        "label_total_corners": (
            (match.get("home_corners", 0) or 0) + (match.get("away_corners", 0) or 0)
            if match.get("home_corners") is not None else None
        ),
    }
    return row


if __name__ == "__main__":
    run()
