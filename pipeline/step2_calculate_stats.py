"""
pipeline/step2_calculate_stats.py
Calculates all statistics from the match history JSON.
No API calls - pure data processing.

Computes per team:
  - Rolling averages (goals, corners, cards) home/away split
  - Exponentially weighted form scores
  - Attack/defense strength vs league average
  - BTTS, Over 2.5, clean sheet percentages
  - Elo ratings (updated after each result)
  - Goals momentum (last 3 vs season average)

Computes per league:
  - Average goals home/away
  - Home advantage factor
  - Win/draw/loss rates

Computes H2H records between all team pairs.
"""

import logging
import time
from collections import defaultdict
from datetime import datetime
from pipeline.data_store import (
    get_match_history,
    get_team_statistics, save_team_statistics,
    get_league_baselines, save_league_baselines,
    get_h2h_data, save_h2h_data,
)

log = logging.getLogger(__name__)

FORM_DECAY   = 0.75
ELO_K        = 32
ELO_DEFAULT  = 1500.0


def run():
    start = time.time()
    log.info("Step 2: Calculate statistics from match history")

    history = get_match_history()
    all_matches = list(history.get("matches", {}).values())

    if not all_matches:
        log.warning("No match history found - run step 1 first")
        return {"teams_updated": 0, "leagues_updated": 0}

    # Sort by date oldest first - critical for Elo calculation
    all_matches.sort(key=lambda m: m.get("match_date", ""))

    # Use whatever league IDs are actually in the data
    # This way Brazil/Copa work even if not in config ACTIVE_LEAGUE_IDS
    league_ids_in_data = list(
        {m.get("league_id") for m in all_matches if m.get("league_id")}
    )
    log.info(f"League IDs found in match data: {league_ids_in_data}")

    matches = [m for m in all_matches if m.get("league_id") in league_ids_in_data]
    log.info(f"Processing {len(matches)} matches across {len(league_ids_in_data)} leagues")

    # Step 2a: League baselines
    league_stats = _calculate_league_baselines(matches)

    # Step 2b: Team statistics
    team_stats = _calculate_team_statistics(matches, league_stats)

    # Step 2c: Elo ratings - merge into team stats
    elo_ratings = _calculate_elo_ratings(matches)
    for team_id, elo_data in elo_ratings.items():
        if team_id in team_stats:
            team_stats[team_id].update(elo_data)

    # Step 2d: H2H records
    h2h_records = _calculate_h2h(matches)

    # Save all
    save_league_baselines({"leagues": {str(k): v for k, v in league_stats.items()}})
    save_team_statistics({"teams": {str(k): v for k, v in team_stats.items()}})
    save_h2h_data({"records": h2h_records})

    elapsed = round(time.time() - start, 1)
    log.info(
        f"Step 2 complete in {elapsed}s: "
        f"{len(team_stats)} teams, "
        f"{len(league_stats)} leagues, "
        f"{len(h2h_records)} H2H pairs"
    )

    return {
        "teams_updated":   len(team_stats),
        "leagues_updated": len(league_stats),
        "h2h_pairs":       len(h2h_records),
    }


def _calculate_league_baselines(matches: list) -> dict:
    """Compute per-league averages from all completed matches."""
    league_data = defaultdict(lambda: {
        "home_goals": [], "away_goals": [],
        "corners": [], "cards": [], "results": [],
    })

    for m in matches:
        lid = m.get("league_id")
        hg  = m.get("home_goals")
        ag  = m.get("away_goals")
        if lid is None or hg is None or ag is None:
            continue

        league_data[lid]["home_goals"].append(hg)
        league_data[lid]["away_goals"].append(ag)

        hc = m.get("home_corners")
        ac = m.get("away_corners")
        if hc is not None and ac is not None:
            league_data[lid]["corners"].append(hc + ac)

        hy = m.get("home_yellow_cards") or 0
        ay = m.get("away_yellow_cards") or 0
        hr = m.get("home_red_cards") or 0
        ar = m.get("away_red_cards") or 0
        league_data[lid]["cards"].append(hy + ay + hr + ar)

        if hg > ag:
            league_data[lid]["results"].append("H")
        elif ag > hg:
            league_data[lid]["results"].append("A")
        else:
            league_data[lid]["results"].append("D")

    baselines = {}
    for lid, data in league_data.items():
        n = len(data["home_goals"])
        if n < 5:
            continue

        avg_home = sum(data["home_goals"]) / n
        avg_away = sum(data["away_goals"]) / n
        results  = data["results"]
        nr       = len(results)

        ha_factor = avg_home / avg_away if avg_away > 0 else 1.20
        ha_factor = max(1.05, min(ha_factor, 1.60))

        baselines[lid] = {
            "league_id":            lid,
            "sample_matches":       n,
            "avg_goals_home":       round(avg_home, 4),
            "avg_goals_away":       round(avg_away, 4),
            "avg_goals_total":      round(avg_home + avg_away, 4),
            "avg_corners":          round(sum(data["corners"]) / len(data["corners"]), 3) if data["corners"] else 10.0,
            "avg_cards":            round(sum(data["cards"]) / len(data["cards"]), 3) if data["cards"] else 3.5,
            "home_win_rate":        round(results.count("H") / nr, 4),
            "draw_rate":            round(results.count("D") / nr, 4),
            "away_win_rate":        round(results.count("A") / nr, 4),
            "home_advantage_factor": round(ha_factor, 4),
        }
        log.info(
            f"  League {lid}: {n} matches | "
            f"avg goals {avg_home:.2f}/{avg_away:.2f} | "
            f"HA={ha_factor:.3f}"
        )

    return baselines


def _calculate_team_statistics(matches: list, league_stats: dict) -> dict:
    """Compute per-team rolling statistics."""
    team_home_matches  = defaultdict(list)
    team_away_matches  = defaultdict(list)
    team_league        = {}

    for m in matches:
        htid = m.get("home_team_id")
        atid = m.get("away_team_id")
        lid  = m.get("league_id")
        hg   = m.get("home_goals")
        ag   = m.get("away_goals")

        if not all([htid, atid, lid, hg is not None, ag is not None]):
            continue

        team_league[htid] = lid
        team_league[atid] = lid
        team_home_matches[htid].append(m)
        team_away_matches[atid].append(m)

    team_stats    = {}
    all_team_ids  = set(team_home_matches.keys()) | set(team_away_matches.keys())

    for team_id in all_team_ids:
        home_matches = team_home_matches[team_id]
        away_matches = team_away_matches[team_id]
        all_m        = sorted(
            home_matches + away_matches,
            key=lambda m: m.get("match_date", "")
        )
        total = len(all_m)
        if total < 3:
            continue

        lid              = team_league.get(team_id)
        league_baseline  = league_stats.get(lid, {})

        home_s = _compute_split_stats(home_matches, is_home=True)
        away_s = _compute_split_stats(away_matches, is_home=False)

        btts_count  = sum(1 for m in all_m if (m.get("home_goals") or 0) > 0 and (m.get("away_goals") or 0) > 0)
        over15_count = sum(1 for m in all_m if (m.get("home_goals") or 0) + (m.get("away_goals") or 0) > 1.5)
        over25_count = sum(1 for m in all_m if (m.get("home_goals") or 0) + (m.get("away_goals") or 0) > 2.5)
        over35_count = sum(1 for m in all_m if (m.get("home_goals") or 0) + (m.get("away_goals") or 0) > 3.5)

        form_string = _compute_form_string(all_m[-5:], team_id)
        home_form   = _compute_weighted_form(home_matches[-6:], team_id, is_home=True)
        away_form   = _compute_weighted_form(away_matches[-6:], team_id, is_home=False)

        avg_goals_all = (
            (home_s["avg_goals_scored"] + away_s["avg_goals_scored"]) / 2
        )
        last_3       = all_m[-3:]
        goals_last_3 = _team_goals_in_matches(last_3, team_id) / max(len(last_3), 1)
        momentum     = goals_last_3 / avg_goals_all if avg_goals_all > 0 else 1.0
        momentum     = max(0.5, min(momentum, 2.0))

        la_home = league_baseline.get("avg_goals_home", 1.5)
        la_away = league_baseline.get("avg_goals_away", 1.1)

        home_atk = home_s["avg_goals_scored"]  / la_home if la_home > 0 else 1.0
        home_def = home_s["avg_goals_conceded"] / la_away if la_away > 0 else 1.0
        away_atk = away_s["avg_goals_scored"]  / la_away if la_away > 0 else 1.0
        away_def = away_s["avg_goals_conceded"] / la_home if la_home > 0 else 1.0

        attack_rating  = min(100, (home_atk + away_atk) / 2 * 50)
        defense_rating = min(100, max(0, 100 - (home_def + away_def) / 2 * 50))

        team_stats[team_id] = {
            "team_id":             team_id,
            "league_id":           lid,
            "total_matches_played": total,
            "data_sufficient": (
                total >= 8
                and home_s["matches_played"] >= 4
                and away_s["matches_played"] >= 4
            ),

            # Home stats (prefixed)
            **{f"home_{k}": v for k, v in home_s.items()},

            # Away stats (prefixed)
            **{f"away_{k}": v for k, v in away_s.items()},

            # Market percentages
            "btts_percentage":   round(btts_count  / total, 4),
            "over15_percentage": round(over15_count / total, 4),
            "over25_percentage": round(over25_count / total, 4),
            "over35_percentage": round(over35_count / total, 4),

            # Form
            "form_string":      form_string,
            "home_form_score":  round(home_form, 4),
            "away_form_score":  round(away_form, 4),
            "goals_momentum":   round(momentum, 4),

            # Strength ratios vs league average
            "home_attack_strength":  round(home_atk, 4),
            "home_defense_strength": round(home_def, 4),
            "away_attack_strength":  round(away_atk, 4),
            "away_defense_strength": round(away_def, 4),
            "attack_rating":         round(attack_rating, 1),
            "defense_rating":        round(defense_rating, 1),

            # Elo filled in by _calculate_elo_ratings
            "elo_rating":          ELO_DEFAULT,
            "elo_matches_played":  0,
        }

    return team_stats


def _compute_split_stats(matches: list, is_home: bool) -> dict:
    """Compute averages for a team's home or away matches."""
    n = len(matches)
    if n == 0:
        return {
            "matches_played": 0, "wins": 0, "draws": 0, "losses": 0,
            "avg_goals_scored": 0.0, "avg_goals_conceded": 0.0,
            "avg_corners": 0.0, "avg_yellow_cards": 0.0,
            "clean_sheet_rate": 0.0, "scoring_rate": 0.0,
        }

    goals_scored    = []
    goals_conceded  = []
    corners         = []
    yellows         = []
    wins = draws = losses = clean_sheets = scored_count = 0

    for m in matches:
        hg = m.get("home_goals", 0) or 0
        ag = m.get("away_goals", 0) or 0
        gs = hg if is_home else ag
        gc = ag if is_home else hg

        goals_scored.append(gs)
        goals_conceded.append(gc)

        if gs > gc:   wins   += 1
        elif gs == gc: draws  += 1
        else:          losses += 1

        if gc == 0: clean_sheets  += 1
        if gs > 0:  scored_count  += 1

        hc = m.get("home_corners")
        ac = m.get("away_corners")
        if hc is not None and ac is not None:
            corners.append(hc if is_home else ac)

        hy = m.get("home_yellow_cards") or 0
        ay = m.get("away_yellow_cards") or 0
        yellows.append(hy if is_home else ay)

    return {
        "matches_played":      n,
        "wins":                wins,
        "draws":               draws,
        "losses":              losses,
        "avg_goals_scored":    round(sum(goals_scored)   / n, 4),
        "avg_goals_conceded":  round(sum(goals_conceded) / n, 4),
        "avg_corners":         round(sum(corners) / len(corners), 4) if corners else 0.0,
        "avg_yellow_cards":    round(sum(yellows) / n, 4),
        "clean_sheet_rate":    round(clean_sheets   / n, 4),
        "scoring_rate":        round(scored_count   / n, 4),
    }


def _compute_form_string(matches: list, team_id: int) -> str:
    result = ""
    for m in matches:
        hg      = m.get("home_goals", 0) or 0
        ag      = m.get("away_goals", 0) or 0
        is_home = m.get("home_team_id") == team_id
        gs = hg if is_home else ag
        gc = ag if is_home else hg
        if gs > gc:    result += "W"
        elif gs == gc: result += "D"
        else:          result += "L"
    return result


def _compute_weighted_form(matches: list, team_id: int, is_home: bool) -> float:
    if not matches:
        return 0.5
    total_weight = total_score = 0.0
    for i, m in enumerate(reversed(matches)):
        w       = FORM_DECAY ** i
        hg      = m.get("home_goals", 0) or 0
        ag      = m.get("away_goals", 0) or 0
        is_h    = m.get("home_team_id") == team_id
        gs = hg if is_h else ag
        gc = ag if is_h else hg
        if gs > gc:    score = 1.0
        elif gs == gc: score = 0.4
        else:          score = 0.0
        total_score  += score * w
        total_weight += w
    return total_score / total_weight if total_weight > 0 else 0.5


def _team_goals_in_matches(matches: list, team_id: int) -> float:
    total = 0
    for m in matches:
        is_home = m.get("home_team_id") == team_id
        total  += (m.get("home_goals") or 0) if is_home else (m.get("away_goals") or 0)
    return float(total)


def _calculate_elo_ratings(matches: list) -> dict:
    ratings = defaultdict(lambda: ELO_DEFAULT)
    played  = defaultdict(int)

    for m in matches:
        htid = m.get("home_team_id")
        atid = m.get("away_team_id")
        hg   = m.get("home_goals")
        ag   = m.get("away_goals")
        if not all([htid, atid, hg is not None, ag is not None]):
            continue

        ra = ratings[htid]
        rb = ratings[atid]
        ea = 1.0 / (1.0 + 10 ** ((rb - ra - 50) / 400.0))
        eb = 1.0 - ea

        if hg > ag:   sa, sb = 1.0, 0.0
        elif hg < ag: sa, sb = 0.0, 1.0
        else:         sa, sb = 0.5, 0.5

        k = 20 if played[htid] > 30 else ELO_K
        ratings[htid] = ra + k * (sa - ea)
        ratings[atid] = rb + k * (sb - eb)
        played[htid] += 1
        played[atid] += 1

    return {
        tid: {
            "elo_rating":         round(ratings[tid], 2),
            "elo_matches_played": played[tid],
        }
        for tid in ratings
    }


def _calculate_h2h(matches: list) -> dict:
    h2h = defaultdict(lambda: {
        "home_wins": 0, "away_wins": 0, "draws": 0,
        "total_goals": 0, "btts_count": 0,
        "total_corners": 0, "corner_matches": 0,
        "total_cards": 0, "match_count": 0,
    })

    for m in matches:
        htid = m.get("home_team_id")
        atid = m.get("away_team_id")
        hg   = m.get("home_goals")
        ag   = m.get("away_goals")
        if not all([htid, atid, hg is not None, ag is not None]):
            continue

        key = f"{min(htid, atid)}_{max(htid, atid)}"
        rec = h2h[key]
        rec["match_count"] += 1

        if htid < atid:
            if hg > ag:   rec["home_wins"] += 1
            elif ag > hg: rec["away_wins"] += 1
            else:         rec["draws"]     += 1
        else:
            if ag > hg:   rec["home_wins"] += 1
            elif hg > ag: rec["away_wins"] += 1
            else:         rec["draws"]     += 1

        rec["total_goals"] += hg + ag
        if hg > 0 and ag > 0:
            rec["btts_count"] += 1

        hc = m.get("home_corners")
        ac = m.get("away_corners")
        if hc is not None and ac is not None:
            rec["total_corners"]  += hc + ac
            rec["corner_matches"] += 1

        hy = m.get("home_yellow_cards") or 0
        ay = m.get("away_yellow_cards") or 0
        hr = m.get("home_red_cards")    or 0
        ar = m.get("away_red_cards")    or 0
        rec["total_cards"] += hy + ay + hr + ar

    result = {}
    for key, rec in h2h.items():
        n = rec["match_count"]
        if n < 2:
            continue
        result[key] = {
            "matches_played": n,
            "home_wins":      rec["home_wins"],
            "away_wins":      rec["away_wins"],
            "draws":          rec["draws"],
            "avg_goals":      round(rec["total_goals"] / n, 3),
            "btts_rate":      round(rec["btts_count"]  / n, 3),
            "avg_corners":    round(rec["total_corners"] / rec["corner_matches"], 3) if rec["corner_matches"] > 0 else None,
            "avg_cards":      round(rec["total_cards"] / n, 3),
        }

    return result


if __name__ == "__main__":
    run()
