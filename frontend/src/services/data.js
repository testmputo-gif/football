// src/services/data.js — Central data service
// Reads JSON files served as static assets by Vercel from the data/ folder

const BASE = import.meta.env.VITE_DATA_BASE_URL || ''
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
    console.warn(`fetchJSON failed [${path}]:`, e.message)
    return null
  }
}

// ── Predictions ────────────────────────────────────────────────────────────────

export async function getLatestPredictions() {
  return await fetchJSON('/predictions/latest.json')
}

export async function getPredictionsByDate(dateStr) {
  return await fetchJSON(`/predictions/${dateStr}.json`)
}

/**
 * Load ALL fixtures: upcoming (latest.json) + past (from dated files).
 * Returns { upcoming: [...], past: [...] }
 * "past" includes the actual score from match history when available.
 */
export async function getAllFixtures() {
  const [latestData, historyData, accuracyData] = await Promise.all([
    getLatestPredictions(),
    getMatchHistory(),
    getAccuracyData(),
  ])

  const today = new Date().toISOString().split('T')[0]

  // Build a lookup of scored results from accuracy recent_results
  const scoredMap = {}
  for (const r of (accuracyData?.recent_results || [])) {
    if (r.fixture_id) scoredMap[r.fixture_id] = r
  }

  // Upcoming: latest.json, dates >= today
  const upcoming = (latestData?.fixtures || []).filter(f => {
    const fDate = f.fixture_date?.split('T')[0] || ''
    return fDate >= today
  })

  // Past: collect from last 30 days of prediction files
  const pastMap = new Map()
  const pastPromises = []
  for (let i = 1; i <= 30; i++) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const dateStr = d.toISOString().split('T')[0]
    pastPromises.push(getPredictionsByDate(dateStr).then(data => ({ dateStr, data })))
  }
  const pastResults = await Promise.allSettled(pastPromises)
  for (const res of pastResults) {
    if (res.status !== 'fulfilled' || !res.value?.data?.fixtures) continue
    for (const f of res.value.data.fixtures) {
      const fDate = f.fixture_date?.split('T')[0] || ''
      if (fDate < today && !pastMap.has(f.id)) {
        // Attach scoring data if available
        const scored = scoredMap[f.id]
        pastMap.set(f.id, { ...f, _scored: scored || null })
      }
    }
  }
  const past = [...pastMap.values()].sort((a, b) =>
    (b.fixture_date || '').localeCompare(a.fixture_date || '')
  )

  return {
    upcoming,
    past,
    meta: {
      generated_at: latestData?.generated_at,
      ml_active: latestData?.ml_active ?? false,
      total_upcoming: upcoming.length,
      total_past: past.length,
    }
  }
}

/**
 * Find a single fixture by ID — searches upcoming then past prediction files.
 */
export async function getFixtureById(targetId) {
  if (!targetId) return null
  const id = decodeURIComponent(targetId)

  const isMatch = f =>
    f.id === id || String(f.api_fixture_id) === id ||
    f.id === targetId || String(f.api_fixture_id) === targetId

  // Search latest first
  const latest = await getLatestPredictions()
  const found = (latest?.fixtures || []).find(isMatch)
  if (found) return found

  // Then dated files (last 30 days)
  for (let i = 1; i <= 30; i++) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const dateStr = d.toISOString().split('T')[0]
    const data = await getPredictionsByDate(dateStr)
    const f = (data?.fixtures || []).find(isMatch)
    if (f) return f
  }
  return null
}

// ── Match History ──────────────────────────────────────────────────────────────

export async function getMatchHistory() {
  return await fetchJSON('/matches/history.json')
}

// ── Accuracy & Self-Scoring ────────────────────────────────────────────────────

export async function getAccuracyData() {
  return await fetchJSON('/accuracy/results.json')
}

// ── Teams / Leagues ────────────────────────────────────────────────────────────

export async function getTeamStatistics() {
  return await fetchJSON('/teams/statistics.json')
}

export async function getModelMeta() {
  return await fetchJSON('/models/model_meta.json')
}

// ── Search ─────────────────────────────────────────────────────────────────────

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

// ── Helpers ────────────────────────────────────────────────────────────────────

export function getBestConfidence(fixture) {
  const preds = fixture?.predictions || {}
  const values = Object.values(preds)
    .map(p => p?.confidence)
    .filter(c => c != null && typeof c === 'number')
  return values.length ? Math.max(...values) : null
}

export function getConfidenceLabel(conf) {
  if (conf == null) return { label: 'No data', color: 'text-slate-500', bg: 'bg-slate-700/50', border: 'border-slate-600' }
  if (conf >= 80) return { label: 'Very Strong', color: 'text-emerald-300', bg: 'bg-emerald-900/40', border: 'border-emerald-600/50' }
  if (conf >= 70) return { label: 'Strong',      color: 'text-green-400',   bg: 'bg-green-900/30',  border: 'border-green-600/40'  }
  if (conf >= 60) return { label: 'Moderate',    color: 'text-yellow-400',  bg: 'bg-yellow-900/20', border: 'border-yellow-600/30' }
  return              { label: 'Weak',         color: 'text-orange-400',  bg: 'bg-orange-900/20', border: 'border-orange-600/30' }
}

export function clearCache() { _cache.clear() }
