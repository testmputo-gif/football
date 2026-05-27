// src/services/data.js
// Central data service - reads JSON files served as static assets by Vercel
// All data lives in the data/ folder, committed to GitHub, served at root path

const BASE = import.meta.env.VITE_DATA_BASE_URL || ''

// Session cache to avoid re-fetching same files
const _cache = new Map()

async function fetchJSON(path) {
  if (_cache.has(path)) return _cache.get(path)
  try {
    const res = await fetch(`${BASE}${path}`)
    if (!res.ok) throw new Error(`HTTP ${res.status} for ${path}`)
    const data = await res.json()
    _cache.set(path, data)
    return data
  } catch (e) {
    console.warn(`Failed to fetch ${path}:`, e.message)
    return null
  }
}

// ── Predictions ───────────────────────────────────────────────────────────────

export async function getLatestPredictions() {
  return await fetchJSON('/predictions/latest.json')
}

export async function getPredictionsByDate(dateStr) {
  return await fetchJSON(`/predictions/${dateStr}.json`)
}

export async function getFixtureById(fixtureId) {
  // Search latest predictions first
  const data = await getLatestPredictions()
  if (data?.fixtures) {
    // Try exact match on id field
    let found = data.fixtures.find(f => f.id === fixtureId)
    if (found) return found

    // Try matching api_fixture_id
    found = data.fixtures.find(f => String(f.api_fixture_id) === String(fixtureId))
    if (found) return found

    // Try partial match - the id might be a substring
    found = data.fixtures.find(f =>
      f.id && (
        f.id === fixtureId ||
        f.id.includes(fixtureId) ||
        fixtureId.includes(f.id)
      )
    )
    if (found) return found
  }

  // Search last 7 days of predictions if not found in latest
  const dates = await getRecentPredictionDates()
  for (const dateStr of dates.slice(0, 7)) {
    const dayData = await getPredictionsByDate(dateStr)
    if (!dayData?.fixtures) continue

    const found = dayData.fixtures.find(f =>
      f.id === fixtureId ||
      String(f.api_fixture_id) === String(fixtureId) ||
      (f.id && fixtureId && (f.id.includes(fixtureId) || fixtureId.includes(f.id)))
    )
    if (found) return found
  }

  return null
}

// ── Fixtures ──────────────────────────────────────────────────────────────────

export async function getUpcomingFixtures() {
  return await fetchJSON('/fixtures/upcoming.json')
}

// ── Teams ─────────────────────────────────────────────────────────────────────

export async function getTeamStatistics() {
  return await fetchJSON('/teams/statistics.json')
}

export async function getTeamById(teamId) {
  const data = await getTeamStatistics()
  if (!data?.teams) return null
  // Try direct lookup, then string version, then prefixed versions
  return (
    data.teams[teamId] ||
    data.teams[String(teamId)] ||
    data.teams[`fd_${teamId}`] ||
    data.teams[`bsd_${teamId}`] ||
    null
  )
}

// ── Leagues ───────────────────────────────────────────────────────────────────

export async function getLeagueBaselines() {
  return await fetchJSON('/leagues/baselines.json')
}

// ── Accuracy ──────────────────────────────────────────────────────────────────

export async function getAccuracyData() {
  return await fetchJSON('/accuracy/results.json')
}

// ── Model metadata ────────────────────────────────────────────────────────────

export async function getModelMeta() {
  return await fetchJSON('/models/model_meta.json')
}

// ── Helpers ───────────────────────────────────────────────────────────────────

export async function getRecentPredictionDates() {
  // Check last 14 days
  const dates = []
  const today = new Date()
  for (let i = 0; i < 14; i++) {
    const d = new Date(today)
    d.setDate(today.getDate() - i)
    dates.push(d.toISOString().split('T')[0])
  }
  return dates
}

export async function getTodaysPredictions() {
  const latest = await getLatestPredictions()
  if (!latest) return { fixtures: [], generated_at: null }
  return latest
}

export async function getTopPicks(market = 'over25', minConfidence = 65, limit = 10) {
  const data = await getLatestPredictions()
  if (!data?.fixtures) return []

  const marketKeyMap = {
    winner:  'winner',
    over25:  'over25',
    btts:    'btts',
    corners: 'corners_85',
    cards:   'cards_35',
  }
  const marketKey = marketKeyMap[market] || market

  return data.fixtures
    .filter(f => {
      const pred = f.predictions?.[marketKey]
      return pred &&
        pred.pick !== 'no_pick' &&
        pred.pick !== null &&
        pred.confidence != null &&
        pred.confidence >= minConfidence
    })
    .sort((a, b) => {
      const ca = a.predictions?.[marketKey]?.confidence || 0
      const cb = b.predictions?.[marketKey]?.confidence || 0
      return cb - ca
    })
    .slice(0, limit)
}

export async function searchFixtures(query) {
  if (!query || query.length < 2) return []
  const q = query.toLowerCase()
  const data = await getLatestPredictions()
  if (!data?.fixtures) return []
  return data.fixtures.filter(f =>
    f.home_team_name?.toLowerCase().includes(q) ||
    f.away_team_name?.toLowerCase().includes(q) ||
    f.league_name?.toLowerCase().includes(q)
  )
}

export function clearCache() {
  _cache.clear()
}

