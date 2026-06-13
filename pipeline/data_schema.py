# DATA SCHEMA — Football Predictor
# Every JSON file the pipeline reads and writes is documented here.
# Think of each file as a "table" in a traditional database.
#
# data/
#  ├── fixtures/
#  │   └── upcoming.json          — next 7 days fixtures
#  ├── predictions/
#  │   ├── latest.json            — today's predictions (symlink target)
#  │   └── YYYY-MM-DD.json        — predictions by date
#  ├── teams/
#  │   └── statistics.json        — all team rolling averages + Elo
#  ├── leagues/
#  │   └── baselines.json         — league-level averages
#  ├── accuracy/
#  │   └── results.json           — prediction vs actual scoring
#  ├── models/
#  │   ├── winner_model.joblib    — trained XGBoost classifier
#  │   ├── goals_model.joblib     — trained LightGBM classifier
#  │   ├── btts_model.joblib      — trained LightGBM classifier
#  │   ├── corners_model.joblib   — trained XGBoost regressor
#  │   ├── cards_model.joblib     — trained logistic regression
#  │   └── model_meta.json        — training dates, accuracy, version
#  └── logs/
#      └── pipeline_YYYY-MM-DD.json — daily run log

# ── upcoming.json schema ──────────────────────────────────────────────────────
UPCOMING_SCHEMA = {
    "last_updated": "ISO datetime",
    "fixtures": [
        {
            "id": "str — unique e.g. epl_42_49_20241115",
            "api_fixture_id": "int",
            "fixture_date": "ISO datetime",
            "league_id": "int",
            "league_name": "str",
            "league_country": "str",
            "league_logo": "str url",
            "season": "int",
            "round": "str e.g. Matchweek 12",
            "venue": "str",
            "home_team_id": "int",
            "home_team_name": "str",
            "home_team_logo": "str url",
            "away_team_id": "int",
            "away_team_name": "str",
            "away_team_logo": "str url",
            "referee_name": "str or null",
            "status": "str NS/1H/HT/2H/FT",
        }
    ]
}

# ── predictions/YYYY-MM-DD.json schema ────────────────────────────────────────
PREDICTION_SCHEMA = {
    "date": "YYYY-MM-DD",
    "generated_at": "ISO datetime",
    "model_version": "str",
    "total_fixtures": "int",
    "predictions_made": "int",
    "fixtures": [
        {
            # Match identity (copied from upcoming.json)
            "id": "str",
            "api_fixture_id": "int",
            "fixture_date": "ISO datetime",
            "league_name": "str",
            "league_country": "str",
            "league_logo": "str",
            "round": "str",
            "venue": "str",
            "home_team_id": "int",
            "home_team_name": "str",
            "home_team_logo": "str",
            "away_team_id": "int",
            "away_team_name": "str",
            "away_team_logo": "str",
            "referee_name": "str or null",
            "is_featured": "bool",

            # Dixon-Coles outputs
            "xg_home": "float",
            "xg_away": "float",
            "home_win_probability": "float 0-1",
            "draw_probability": "float 0-1",
            "away_win_probability": "float 0-1",
            "most_likely_score": "str e.g. 2-1",
            "score_matrix": "list[list[float]] 7x7",

            # Team context (snapshot at prediction time)
            "home_elo": "float",
            "away_elo": "float",
            "home_form": "str e.g. WWDLW",
            "away_form": "str e.g. DLWWL",
            "home_attack_strength": "float",
            "away_attack_strength": "float",
            "home_defense_strength": "float",
            "away_defense_strength": "float",

            # Prediction markets
            "predictions": {
                "winner":      {"pick": "home|draw|away|no_pick", "confidence": "float 0-100"},
                "over15":      {"pick": "over|under|no_pick",     "confidence": "float 0-100"},
                "over25":      {"pick": "over|under|no_pick",     "confidence": "float 0-100"},
                "over35":      {"pick": "over|under|no_pick",     "confidence": "float 0-100"},
                "btts":        {"pick": "yes|no|no_pick",         "confidence": "float 0-100"},
                "corners_85":  {"pick": "over|under|no_pick",     "confidence": "float 0-100"},
                "corners_95":  {"pick": "over|under|no_pick",     "confidence": "float 0-100"},
                "cards_35":    {"pick": "over|under|no_pick",     "confidence": "float 0-100"},
                "fh_over05":   {"pick": "over|under|no_pick",     "confidence": "float 0-100"},
            },
            "expected_corners": "float",
            "expected_cards": "float",
            "red_card_probability": "float 0-1",

            # Plain-English reasoning
            "reasoning": {
                "winner": "str",
                "over25": "str",
                "btts": "str",
                "corners": "str",
                "cards": "str",
            },

            # Data quality
            "no_prediction_reason": "str or null",
            "data_freshness_score": "float 0-100",
            "home_matches_used": "int",
            "away_matches_used": "int",
        }
    ]
}
