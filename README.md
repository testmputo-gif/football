# ⚽ StatPredict — Football Prediction Engine
### Vercel + GitHub · Zero cost · Zero servers · Forever free

Dixon-Coles Poisson model + XGBoost ML · Fresh predictions every morning.

---

## How It Works

```
Every day 4 AM UTC — GitHub Actions (7GB RAM, free):
  1. Calls football API → saves to data/matches/history.json
  2. Calculates Elo, team stats, H2H → data/teams/statistics.json
  3. Runs Dixon-Coles + XGBoost → data/predictions/latest.json
  4. Scores yesterday's results → data/accuracy/results.json
  5. git commit + push → Vercel auto-deploys in ~60s

React frontend reads JSON files directly. No backend. No server.
```

---

## Setup (30 minutes)

### 1. Fork this repository (make it PUBLIC for free Actions minutes)

### 2. Get free API keys

- **api-football.com** via RapidAPI → free 100 req/day
- **football-data.org** → free, no daily cap

### 3. Add GitHub Secrets (Settings → Secrets → Actions)

| Secret | Value |
|--------|-------|
| `FOOTBALL_API_KEY` | RapidAPI key |
| `FOOTBALL_DATA_API_KEY` | football-data.org token |
| `VERCEL_TOKEN` | From Vercel dashboard |
| `VERCEL_ORG_ID` | From Vercel project settings |
| `VERCEL_PROJECT_ID` | From Vercel project settings |

Add Variables: `CURRENT_SEASON=2024`, `MODEL_VERSION=v1.0.0`

### 4. First run

Actions → Manual Pipeline Controls → Run workflow → **full_pipeline**

### 5. Deploy to Vercel

New Project → Import repo → Build: `cd frontend && npm install && npm run build` → Output: `dist`

---

## Cost: $0 forever

| Service | Free limit | Your usage |
|---------|-----------|------------|
| GitHub Actions | 2,000 min/month | ~900 min/month |
| Vercel | 100GB bandwidth | <1GB/month |
| API-Football | 100 req/day | ~12 req/day |

---

## Project Structure

```
/
├── .github/workflows/
│   ├── daily_pipeline.yml      ← 4 AM UTC every day
│   ├── deploy.yml              ← Auto-deploys on data change
│   └── manual_controls.yml    ← Run any step manually
├── pipeline/
│   ├── config.py               ← Settings (edit active leagues here)
│   ├── data_store.py           ← Read/write JSON files
│   ├── api_client.py           ← Football API + rate limiting
│   ├── step1_import_data.py    ← API import
│   ├── step2_calculate_stats.py ← Elo + stats + H2H
│   ├── step3_generate_predictions.py ← Dixon-Coles + ML
│   ├── step4_evaluate_results.py ← Score accuracy
│   └── step5_train_models.py   ← Monthly ML training
├── data/                       ← JSON database (committed to git)
│   ├── predictions/latest.json
│   ├── matches/history.json
│   ├── teams/statistics.json
│   ├── accuracy/results.json
│   └── models/*.joblib
└── frontend/                   ← React + Tailwind (Vercel)
    └── src/pages/
        ├── HomePage.jsx
        ├── FixturesPage.jsx
        ├── PredictionPage.jsx
        ├── SearchPage.jsx
        └── AccuracyPage.jsx
```

---

## Customise Leagues

Edit `pipeline/config.py` → `ACTIVE_LEAGUES`. Each league = ~2 API calls/day.
With 100/day budget you can run up to 8 leagues comfortably.

Popular IDs: EPL=39, La Liga=140, Bundesliga=78, Serie A=135, Ligue 1=61

---

*Dixon-Coles · XGBoost · LightGBM · React · Tailwind · Zero cost forever*
