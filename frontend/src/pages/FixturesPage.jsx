// src/pages/FixturesPage.jsx — with Today/Tomorrow/Week/All date tabs
import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { getAllFixtures, getBestConfidence, getConfidenceLabel, safeFormat, safeDateStr } from '../services/data'
import { Spinner } from '../components/ui'
import { SlidersHorizontal, Cpu, RefreshCw } from 'lucide-react'

// Safe string coercion for any field that might be an object
function safeStr(val) {
  if (val == null) return null
  if (typeof val === 'string') return val
  if (typeof val === 'object') return val.name || JSON.stringify(val)
  return String(val)
}

function ConfBadge({ conf }) {
  const { label, color, bg, border } = getConfidenceLabel(conf)
  return (
    <div className={`flex flex-col items-center justify-center w-20 shrink-0 rounded-lg border px-2 py-2 ${bg} ${border}`}>
      <span className={`text-xl font-bold leading-none ${color}`}>
        {conf != null ? `${Math.round(conf)}%` : '—'}
      </span>
      <span className={`text-xs mt-0.5 ${color} opacity-80`}>{label}</span>
    </div>
  )
}

function FixtureRow({ fixture }) {
  const bestConf = getBestConfidence(fixture)
  const pred     = fixture.predictions || {}
  const bestMkt  = bestConf != null
    ? Object.entries(pred)
        .filter(([, p]) => p?.confidence != null && p?.pick && p.pick !== 'no_pick')
        .sort(([, a], [, b]) => b.confidence - a.confidence)[0]
    : null
  const dateStr = safeFormat(fixture.fixture_date, 'datetime')

  return (
    <Link to={`/fixture/${encodeURIComponent(fixture.id)}`}
      className="flex items-center gap-3 bg-slate-800 hover:bg-slate-750 border border-slate-700 hover:border-emerald-500/40 rounded-xl px-4 py-3 transition-all group"
    >
      <ConfBadge conf={bestConf} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
          {fixture.league_logo && (
            <img src={safeStr(fixture.league_logo)} alt="" className="w-3.5 h-3.5 object-contain"
              onError={e => { e.target.style.display='none' }} />
          )}
          <span className="text-xs text-slate-500 truncate">{safeStr(fixture.league_name)}</span>
          <span className="text-slate-600 text-xs">·</span>
          <span className="text-xs text-slate-600">{dateStr}</span>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {fixture.home_team_logo && (
            <img src={safeStr(fixture.home_team_logo)} alt="" className="w-5 h-5 object-contain shrink-0"
              onError={e => { e.target.style.display='none' }} />
          )}
          <span className="font-semibold text-sm text-white">{safeStr(fixture.home_team_name)}</span>
          <span className="text-slate-500 text-xs shrink-0">vs</span>
          <span className="font-semibold text-sm text-white">{safeStr(fixture.away_team_name)}</span>
          {fixture.away_team_logo && (
            <img src={safeStr(fixture.away_team_logo)} alt="" className="w-5 h-5 object-contain shrink-0"
              onError={e => { e.target.style.display='none' }} />
          )}
        </div>
        <div className="mt-0.5">
          {bestMkt ? (
            <span className="text-xs text-emerald-400">
              Best: <span className="font-medium">{bestMkt[0].replace(/_/g,' ')}</span>
              {' → '}<span className="font-bold uppercase">{bestMkt[1].pick}</span>
              {fixture.most_likely_score && <span className="text-slate-500 ml-2">· Likely {fixture.most_likely_score}</span>}
            </span>
          ) : (
            <span className="text-xs text-slate-600">
              {fixture.no_prediction_reason ? `⚠ ${fixture.no_prediction_reason}` : 'Building data…'}
            </span>
          )}
        </div>
      </div>
      <div className="hidden sm:flex flex-col items-end gap-1 shrink-0 text-xs text-slate-500">
        {fixture.xg_home != null && (
          <span>xG <span className="text-blue-400">{Number(fixture.xg_home).toFixed(1)}</span>–<span className="text-orange-400">{Number(fixture.xg_away).toFixed(1)}</span></span>
        )}
        {fixture.home_elo != null && (
          <span>Elo <span className="text-slate-400">{Math.round(fixture.home_elo)}</span>–<span className="text-slate-400">{Math.round(fixture.away_elo)}</span></span>
        )}
        <span className="text-slate-600 group-hover:text-emerald-500 transition-colors">Detail →</span>
      </div>
    </Link>
  )
}

// Date tab helper
function getDateRange(tab) {
  const todayStr = new Date().toISOString().split('T')[0]
  const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1)
  const tomStr   = tomorrow.toISOString().split('T')[0]
  const weekEnd  = new Date(); weekEnd.setDate(weekEnd.getDate() + 7)
  const weekStr  = weekEnd.toISOString().split('T')[0]

  if (tab === 'today')    return [todayStr, todayStr]
  if (tab === 'tomorrow') return [tomStr, tomStr]
  if (tab === 'week')     return [todayStr, weekStr]
  return [null, null] // all
}

const DATE_TABS = [
  { key: 'today',    label: 'Today'    },
  { key: 'tomorrow', label: 'Tomorrow' },
  { key: 'week',     label: 'This Week'},
  { key: 'all',      label: 'All'      },
]

const CONF_PRESETS = [
  { label: 'All',    min: 0,  max: 100 },
  { label: '60%+',   min: 60, max: 100 },
  { label: '70%+',   min: 70, max: 100 },
  { label: '80%+ ★', min: 80, max: 100 },
  { label: '70–80%', min: 70, max: 80  },
  { label: '80–90%', min: 80, max: 90  },
]

export default function FixturesPage() {
  const [all, setAll]       = useState({ upcoming: [], past: [], meta: {} })
  const [loading, setLoading] = useState(true)
  const [dateTab, setDateTab] = useState('today')
  const [showFilters, setShowFilters] = useState(false)
  const [confMin, setConfMin]   = useState(0)
  const [confMax, setConfMax]   = useState(100)
  const [limitN, setLimitN]     = useState(0)
  const [sortBy, setSortBy]     = useState('confidence')
  const [leagueFilter, setLeagueFilter] = useState('all')
  const [showNoPred, setShowNoPred] = useState(true)

  useEffect(() => {
    getAllFixtures()
      .then(d => setAll(d || { upcoming: [], past: [], meta: {} }))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const leagues = useMemo(() => {
    const s = new Set(all.upcoming.map(f => safeStr(f.league_name)).filter(Boolean))
    return ['all', ...Array.from(s).sort()]
  }, [all.upcoming])

  // Date counts for tab labels
  const dateCounts = useMemo(() => {
    const today  = new Date().toISOString().split('T')[0]
    const tom    = new Date(); tom.setDate(tom.getDate()+1)
    const tomStr = tom.toISOString().split('T')[0]
    const week   = new Date(); week.setDate(week.getDate()+7)
    const wkStr  = week.toISOString().split('T')[0]
    const counts = { today:0, tomorrow:0, week:0, all: all.upcoming.length }
    for (const f of all.upcoming) {
      const d = safeDateStr(f.fixture_date)
      if (d === today)           counts.today++
      if (d === tomStr)          counts.tomorrow++
      if (d >= today && d <= wkStr) counts.week++
    }
    return counts
  }, [all.upcoming])

  const filtered = useMemo(() => {
    const [dateFrom, dateTo] = getDateRange(dateTab)
    let result = all.upcoming.filter(f => {
      const d = safeDateStr(f.fixture_date)
      if (dateFrom && d < dateFrom) return false
      if (dateTo   && d > dateTo)   return false
      if (!showNoPred && getBestConfidence(f) == null) return false
      if (leagueFilter !== 'all' && safeStr(f.league_name) !== leagueFilter) return false
      const c = getBestConfidence(f)
      if (c != null) return c >= confMin && c <= confMax
      return confMin === 0
    })
    result = [...result].sort((a, b) => {
      if (sortBy === 'confidence') return (getBestConfidence(b) ?? -1) - (getBestConfidence(a) ?? -1)
      if (sortBy === 'date')   return safeDateStr(a.fixture_date).localeCompare(safeDateStr(b.fixture_date))
      if (sortBy === 'league') return (safeStr(a.league_name)||'').localeCompare(safeStr(b.league_name)||'')
      return 0
    })
    if (limitN > 0) result = result.slice(0, limitN)
    return result
  }, [all.upcoming, dateTab, confMin, confMax, limitN, sortBy, leagueFilter, showNoPred])

  const grouped = useMemo(() => filtered.reduce((acc, f) => {
    const key = safeDateStr(f.fixture_date) || 'Unknown'
    if (!acc[key]) acc[key] = []
    acc[key].push(f)
    return acc
  }, {}), [filtered])

  const predictedCount = all.upcoming.filter(f => getBestConfidence(f) != null).length
  const genAt = all.meta?.generated_at ? safeFormat(all.meta.generated_at, 'datetime') : '—'

  if (loading) return <Spinner />

  return (
    <div className="space-y-4">
      {/* Pipeline status */}
      <div className="flex flex-wrap items-center justify-between gap-2 bg-slate-800/80 border border-slate-700 rounded-xl px-4 py-3">
        <div className="flex items-center gap-2 flex-wrap text-sm">
          <Cpu size={13} className="text-emerald-400" />
          <span className="text-white font-medium">{all.upcoming.length} fixtures</span>
          <span className="text-slate-500">·</span>
          <span className="text-emerald-400 font-medium">{predictedCount} predicted</span>
          <span className="text-slate-500">·</span>
          <span className="text-slate-500">{all.upcoming.length - predictedCount} building data</span>
          {all.meta?.ml_active
            ? <span className="text-xs bg-emerald-900/40 text-emerald-300 border border-emerald-600/40 px-2 py-0.5 rounded-full ml-1">ML active</span>
            : <span className="text-xs bg-slate-700 text-slate-500 border border-slate-600 px-2 py-0.5 rounded-full ml-1">Statistical</span>
          }
        </div>
        <span className="text-xs text-slate-600 flex items-center gap-1">
          <RefreshCw size={10} /> Updated {genAt}
        </span>
      </div>

      {/* Date tabs */}
      <div className="flex gap-1 bg-slate-800 border border-slate-700 rounded-xl p-1">
        {DATE_TABS.map(({ key, label }) => (
          <button key={key} onClick={() => setDateTab(key)}
            className={`flex-1 py-2 px-1 text-xs font-medium rounded-lg transition-colors flex flex-col items-center ${
              dateTab === key ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            <span>{label}</span>
            <span className={`text-xs mt-0.5 ${dateTab === key ? 'text-emerald-200' : 'text-slate-600'}`}>
              {dateCounts[key]} matches
            </span>
          </button>
        ))}
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">
            {dateTab === 'today' ? "Today's Fixtures" :
             dateTab === 'tomorrow' ? "Tomorrow's Fixtures" :
             dateTab === 'week' ? 'This Week' : 'All Fixtures'}
          </h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Showing <span className="text-white font-medium">{filtered.length}</span>
            {limitN > 0 && <span className="text-emerald-400"> (top {limitN})</span>}
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/history" className="px-3 py-2 rounded-lg text-sm bg-slate-700 border border-slate-600 text-slate-300 hover:border-slate-500">
            📋 History
          </Link>
          <button onClick={() => setShowFilters(f => !f)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${showFilters ? 'bg-emerald-600 border-emerald-500 text-white' : 'bg-slate-800 border-slate-600 text-slate-300 hover:border-emerald-500/50'}`}
          >
            <SlidersHorizontal size={14} /> Filters
          </button>
        </div>
      </div>

      {showFilters && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-slate-400 mb-1.5 uppercase tracking-wide font-medium">League</label>
              <select value={leagueFilter} onChange={e => setLeagueFilter(e.target.value)}
                className="w-full bg-slate-700 text-white text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none focus:border-emerald-500"
              >
                {leagues.map(l => <option key={l} value={l}>{l === 'all' ? 'All leagues' : l}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5 uppercase tracking-wide font-medium">Sort by</label>
              <select value={sortBy} onChange={e => setSortBy(e.target.value)}
                className="w-full bg-slate-700 text-white text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none focus:border-emerald-500"
              >
                <option value="confidence">Confidence (highest first)</option>
                <option value="date">Kick-off time</option>
                <option value="league">League name</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5 uppercase tracking-wide font-medium">Top N</label>
              <div className="flex items-center gap-2">
                <input type="number" min={0} max={200} step={5} value={limitN}
                  onChange={e => setLimitN(Number(e.target.value))}
                  className="w-20 bg-slate-700 text-white text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none"
                />
                <div className="flex gap-1">
                  {[10,20,30].map(n => (
                    <button key={n} onClick={() => setLimitN(n)}
                      className={`text-xs px-2 py-1 rounded border transition-colors ${limitN===n ? 'bg-emerald-600 border-emerald-500 text-white' : 'bg-slate-700 border-slate-600 text-slate-400'}`}
                    >Top {n}</button>
                  ))}
                  <button onClick={() => setLimitN(0)}
                    className={`text-xs px-2 py-1 rounded border transition-colors ${limitN===0 ? 'bg-emerald-600 border-emerald-500 text-white' : 'bg-slate-700 border-slate-600 text-slate-400'}`}
                  >All</button>
                </div>
              </div>
            </div>
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-2 uppercase tracking-wide font-medium">
              Confidence: <span className="normal-case text-white">{confMin===0&&confMax===100?'All':`${confMin}%–${confMax}%`}</span>
            </label>
            <div className="flex flex-wrap gap-2">
              {CONF_PRESETS.map(({ label, min, max }) => (
                <button key={label} onClick={() => { setConfMin(min); setConfMax(max) }}
                  className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${confMin===min&&confMax===max ? 'bg-emerald-600 border-emerald-500 text-white' : 'bg-slate-700 border-slate-600 text-slate-400 hover:border-emerald-500/50'}`}
                >{label}</button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => setShowNoPred(p => !p)}
              className={`relative w-10 h-6 rounded-full border transition-colors ${showNoPred ? 'bg-emerald-600 border-emerald-500' : 'bg-slate-700 border-slate-600'}`}
            >
              <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${showNoPred ? 'translate-x-4' : 'translate-x-0.5'}`} />
            </button>
            <span className="text-sm text-slate-300">Show fixtures with no prediction yet</span>
          </div>
          <button onClick={() => { setConfMin(0); setConfMax(100); setLimitN(0); setSortBy('confidence'); setLeagueFilter('all'); setShowNoPred(true) }}
            className="text-xs text-slate-500 hover:text-slate-300 underline"
          >Reset filters</button>
        </div>
      )}

      {/* Confidence key */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {[
          { label:'80%+ Very Strong', color:'text-emerald-300' },
          { label:'70–80% Strong',    color:'text-green-400'   },
          { label:'60–70% Moderate',  color:'text-yellow-400'  },
          { label:'<60% Weak',        color:'text-orange-400'  },
          { label:'— No data yet',    color:'text-slate-500'   },
        ].map(({ label, color }) => <span key={label} className={color}>● {label}</span>)}
      </div>

      {/* Today empty state - pipeline likely needs to run */}
      {dateTab === 'today' && filtered.length === 0 && (
        <div className="text-center py-12 bg-slate-800/40 border border-slate-700 rounded-xl">
          <p className="text-slate-400 font-medium mb-2">No fixtures found for today</p>
          <p className="text-slate-500 text-sm mb-4">The pipeline may not have run yet today. Try "This Week" to see upcoming games, or run the pipeline from GitHub Actions.</p>
          <button onClick={() => setDateTab('week')}
            className="text-sm text-emerald-400 hover:underline"
          >View this week's fixtures →</button>
        </div>
      )}

      {/* Fixture list */}
      {filtered.length > 0 && (
        Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).map(([date, dayFixtures]) => (
          <section key={date}>
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2 mt-4">
              <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
              {safeFormat(date + 'T12:00:00', 'fulldate')}
              <span className="text-slate-600 normal-case font-normal">
                · {dayFixtures.length} match{dayFixtures.length !== 1 ? 'es' : ''}
                · {dayFixtures.filter(f => getBestConfidence(f) != null).length} predicted
              </span>
            </h2>
            <div className="space-y-2">
              {dayFixtures.map(f => <FixtureRow key={f.id} fixture={f} />)}
            </div>
          </section>
        ))
      )}
    </div>
  )
}
