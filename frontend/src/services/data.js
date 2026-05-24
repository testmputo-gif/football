// src/services/data.js
// All data is read from JSON files in the GitHub repo.
// In production (Vercel), these files are served as static assets
// from the /public directory (which maps to our data/ folder).
// In development, same thing via Vite's publicDir setting.

const BASE = import.meta.env.VITE_DATA_BASE_URL || ''

// Cache responses for the session to avoid re-fetching
const _cache = new Map()

async function fetchJSON(path) {
  if (_cache.has(path)) return _cache.get(path)
  try {
    const res = await fetch(`${BASE}${path}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
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
  const data = await getLatestPredictions()
  if (!data) return null
  const fixture = data.fixtures?.find(f => f.id === fixtureId || String(f.api_fixture_id) === String(fixtureId))
  // Also check recent dates if not found in latest
  if (!fixture) {
    const recent = await getRecentPredictionDates()
    for (const dateStr of recent.slice(0, 5)) {
      const dayData = await getPredictionsByDate(dateStr)
      const found = dayData?.fixtures?.find(f => f.id === fixtureId || String(f.api_fixture_id) === String(fixtureId))
      if (found) return found
    }
  }
  return fixture || null
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
  return data?.teams?.[teamId] || null
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
  // We don't have a directory listing, so check last 14 days
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

  const confidenceKey = {
    winner: 'winner', over25: 'over25', btts: 'btts',
    corners: 'corners_85', cards: 'cards_35'
  }[market] || market

  return data.fixtures
    .filter(f => {
      const pred = f.predictions?.[confidenceKey]
      return pred && pred.pick !== 'no_pick' && pred.confidence >= minConfidence
    })
    .sort((a, b) => {
      const ca = a.predictions?.[confidenceKey]?.confidence || 0
      const cb = b.predictions?.[confidenceKey]?.confidence || 0
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

// Clear cache (useful after data updates)
export function clearCache() { _cache.clear() }
