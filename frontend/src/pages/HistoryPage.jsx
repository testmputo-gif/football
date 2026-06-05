// src/pages/HistoryPage.jsx
// Shows past fixtures with predictions AND actual results.
// Self-scoring: compares what was predicted vs what actually happened.

import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { getAllFixtures, getAccuracyData, getBestConfidence, getConfidenceLabel } from '../services/data'
import { Spinner } from '../components/ui'
import { format } from 'date-fns'
import { CheckCircle2, XCircle, MinusCircle, BarChart2, TrendingUp } from 'lucide-react'

// ── Score pill ─────────────────────────────────────────────────────────────────
function ResultPill({ correct }) {
  if (correct === true)  return <span className="flex items-center gap-1 text-xs text-emerald-400 font-bold"><CheckCircle2 size={12} />CORRECT</span>
  if (correct === false) return <span className="flex items-center gap-1 text-xs text-red-400 font-bold"><XCircle size={12} />WRONG</span>
  return <span className="flex items-center gap-1 text-xs text-slate-500"><MinusCircle size={12} />N/A</span>
}

// ── Market result row ──────────────────────────────────────────────────────────
function MarketResult({ label, result }) {
  if (!result) return null
  const { pick, confidence, correct, actual } = result
  if (!pick || pick === 'no_pick') return null
  return (
    <div className="flex items-center justify-between py-1 text-xs">
      <span className="text-slate-500 w-24">{label}</span>
      <span className="text-white font-medium uppercase">{pick}</span>
      <span className="text-slate-500">{confidence != null ? `${Math.round(confidence)}%` : '—'}</span>
      {actual != null && <span className="text-slate-600">actual: <span className="text-slate-400">{actual}</span></span>}
      <ResultPill correct={correct} />
    </div>
  )
}

// ── History fixture card ───────────────────────────────────────────────────────
function HistoryCard({ fixture }) {
  const [expanded, setExpanded] = useState(false)
  const scored    = fixture._scored
  const hasPred   = !!scored?.results || !!Object.keys(fixture.predictions || {}).length
  const bestConf  = getBestConfidence(fixture)
  const { color } = getConfidenceLabel(bestConf)

  // Overall correct count from scored results
  const scoreStats = useMemo(() => {
    if (!scored?.results) return null
    const vals = Object.values(scored.results).filter(r => r?.correct != null)
    const correct = vals.filter(r => r.correct === true).length
    return { correct, total: vals.length }
  }, [scored])

  let dateStr = '—'
  try { dateStr = format(new Date(fixture.fixture_date), 'EEE d MMM · HH:mm') } catch (_) {}

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
      <button onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-750 text-left transition-colors"
      >
        {/* Confidence */}
        <div className={`text-lg font-bold w-14 shrink-0 text-center ${color}`}>
          {bestConf != null ? `${Math.round(bestConf)}%` : '—'}
        </div>

        {/* Match info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            {fixture.league_logo && (
              <img src={fixture.league_logo} alt="" className="w-3 h-3 object-contain"
                onError={e => { e.target.style.display='none' }} />
            )}
            <span className="text-xs text-slate-500">{fixture.league_name} · {dateStr}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm text-white">{fixture.home_team_name}</span>
            {scored?.actual_score ? (
              <span className="text-emerald-400 font-bold text-sm">{scored.actual_score}</span>
            ) : (
              <span className="text-slate-500 text-xs">vs</span>
            )}
            <span className="font-semibold text-sm text-white">{fixture.away_team_name}</span>
          </div>
        </div>

        {/* Score summary */}
        <div className="shrink-0 text-right">
          {scoreStats ? (
            <div className={`text-sm font-bold ${scoreStats.correct === scoreStats.total ? 'text-emerald-400' : scoreStats.correct === 0 ? 'text-red-400' : 'text-yellow-400'}`}>
              {scoreStats.correct}/{scoreStats.total}
              <div className="text-xs font-normal text-slate-500">markets correct</div>
            </div>
          ) : hasPred ? (
            <span className="text-xs text-slate-500">Predicted · pending result</span>
          ) : (
            <span className="text-xs text-slate-600">No prediction</span>
          )}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-slate-700 px-4 py-3 bg-slate-900/30 space-y-1">
          {scored?.results ? (
            <>
              <MarketResult label="Winner"    result={scored.results.winner} />
              <MarketResult label="Over 2.5"  result={scored.results.over25} />
              <MarketResult label="BTTS"      result={scored.results.btts} />
              <MarketResult label="Corners"   result={scored.results.corners} />
              <MarketResult label="Cards"     result={scored.results.cards} />
            </>
          ) : fixture.predictions && Object.keys(fixture.predictions).length > 0 ? (
            Object.entries(fixture.predictions).map(([mkt, p]) =>
              p?.pick && p.pick !== 'no_pick' ? (
                <div key={mkt} className="flex items-center justify-between py-1 text-xs">
                  <span className="text-slate-500 w-24">{mkt.replace(/_/g,' ')}</span>
                  <span className="text-white font-medium uppercase">{p.pick}</span>
                  <span className="text-slate-500">{p.confidence != null ? `${Math.round(p.confidence)}%` : '—'}</span>
                  <span className="text-slate-600 text-xs">Awaiting result</span>
                </div>
              ) : null
            )
          ) : (
            <p className="text-slate-600 text-xs py-2">No predictions were made for this fixture.</p>
          )}
          <div className="pt-2">
            <Link to={`/fixture/${encodeURIComponent(fixture.id)}`}
              className="text-xs text-emerald-400 hover:underline">
              Full analysis →
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Accuracy summary bar ───────────────────────────────────────────────────────
function AccuracySummary({ accuracy }) {
  if (!accuracy?.by_market) return null
  const markets = [
    { key: 'winner', label: 'Match Winner' },
    { key: 'over25', label: 'Over 2.5' },
    { key: 'btts',   label: 'BTTS' },
    { key: 'corners', label: 'Corners' },
    { key: 'cards',  label: 'Cards' },
  ]
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 mb-4">
      <div className="flex items-center gap-2 mb-4">
        <BarChart2 size={15} className="text-emerald-400" />
        <h2 className="text-sm font-bold text-white uppercase tracking-wide">Self-Scoring Summary</h2>
        <span className="text-xs text-slate-500 ml-auto">{accuracy.total_evaluated} total evaluated</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {markets.map(({ key, label }) => {
          const m = accuracy.by_market[key]
          if (!m || m.total === 0) return (
            <div key={key} className="text-center bg-slate-900/50 rounded-lg p-3">
              <p className="text-slate-600 text-xs">{label}</p>
              <p className="text-slate-600 text-lg font-bold">—</p>
              <p className="text-slate-700 text-xs">no data</p>
            </div>
          )
          const pct = Math.round(m.correct / m.total * 100)
          const color = pct >= 70 ? 'text-emerald-400' : pct >= 50 ? 'text-yellow-400' : 'text-red-400'
          return (
            <div key={key} className="text-center bg-slate-900/50 rounded-lg p-3">
              <p className="text-slate-400 text-xs mb-1">{label}</p>
              <p className={`text-2xl font-bold ${color}`}>{pct}%</p>
              <p className="text-slate-500 text-xs">{m.correct}/{m.total}</p>
              {/* Mini bar */}
              <div className="mt-2 h-1 bg-slate-700 rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${pct >= 70 ? 'bg-emerald-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-500'}`}
                  style={{ width: `${pct}%` }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function HistoryPage() {
  const [past, setPast]         = useState([])
  const [accuracy, setAccuracy] = useState(null)
  const [loading, setLoading]   = useState(true)
  const [filter, setFilter]     = useState('all') // all | scored | unscored | predicted

  useEffect(() => {
    Promise.all([getAllFixtures(), getAccuracyData()]).then(([d, acc]) => {
      setPast(d.past || [])
      setAccuracy(acc)
    }).finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    switch (filter) {
      case 'scored':    return past.filter(f => f._scored)
      case 'unscored':  return past.filter(f => !f._scored)
      case 'predicted': return past.filter(f => getBestConfidence(f) != null)
      default:          return past
    }
  }, [past, filter])

  // Group by date
  const grouped = useMemo(() => {
    return filtered.reduce((acc, f) => {
      const key = f.fixture_date?.split('T')[0] || 'Unknown'
      if (!acc[key]) acc[key] = []
      acc[key].push(f)
      return acc
    }, {})
  }, [filtered])

  if (loading) return <Spinner />

  const scoredCount    = past.filter(f => f._scored).length
  const predictedCount = past.filter(f => getBestConfidence(f) != null).length

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-white">Prediction History</h1>
        <p className="text-slate-500 text-sm mt-0.5">
          Past fixtures · cross-referenced against actual results · self-scoring
        </p>
      </div>

      {/* Accuracy summary */}
      <AccuracySummary accuracy={accuracy} />

      {/* Stats strip */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Past fixtures',  value: past.length,       color: 'text-slate-300' },
          { label: 'With predictions', value: predictedCount,  color: 'text-emerald-400' },
          { label: 'Self-scored',    value: scoredCount,        color: 'text-blue-400' },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-slate-800 border border-slate-700 rounded-xl p-3 text-center">
            <p className={`text-2xl font-bold ${color}`}>{value}</p>
            <p className="text-xs text-slate-500">{label}</p>
          </div>
        ))}
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 bg-slate-800 border border-slate-700 rounded-xl p-1 w-fit">
        {[
          { key: 'all',       label: `All (${past.length})` },
          { key: 'predicted', label: `Predicted (${predictedCount})` },
          { key: 'scored',    label: `Scored (${scoredCount})` },
          { key: 'unscored',  label: `Pending (${past.length - scoredCount})` },
        ].map(({ key, label }) => (
          <button key={key} onClick={() => setFilter(key)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
              filter === key ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Fixture list */}
      {Object.keys(grouped).length === 0 ? (
        <div className="text-center py-16 text-slate-500">
          <p>No past fixtures found in the last 30 days.</p>
        </div>
      ) : (
        Object.entries(grouped)
          .sort(([a], [b]) => b.localeCompare(a)) // newest first
          .map(([date, dayFixtures]) => (
            <section key={date}>
              <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2 mt-4">
                <span className="w-2 h-2 rounded-full bg-slate-500 inline-block" />
                {format(new Date(date + 'T12:00:00'), 'EEEE, MMMM d')}
                <span className="text-slate-600 normal-case font-normal">
                  · {dayFixtures.filter(f => f._scored).length}/{dayFixtures.length} scored
                </span>
              </h2>
              <div className="space-y-2">
                {dayFixtures.map(f => <HistoryCard key={f.id} fixture={f} />)}
              </div>
            </section>
          ))
      )}
    </div>
  )
            }
            
