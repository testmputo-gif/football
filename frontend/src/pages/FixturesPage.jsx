// src/pages/FixturesPage.jsx — Smart filtering, sorting & live pipeline stats
import { useState, useEffect, useMemo } from 'react'
import { getTodaysPredictions, getModelMeta, getAccuracyData } from '../services/data'
import PredictionCard from '../components/PredictionCard'
import { Spinner, Empty } from '../components/ui'
import { format } from 'date-fns'
import { SlidersHorizontal, ChevronDown, ChevronUp, Activity, Target, Cpu, CheckCircle } from 'lucide-react'

// ── Pipeline Stats Banner ──────────────────────────────────────────────────────
function PipelineBanner({ data, meta, accuracy }) {
  const [expanded, setExpanded] = useState(false)

  const fixtures = data?.fixtures || []
  const total = fixtures.length
  const predicted = fixtures.filter(f => !f.no_prediction_reason).length
  const skipped = total - predicted
  const highConf = fixtures.filter(f => {
    const p = f.predictions || {}
    return Object.values(p).some(m => m?.confidence >= 75 && m?.pick && m.pick !== 'no_pick')
  }).length
  const mlActive = data?.ml_active ?? false
  const modelVer = data?.model_version ?? meta?.version ?? '—'
  const generatedAt = data?.generated_at ? format(new Date(data.generated_at), 'HH:mm, d MMM yyyy') : '—'

  const leagues = [...new Set(fixtures.map(f => f.league_name).filter(Boolean))]
  const o25Acc = accuracy?.by_market?.over25
  const winnerAcc = accuracy?.by_market?.winner
  const totalEval = accuracy?.total_evaluated ?? 0

  const statItems = [
    { icon: Activity, label: 'Fixtures today',    value: total,          color: 'text-slate-300' },
    { icon: Target,   label: 'Predictions made',  value: predicted,      color: 'text-emerald-400' },
    { icon: Target,   label: 'Skipped (no data)', value: skipped,        color: 'text-amber-400' },
    { icon: Target,   label: '≥75% confidence',   value: highConf,       color: 'text-yellow-400' },
  ]

  return (
    <div className="bg-slate-800/80 border border-slate-700 rounded-xl overflow-hidden mb-6">
      {/* Always-visible summary row */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-5 py-3 hover:bg-slate-700/40 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Cpu size={15} className="text-emerald-400" />
          <span className="text-sm font-medium text-white">Pipeline status</span>
          <span className="text-xs text-slate-500">· updated {generatedAt} UTC</span>
          {mlActive
            ? <span className="text-xs bg-emerald-600/30 text-emerald-300 border border-emerald-600/40 px-2 py-0.5 rounded-full">ML active</span>
            : <span className="text-xs bg-slate-700 text-slate-400 border border-slate-600 px-2 py-0.5 rounded-full">Dixon-Coles only</span>
          }
        </div>
        <div className="flex items-center gap-3">
          <span className="text-emerald-400 text-sm font-bold">{predicted}/{total} predicted</span>
          {expanded ? <ChevronUp size={15} className="text-slate-400" /> : <ChevronDown size={15} className="text-slate-400" />}
        </div>
      </button>

      {/* Expanded detail panel */}
      {expanded && (
        <div className="border-t border-slate-700 px-5 py-4 space-y-4">
          {/* 4-stat grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {statItems.map(({ icon: Icon, label, value, color }) => (
              <div key={label} className="bg-slate-900/50 rounded-lg px-3 py-2">
                <p className="text-slate-500 text-xs mb-0.5">{label}</p>
                <p className={`font-bold text-xl ${color}`}>{value}</p>
              </div>
            ))}
          </div>

          {/* Model info row */}
          <div className="flex flex-wrap gap-4 text-xs text-slate-400">
            <span>
              <span className="text-slate-500">Model:</span>{' '}
              <span className="text-white">{modelVer}</span>
            </span>
            <span>
              <span className="text-slate-500">Engine:</span>{' '}
              <span className="text-white">{mlActive ? 'Dixon-Coles + XGBoost/LightGBM ensemble' : 'Dixon-Coles Poisson (pure statistical)'}</span>
            </span>
            {meta?.training_samples > 0 && (
              <span>
                <span className="text-slate-500">Trained on:</span>{' '}
                <span className="text-white">{meta.training_samples.toLocaleString()} matches</span>
              </span>
            )}
            <span>
              <span className="text-slate-500">Evaluated all-time:</span>{' '}
              <span className="text-white">{totalEval} predictions</span>
            </span>
          </div>

          {/* Accuracy quick-glance */}
          {(o25Acc || winnerAcc) && (
            <div className="flex flex-wrap gap-3">
              {winnerAcc?.total > 0 && (
                <div className="flex items-center gap-1.5 bg-blue-900/30 border border-blue-700/30 rounded-lg px-3 py-1.5">
                  <CheckCircle size={12} className="text-blue-400" />
                  <span className="text-xs text-blue-300">
                    Winner: <strong>{Math.round(winnerAcc.correct / winnerAcc.total * 100)}%</strong>
                    <span className="text-blue-500 ml-1">({winnerAcc.total} picks)</span>
                  </span>
                </div>
              )}
              {o25Acc?.total > 0 && (
                <div className="flex items-center gap-1.5 bg-emerald-900/30 border border-emerald-700/30 rounded-lg px-3 py-1.5">
                  <CheckCircle size={12} className="text-emerald-400" />
                  <span className="text-xs text-emerald-300">
                    Over 2.5: <strong>{Math.round(o25Acc.correct / o25Acc.total * 100)}%</strong>
                    <span className="text-emerald-600 ml-1">({o25Acc.total} picks)</span>
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Active leagues */}
          {leagues.length > 0 && (
            <div>
              <p className="text-xs text-slate-500 mb-1.5">Active leagues today ({leagues.length})</p>
              <div className="flex flex-wrap gap-1.5">
                {leagues.map(l => (
                  <span key={l} className="text-xs bg-slate-700/60 text-slate-400 border border-slate-600/50 px-2 py-0.5 rounded">{l}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────
const MARKETS = ['any', 'winner', 'over25', 'over15', 'over35', 'btts', 'corners_85', 'cards_35', 'fh_over05']
const MARKET_LABELS = {
  any: 'Any market', winner: 'Match winner', over25: 'Over 2.5 goals',
  over15: 'Over 1.5 goals', over35: 'Over 3.5 goals', btts: 'BTTS',
  corners_85: 'Corners O8.5', cards_35: 'Cards O3.5', fh_over05: '1st half O0.5',
}

export default function FixturesPage() {
  const [data, setData]         = useState(null)
  const [meta, setMeta]         = useState(null)
  const [accuracy, setAccuracy] = useState(null)
  const [loading, setLoading]   = useState(true)

  // Filter & sort controls
  const [market, setMarket]           = useState('any')
  const [minConf, setMinConf]         = useState(50)
  const [maxConf, setMaxConf]         = useState(100)
  const [limitN, setLimitN]           = useState(0)      // 0 = no limit
  const [sortBy, setSortBy]           = useState('confidence') // confidence | date | league
  const [onlyPredicted, setOnlyPredicted] = useState(false)
  const [showFilters, setShowFilters] = useState(false)

  useEffect(() => {
    Promise.all([getTodaysPredictions(), getModelMeta(), getAccuracyData()])
      .then(([d, m, a]) => { setData(d); setMeta(m); setAccuracy(a) })
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    const fixtures = data?.fixtures || []

    let result = fixtures.filter(f => {
      // Must have a prediction if toggle on
      if (onlyPredicted && f.no_prediction_reason) return false

      const preds = f.predictions || {}

      // Market filter
      if (market === 'any') {
        // confidence range applies across any market
        const confs = Object.values(preds)
          .map(m => m?.confidence)
          .filter(c => c != null)
        if (confs.length === 0) return minConf <= 0
        const best = Math.max(...confs)
        return best >= minConf && best <= maxConf
      } else {
        const p = preds[market]
        if (!p || p.pick === 'no_pick' || p.pick == null) return false
        if (p.confidence == null) return false
        return p.confidence >= minConf && p.confidence <= maxConf
      }
    })

    // Sort
    result = [...result].sort((a, b) => {
      if (sortBy === 'confidence') {
        const getConf = f => {
          const preds = f.predictions || {}
          if (market !== 'any') return preds[market]?.confidence || 0
          return Math.max(0, ...Object.values(preds).map(p => p?.confidence || 0))
        }
        return getConf(b) - getConf(a)
      }
      if (sortBy === 'date') return (a.fixture_date || '').localeCompare(b.fixture_date || '')
      if (sortBy === 'league') return (a.league_name || '').localeCompare(b.league_name || '')
      return 0
    })

    // Limit
    if (limitN > 0) result = result.slice(0, limitN)

    return result
  }, [data, market, minConf, maxConf, limitN, sortBy, onlyPredicted])

  // Group by date for display
  const grouped = useMemo(() => {
    return filtered.reduce((acc, f) => {
      const key = f.fixture_date?.split('T')[0] || 'Unknown'
      if (!acc[key]) acc[key] = []
      acc[key].push(f)
      return acc
    }, {})
  }, [filtered])

  if (loading) return <Spinner />

  const totalFixtures = data?.fixtures?.length || 0
  const predFixtures  = (data?.fixtures || []).filter(f => !f.no_prediction_reason).length

  return (
    <div className="space-y-4">
      {/* Pipeline banner */}
      <PipelineBanner data={data} meta={meta} accuracy={accuracy} />

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Fixtures & Predictions</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Showing <span className="text-white font-medium">{filtered.length}</span> of{' '}
            {totalFixtures} fixtures · {predFixtures} have predictions
          </p>
        </div>
        <button
          onClick={() => setShowFilters(f => !f)}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
            showFilters
              ? 'bg-emerald-600 border-emerald-500 text-white'
              : 'bg-slate-800 border-slate-600 text-slate-300 hover:border-emerald-500/50'
          }`}
        >
          <SlidersHorizontal size={15} />
          Filters {showFilters ? '▲' : '▼'}
        </button>
      </div>

      {/* Filter panel */}
      {showFilters && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">

            {/* Market */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5 font-medium uppercase tracking-wide">Market</label>
              <select
                value={market}
                onChange={e => setMarket(e.target.value)}
                className="w-full bg-slate-700 text-white text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none focus:border-emerald-500"
              >
                {MARKETS.map(m => <option key={m} value={m}>{MARKET_LABELS[m]}</option>)}
              </select>
            </div>

            {/* Sort by */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5 font-medium uppercase tracking-wide">Sort by</label>
              <select
                value={sortBy}
                onChange={e => setSortBy(e.target.value)}
                className="w-full bg-slate-700 text-white text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none focus:border-emerald-500"
              >
                <option value="confidence">Confidence (highest first)</option>
                <option value="date">Kick-off time</option>
                <option value="league">League name</option>
              </select>
            </div>

            {/* Show N */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5 font-medium uppercase tracking-wide">
                Show top N <span className="normal-case text-slate-500">(0 = all)</span>
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0} max={200} step={5}
                  value={limitN}
                  onChange={e => setLimitN(Number(e.target.value))}
                  className="w-24 bg-slate-700 text-white text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none focus:border-emerald-500"
                />
                <div className="flex gap-1 flex-wrap">
                  {[5, 10, 15, 20, 25].map(n => (
                    <button key={n} onClick={() => setLimitN(n)}
                      className={`text-xs px-2 py-1 rounded border transition-colors ${
                        limitN === n
                          ? 'bg-emerald-600 border-emerald-500 text-white'
                          : 'bg-slate-700 border-slate-600 text-slate-400 hover:border-emerald-500/50'
                      }`}
                    >Top {n}</button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Confidence range */}
          <div>
            <label className="block text-xs text-slate-400 mb-2 font-medium uppercase tracking-wide">
              Confidence range: <span className="text-white normal-case">{minConf}% – {maxConf}%</span>
            </label>
            <div className="flex flex-wrap gap-2 mb-3">
              {[
                { label: '50–100 (all)',   min: 50, max: 100 },
                { label: '60–100',         min: 60, max: 100 },
                { label: '70–100',         min: 70, max: 100 },
                { label: '80–100 ★',       min: 80, max: 100 },
                { label: '60–70',          min: 60, max: 70  },
                { label: '70–80',          min: 70, max: 80  },
                { label: '80–90',          min: 80, max: 90  },
                { label: '90–100',         min: 90, max: 100 },
              ].map(({ label, min, max }) => (
                <button key={label} onClick={() => { setMinConf(min); setMaxConf(max) }}
                  className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                    minConf === min && maxConf === max
                      ? 'bg-emerald-600 border-emerald-500 text-white'
                      : 'bg-slate-700 border-slate-600 text-slate-400 hover:border-emerald-500/50'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {/* Dual slider (min) */}
            <div className="flex items-center gap-4">
              <div className="flex-1 space-y-1">
                <div className="flex justify-between text-xs text-slate-500">
                  <span>Min {minConf}%</span>
                </div>
                <input type="range" min={50} max={100} step={1} value={minConf}
                  onChange={e => setMinConf(Math.min(Number(e.target.value), maxConf - 1))}
                  className="w-full accent-emerald-500"
                />
              </div>
              <div className="flex-1 space-y-1">
                <div className="flex justify-between text-xs text-slate-500">
                  <span>Max {maxConf}%</span>
                </div>
                <input type="range" min={50} max={100} step={1} value={maxConf}
                  onChange={e => setMaxConf(Math.max(Number(e.target.value), minConf + 1))}
                  className="w-full accent-emerald-500"
                />
              </div>
            </div>
          </div>

          {/* Only predicted toggle */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => setOnlyPredicted(p => !p)}
              className={`relative w-10 h-6 rounded-full border transition-colors ${
                onlyPredicted ? 'bg-emerald-600 border-emerald-500' : 'bg-slate-700 border-slate-600'
              }`}
            >
              <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
                onlyPredicted ? 'translate-x-4' : 'translate-x-0.5'
              }`} />
            </button>
            <span className="text-sm text-slate-300">Only show fixtures with predictions</span>
          </div>

          {/* Reset */}
          <button
            onClick={() => { setMarket('any'); setMinConf(50); setMaxConf(100); setLimitN(0); setSortBy('confidence'); setOnlyPredicted(false) }}
            className="text-xs text-slate-500 hover:text-slate-300 underline"
          >
            Reset all filters
          </button>
        </div>
      )}

      {/* Results summary pill */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm text-slate-500">
          {filtered.length === 0 ? 'No matches' : `${filtered.length} match${filtered.length !== 1 ? 'es' : ''}`}
          {limitN > 0 && <span className="text-emerald-400"> (top {limitN})</span>}
          {market !== 'any' && <span className="text-emerald-400"> · {MARKET_LABELS[market]}</span>}
          {(minConf > 50 || maxConf < 100) && <span className="text-yellow-400"> · {minConf}–{maxConf}%</span>}
        </span>
      </div>

      {/* Fixture grid */}
      {Object.keys(grouped).length === 0
        ? <Empty message="No fixtures match your filters. Try widening the confidence range or selecting a different market." />
        : Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).map(([date, dayFixtures]) => (
          <section key={date}>
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
              {format(new Date(date + 'T12:00:00'), 'EEEE, MMMM d')}
              <span className="text-slate-600 normal-case">· {dayFixtures.length} match{dayFixtures.length !== 1 ? 'es' : ''}</span>
            </h2>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
              {dayFixtures.map(f => <PredictionCard key={f.id} fixture={f} />)}
            </div>
          </section>
        ))
      }
    </div>
  )
}
