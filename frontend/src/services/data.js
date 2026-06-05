// src/services/data.js — Central data service
const BASE = import.meta.env.VITE_DATA_BASE_URL || ''
const _cache = new Map()

// fetchJSON: NEVER throws. Returns null on any failure.
async function fetchJSON(path) {
  if (_cache.has(path)) return _cache.get(path)
  try {
    const res = await fetch(`${BASE}${path}`)
    if (!res.ok) return null          // 404, 401, etc — just return null
    const text = await res.text()
    if (!text || !text.trim().startsWith('{') && !text.trim().startsWith('[')) return null
    const data = JSON.parse(text)
    _cache.set(path, data)
    return data
  } catch (e) {
    console.warn(`fetchJSON [${path}]:`, e.message)
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
 * NEVER throws — always returns { upcoming, past, meta } even if all fetches fail.
 */
export async function getAllFixtures() {
  // Fetch these in parallel but handle nulls gracefully
  const [latestData, accuracyData] = await Promise.all([
    getLatestPredictions(),
    getAccuracyData(),
  ])

  const today = new Date().toISOString().split('T')[0]

  // Build scored-result lookup from accuracy recent_results
  const scoredMap = {}
  for (const r of (accuracyData?.recent_results || [])) {
    if (r.fixture_id) scoredMap[r.fixture_id] = r
  }

  // Upcoming: fixtures from latest.json with date >= today
  const upcoming = (latestData?.fixtures || []).filter(f => {
    const fDate = f.fixture_date?.split('T')[0] || ''
    return fDate >= today
  })

  // Past: fetch last 30 days of dated prediction files (parallel, best-effort)
  const pastPromises = []
  for (let i = 1; i <= 30; i++) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const dateStr = d.toISOString().split('T')[0]
    pastPromises.push(
      getPredictionsByDate(dateStr)
        .then(data => (data?.fixtures || [])
          .filter(f => (f.fixture_date?.split('T')[0] || '') < today)
          .map(f => ({ ...f, _scored: scoredMap[f.id] || null }))
        )
        .catch(() => [])
    )
  }

  const pastArrays  = await Promise.allSettled(pastPromises)
  const pastMap     = new Map()
  for (const res of pastArrays) {
    if (res.status !== 'fulfilled') continue
    for (const f of res.value) {
      if (!pastMap.has(f.id)) pastMap.set(f.id, f)
    }
  }
  const past = [...pastMap.values()].sort((a, b) =>
    (b.fixture_date || '').localeCompare(a.fixture_date || '')
  )

  return {
    upcoming,
    past,
    meta: {
      generated_at:    latestData?.generated_at   || null,
      ml_active:       latestData?.ml_active       ?? false,
      total_upcoming:  upcoming.length,
      total_past:      past.length,
    }
  }
}

/**
 * Find a single fixture by ID — never throws.
 */
export async function getFixtureById(targetId) {
  if (!targetId) return null
  const id = decodeURIComponent(targetId)
  const isMatch = f =>
    f.id === id || String(f.api_fixture_id) === id ||
    f.id === targetId || String(f.api_fixture_id) === targetId

  const latest = await getLatestPredictions()
  const found  = (latest?.fixtures || []).find(isMatch)
  if (found) return found

  for (let i = 1; i <= 30; i++) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const data = await getPredictionsByDate(d.toISOString().split('T')[0])
    const f    = (data?.fixtures || []).find(isMatch)
    if (f) return f
  }
  return null
}

// ── Other data ──────────────────────────────────────────────────────────────────

export async function getMatchHistory()   { return await fetchJSON('/matches/history.json') }
export async function getAccuracyData()   { return await fetchJSON('/accuracy/results.json') }
export async function getTeamStatistics() { return await fetchJSON('/teams/statistics.json') }
export async function getModelMeta()      { return await fetchJSON('/models/model_meta.json') }

export async function searchFixtures(query) {
  if (!query || query.length < 2) return []
  const q    = query.toLowerCase()
  const data = await getLatestPredictions()
  return (data?.fixtures || []).filter(f =>
    f.home_team_name?.toLowerCase().includes(q) ||
    f.away_team_name?.toLowerCase().includes(q) ||
    f.league_name?.toLowerCase().includes(q)
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────────

export function getBestConfidence(fixture) {
  const vals = Object.values(fixture?.predictions || {})
    .map(p => p?.confidence)
    .filter(c => c != null && typeof c === 'number')
  return vals.length ? Math.max(...vals) : null
}

export function getConfidenceLabel(conf) {
  if (conf == null) return { label: 'No data',     color: 'text-slate-500', bg: 'bg-slate-700/50',   border: 'border-slate-600' }
  if (conf >= 80)   return { label: 'Very Strong', color: 'text-emerald-300', bg: 'bg-emerald-900/40', border: 'border-emerald-600/50' }
  if (conf >= 70)   return { label: 'Strong',      color: 'text-green-400',   bg: 'bg-green-900/30',   border: 'border-green-600/40'  }
  if (conf >= 60)   return { label: 'Moderate',    color: 'text-yellow-400',  bg: 'bg-yellow-900/20',  border: 'border-yellow-600/30' }
  return                   { label: 'Weak',        color: 'text-orange-400',  bg: 'bg-orange-900/20',  border: 'border-orange-600/30' }
}

export function clearCache() { _cache.clear() }
  
