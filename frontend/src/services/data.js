// src/services/data.js
const BASE = import.meta.env.VITE_DATA_BASE_URL || ''
const _cache = new Map()

async function fetchJSON(path) {
  if (_cache.has(path)) return _cache.get(path)
  try {
    const res = await fetch(`${BASE}${path}`)
    if (!res.ok) return null
    const text = await res.text()
    const t = text?.trim()
    if (!t || (!t.startsWith('{') && !t.startsWith('['))) return null
    const data = JSON.parse(t)
    _cache.set(path, data)
    return data
  } catch (e) {
    console.warn(`fetchJSON [${path}]:`, e.message)
    return null
  }
}

// Safe date string: always returns YYYY-MM-DD regardless of timezone offset
export function safeDateStr(dateStr) {
  if (!dateStr) return ''
  // Strip timezone and take date part only
  return dateStr.replace(/T.*$/, '').substring(0, 10)
}

// Safe format: never throws
export function safeFormat(dateStr, fmt) {
  try {
    // Parse date safely by replacing timezone offset with Z
    const cleaned = dateStr?.replace(/([+-]\d{2}:\d{2})$/, 'Z') || dateStr
    const d = new Date(cleaned)
    if (isNaN(d.getTime())) return dateStr || '—'
    // Manual formatting to avoid date-fns issues
    const days   = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    const pad = n => String(n).padStart(2,'0')
    if (fmt === 'daydate') return `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}`
    if (fmt === 'datetime') return `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]} · ${pad(d.getHours())}:${pad(d.getMinutes())}`
    if (fmt === 'fulldate') return `${['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][d.getDay()]}, ${months[d.getMonth()]} ${d.getDate()}`
    if (fmt === 'time') return `${pad(d.getHours())}:${pad(d.getMinutes())}`
    return d.toLocaleDateString()
  } catch (e) {
    return dateStr || '—'
  }
}

export async function getLatestPredictions() {
  return await fetchJSON('/predictions/latest.json')
}

export async function getPredictionsByDate(dateStr) {
  return await fetchJSON(`/predictions/${dateStr}.json`)
}

export async function getAllFixtures() {
  const [latestData, accuracyData] = await Promise.all([
    getLatestPredictions(),
    getAccuracyData(),
  ])

  // Use UTC date to avoid timezone boundary issues
  const todayUTC = new Date().toISOString().split('T')[0]

  const scoredMap = {}
  for (const r of (accuracyData?.recent_results || [])) {
    if (r.fixture_id) scoredMap[r.fixture_id] = r
  }

  // Use safeDateStr so timezone offsets don't push fixtures into wrong bucket
  const upcoming = (latestData?.fixtures || []).filter(f =>
    safeDateStr(f.fixture_date) >= todayUTC
  )

  // Past fixtures from last 30 dated files
  const pastPromises = []
  for (let i = 1; i <= 30; i++) {
    const d = new Date()
    d.setUTCDate(d.getUTCDate() - i)
    const ds = d.toISOString().split('T')[0]
    pastPromises.push(
      getPredictionsByDate(ds)
        .then(data => (data?.fixtures || [])
          .filter(f => safeDateStr(f.fixture_date) < todayUTC)
          .map(f => ({ ...f, _scored: scoredMap[f.id] || null }))
        ).catch(() => [])
    )
  }

  const pastArrays = await Promise.allSettled(pastPromises)
  const pastMap = new Map()
  for (const r of pastArrays) {
    if (r.status !== 'fulfilled') continue
    for (const f of r.value) {
      if (!pastMap.has(f.id)) pastMap.set(f.id, f)
    }
  }
  const past = [...pastMap.values()].sort((a, b) =>
    safeDateStr(b.fixture_date).localeCompare(safeDateStr(a.fixture_date))
  )

  return {
    upcoming,
    past,
    meta: {
      generated_at:   latestData?.generated_at  || null,
      ml_active:      latestData?.ml_active      ?? false,
      total_upcoming: upcoming.length,
      total_past:     past.length,
    }
  }
}

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
    d.setUTCDate(d.getUTCDate() - i)
    const data = await getPredictionsByDate(d.toISOString().split('T')[0])
    const f = (data?.fixtures || []).find(isMatch)
    if (f) return f
  }
  return null
}

export async function getMatchHistory()   { return await fetchJSON('/matches/history.json') }
export async function getAccuracyData()   { return await fetchJSON('/accuracy/results.json') }
export async function getTeamStatistics() { return await fetchJSON('/teams/statistics.json') }
export async function getModelMeta()      { return await fetchJSON('/models/model_meta.json') }

export async function searchFixtures(query) {
  if (!query || query.length < 2) return []
  const q = query.toLowerCase()
  const data = await getLatestPredictions()
  return (data?.fixtures || []).filter(f =>
    f.home_team_name?.toLowerCase().includes(q) ||
    f.away_team_name?.toLowerCase().includes(q) ||
    f.league_name?.toLowerCase().includes(q)
  )
}

export function getBestConfidence(fixture) {
  const vals = Object.values(fixture?.predictions || {})
    .map(p => p?.confidence)
    .filter(c => c != null && typeof c === 'number')
  return vals.length ? Math.max(...vals) : null
}

export function getConfidenceLabel(conf) {
  if (conf == null) return { label: 'No data',     color: 'text-slate-500',   bg: 'bg-slate-700/50',   border: 'border-slate-600'    }
  if (conf >= 80)   return { label: 'Very Strong', color: 'text-emerald-300', bg: 'bg-emerald-900/40', border: 'border-emerald-600/50'}
  if (conf >= 70)   return { label: 'Strong',      color: 'text-green-400',   bg: 'bg-green-900/30',   border: 'border-green-600/40'  }
  if (conf >= 60)   return { label: 'Moderate',    color: 'text-yellow-400',  bg: 'bg-yellow-900/20',  border: 'border-yellow-600/30' }
  return                   { label: 'Weak',        color: 'text-orange-400',  bg: 'bg-orange-900/20',  border: 'border-orange-600/30' }
}

export function clearCache() { _cache.clear() }
      
