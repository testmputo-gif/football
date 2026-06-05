// src/pages/FixturesPage.jsx
// Shows ALL upcoming fixtures fetched from APIs, graded by confidence level.
// Past fixtures are moved to /history.

import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { getAllFixtures, getBestConfidence, getConfidenceLabel, getModelMeta } from '../services/data'
import { Spinner } from '../components/ui'
import { format } from 'date-fns'
import { SlidersHorizontal, ChevronDown, ChevronUp, Cpu, Database, RefreshCw, TrendingUp } from 'lucide-react'

// ── Confidence badge ──────────────────────────────────────────────────────────
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

// ── Single fixture row ────────────────────────────────────────────────────────
function FixtureRow({ fixture }) {
  const bestConf   = getBestConfidence(fixture)
  const hasPred    = bestConf != null
  const pred       = fixture.predictions || {}

  // Best market pick to display
  const bestMarket = hasPred
    ? Object.entries(pred)
        .filter(([, p]) => p?.confidence != null && p?.pick && p.pick !== 'no_pick')
        .sort(([, a], [, b]) => b.confidence - a.confidence)[0]
    : null

  let dateStr = '—'
  try { dateStr = format(new Date(fixture.fixture_date), 'EEE d MMM · HH:mm') } catch (_) {}

  return (
    <Link to={`/fixture/${encodeURIComponent(fixture.id)}`}
      className="flex items-center gap-3 bg-slate-800 hover:bg-slate-750 border border-slate-700 hover:border-emerald-500/40 rounded-xl px-4 py-3 transition-all group"
    >
      {/* Confidence grade */}
      <ConfBadge conf={bestConf} />

      {/* Match info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-0.5">
          {fixture.league_logo && (
            <img src={fixture.league_logo} alt="" className="w-3.5 h-3.5 object-contain"
              onError={e => { e.target.style.display='none' }} />
          )}
          <span className="text-xs text-slate-500 truncate">{fixture.league_name}</span>
          <span className="text-slate-600 text-xs">·</span>
          <span className="text-xs text-slate-600">{dateStr}</span>
        </div>
        <div className="flex items-center gap-2">
          {fixture.home_team_logo && (
            <img src={fixture.home_team_logo} alt="" className="w-5 h-5 object-contain shrink-0"
              onError={e => { e.target.style.display='none' }} />
          )}
          <span className="font-semibold text-sm text-white truncate">{fixture.home_team_name}</span>
          <span className="text-slate-500 text-xs shrink-0">vs</span>
          <span className="font-semibold text-sm text-white truncate">{fixture.away_team_name}</span>
          {fixture.away_team_logo && (
            <img src={fixture.away_team_logo} alt="" className="w-5 h-5 object-contain shrink-0"
              onError={e => { e.target.style.display='none' }} />
          )}
        </div>

        {/* Best pick label or pending reason */}
        <div className="mt-1">
          {bestMarket ? (
            <span className="text-xs text-emerald-400">
              Best pick: <span className="font-medium">{bestMarket[0].replace(/_/g,' ')}</span>
              {' → '}<span className="font-bold uppercase">{bestMarket[1].pick}</span>
              {fixture.most_likely_score && (
                <span className="text-slate-500 ml-2">· Likely score {fixture.most_likely_score}</span>
              )}
            </span>
          ) : (
            <span className="text-xs text-slate-600">
              {fixture.no_prediction_reason
                ? `⚠ ${fixture.no_prediction_reason}`
                : 'Analysis in progress'}
            </span>
          )}
        </div>
      </div>

      {/* xG + ELO quick stats */}
      <div className="hidden sm:flex flex-col items-end gap-1 shrink-0 text-xs text-slate-500">
        {fixture.xg_home != null && (
          <span>xG <span className="text-blue-400">{fixture.xg_home?.toFixed(1)}</span>–<span className="text-orange-400">{fixture.xg_away?.toFixed(1)}</span></span>
        )}
        {fixture.home_elo != null && (
          <span>Elo <span className="text-slate-400">{Math.round(fixture.home_elo)}</span>–<span className="text-slate-400">{Math.round(fixture.away_elo)}</span></span>
        )}
        <span className="text-slate-600 group-hover:text-emerald-500 transition-colors">Full analysis →</span>
      </div>
    </Link>
  )
}

// ── Pipeline header ───────────────────────────────────────────────────────────
function PipelineHeader({ meta, totalCount, predictedCount, expanded, onToggle }) {
  const generatedAt = meta?.generated_at
    ? format(new Date(meta.generated_at), 'HH:mm, d MMM')
    : '—'

  return (
    <button onClick={onToggle}
      className="w-full flex items-center justify-between bg-slate-800/80 border border-slate-700 rounded-xl px-5 py-3 hover:bg-slate-700/40 transition-colors"
    >
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1.5">
          <Cpu size={13} className="text-emerald-400" />
          <span className="text-sm font-medium text-white">Pipeline</span>
        </div>
        <span className="text-xs text-slate-500">Updated {generatedAt} UTC</span>
        {meta?.ml_active
          ? <span className="text-xs bg-emerald-900/40 text-emerald-300 border border-emerald-600/40 px-2 py-0.5 rounded-full">ML active</span>
          : <span className="text-xs bg-slate-700 text-slate-500 border border-slate-600 px-2 py-0.5 rounded-full">Statistical only</span>
        }
      </div>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-3 text-sm">
          <span><span className="text-white font-bold">{totalCount}</span> <span className="text-slate-500">fixtures</span></span>
          <span><span className="text-emerald-400 font-bold">{predictedCount}</span> <span className="text-slate-500">predicted</span></span>
          <span><span className="text-slate-500 font-bold">{totalCount - predictedCount}</span> <span className="text-slate-500">pending</span></span>
        </div>
        {expanded ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
      </div>
    </button>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────
const CONF_PRESETS = [
  { label: 'All',     min: 0,  max: 100 },
  { label: '60%+',    min: 60, max: 100 },
  { label: '70%+',    min: 70, max: 100 },
  { label: '80%+ ★',  min: 80, max: 100 },
  { label: '60–70%',  min: 60, max: 70  },
  { label: '70–80%',  min: 70, max: 80  },
  { label: '80–90%',  min: 80, max: 90  },
]

export default function FixturesPage() {
  const [all, setAll]         = useState({ upcoming: [], past: [], meta: {} })
  const [loading, setLoading] = useState(true)
  const [headerExpanded, setHeaderExpanded] = useState(false)
  const [showFilters, setShowFilters] = useState(false)

  // Filters
  const [confMin, setConfMin]       = useState(0)
  const [confMax, setConfMax]       = useState(100)
  const [limitN, setLimitN]         = useState(0)
  const [sortBy, setSortBy]         = useState('confidence')  // confidence | date | league
  const [leagueFilter, setLeagueFilter] = useState('all')
  const [showNoPred, setShowNoPred] = useState(true)

  useEffect(() => {
    getAllFixtures().then(d => setAll(d)).finally(() => setLoading(false))
  }, [])

  // Build league list from upcoming
  const leagues = useMemo(() => {
    const set = new Set(all.upcoming.map(f => f.league_name).filter(Boolean))
    return ['all', ...Array.from(set).sort()]
  }, [all.upcoming])

  const filtered = useMemo(() => {
    let result = all.upcoming.filter(f => {
      if (!showNoPred && !f.predictions) return false
      if (leagueFilter !== 'all' && f.league_name !== leagueFilter) return false
      const conf = getBestConfidence(f)
      if (conf != null) {
        if (conf < confMin || conf > confMax) return false
      } else {
        // fixture with no confidence: include only if confMin is 0
        if (confMin > 0) return false
      }
      return true
    })

    result = [...result].sort((a, b) => {
      if (sortBy === 'confidence') {
        return (getBestConfidence(b) ?? -1) - (getBestConfidence(a) ?? -1)
      }
      if (sortBy === 'date') return (a.fixture_date || '').localeCompare(b.fixture_date || '')
      if (sortBy === 'league') return (a.league_name || '').localeCompare(b.league_name || '')
      return 0
    })

    if (limitN > 0) result = result.slice(0, limitN)
    return result
  }, [all.upcoming, confMin, confMax, limitN, sortBy, leagueFilter, showNoPred])

  // Group by date
  const grouped = useMemo(() => {
    return filtered.reduce((acc, f) => {
      const key = f.fixture_date?.split('T')[0] || 'Unknown'
      if (!acc[key]) acc[key] = []
      acc[key].push(f)
      return acc
    }, {})
  }, [filtered])

  const predictedCount = all.upcoming.filter(f => getBestConfidence(f) != null).length

  if (loading) return <Spinner />

  return (
    <div className="space-y-4">

      {/* Pipeline status header */}
      <PipelineHeader
        meta={all.meta}
        totalCount={all.upcoming.length}
        predictedCount={predictedCount}
        expanded={headerExpanded}
        onToggle={() => setHeaderExpanded(e => !e)}
      />

      {headerExpanded && (
        <div className="bg-slate-800/60 border border-slate-700 rounded-xl px-5 py-4 text-sm text-slate-400 space-y-1">
          <p>Engine: <span className="text-white">{all.meta?.ml_active ? 'Dixon-Coles + XGBoost/LightGBM ensemble' : 'Dixon-Coles Poisson (statistical)'}</span></p>
          <p>All fixtures shown — confidence grade shows the highest confidence market available for each match.</p>
          <p>Fixtures with no confidence have insufficient historical data for that team pair. They still show here so you can see everything being fetched.</p>
          <Link to="/history" className="text-emerald-400 hover:underline text-sm">View past fixtures & self-scoring →</Link>
        </div>
      )}

      {/* Page title + filter toggle */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Upcoming Fixtures</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Showing <span className="text-white font-medium">{filtered.length}</span> of {all.upcoming.length} fixtures
            {limitN > 0 && <span className="text-emerald-400"> (top {limitN})</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/history"
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm bg-slate-700 border border-slate-600 text-slate-300 hover:border-slate-500"
          >
            <span>📋</span> History
          </Link>
          <button onClick={() => setShowFilters(f => !f)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
              showFilters ? 'bg-emerald-600 border-emerald-500 text-white' : 'bg-slate-800 border-slate-600 text-slate-300 hover:border-emerald-500/50'
            }`}
          >
            <SlidersHorizontal size={14} />
            Filter & Sort
          </button>
        </div>
      </div>

      {/* Filter panel */}
      {showFilters && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">

            {/* League */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5 font-medium uppercase tracking-wide">League</label>
              <select value={leagueFilter} onChange={e => setLeagueFilter(e.target.value)}
                className="w-full bg-slate-700 text-white text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none focus:border-emerald-500"
              >
                {leagues.map(l => <option key={l} value={l}>{l === 'all' ? 'All leagues' : l}</option>)}
              </select>
            </div>

            {/* Sort */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5 font-medium uppercase tracking-wide">Sort by</label>
              <select value={sortBy} onChange={e => setSortBy(e.target.value)}
                className="w-full bg-slate-700 text-white text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none focus:border-emerald-500"
              >
                <option value="confidence">Confidence (highest first)</option>
                <option value="date">Kick-off time</option>
                <option value="league">League name</option>
              </select>
            </div>

            {/* Top N */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5 font-medium uppercase tracking-wide">Show top N <span className="normal-case text-slate-500">(0 = all)</span></label>
              <div className="flex items-center gap-2">
                <input type="number" min={0} max={200} step={5} value={limitN}
                  onChange={e => setLimitN(Number(e.target.value))}
                  className="w-20 bg-slate-700 text-white text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none focus:border-emerald-500"
                />
                <div className="flex gap-1">
                  {[5,10,15,20,25].map(n => (
                    <button key={n} onClick={() => setLimitN(n)}
                      className={`text-xs px-2 py-1 rounded border transition-colors ${limitN===n ? 'bg-emerald-600 border-emerald-500 text-white' : 'bg-slate-700 border-slate-600 text-slate-400 hover:border-emerald-500/50'}`}
                    >Top {n}</button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Confidence range quick buttons */}
          <div>
            <label className="block text-xs text-slate-400 mb-2 font-medium uppercase tracking-wide">
              Confidence range: <span className="normal-case text-white">{confMin === 0 && confMax === 100 ? 'All' : `${confMin}% – ${confMax}%`}</span>
            </label>
            <div className="flex flex-wrap gap-2">
              {CONF_PRESETS.map(({ label, min, max }) => (
                <button key={label}
                  onClick={() => { setConfMin(min); setConfMax(max) }}
                  className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                    confMin === min && confMax === max
                      ? 'bg-emerald-600 border-emerald-500 text-white'
                      : 'bg-slate-700 border-slate-600 text-slate-400 hover:border-emerald-500/50'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Show no-prediction toggle */}
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
          >Reset all filters</button>
        </div>
      )}

      {/* Confidence key */}
      <div className="flex flex-wrap gap-3 text-xs">
        {[
          { label:'80%+ Very Strong', color:'text-emerald-300' },
          { label:'70–80% Strong', color:'text-green-400' },
          { label:'60–70% Moderate', color:'text-yellow-400' },
          { label:'<60% Weak', color:'text-orange-400' },
          { label:'— No data yet', color:'text-slate-500' },
        ].map(({ label, color }) => (
          <span key={label} className={`${color}`}>● {label}</span>
        ))}
      </div>

      {/* Fixture list */}
      {Object.keys(grouped).length === 0 ? (
        <div className="text-center py-16 text-slate-500">
          <p className="text-lg">No fixtures match your filters</p>
          <p className="text-sm mt-1">Try widening the confidence range or showing all leagues</p>
        </div>
      ) : (
        Object.entries(grouped)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([date, dayFixtures]) => (
            <section key={date}>
              <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2 mt-4">
                <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
                {format(new Date(date + 'T12:00:00'), 'EEEE, MMMM d')}
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
    
