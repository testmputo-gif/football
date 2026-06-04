// src/pages/HomePage.jsx
import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { getTodaysPredictions, getTopPicks, getAccuracyData, getModelMeta } from '../services/data'
import PredictionCard from '../components/PredictionCard'
import { ConfidenceMeter } from '../components/ui'
import { Spinner } from '../components/ui'
import { TrendingUp, Target, Zap, BarChart2, Cpu, Database, RefreshCw, CheckCircle2 } from 'lucide-react'
import { format } from 'date-fns'

function StatCard({ icon: Icon, label, value, sub, color }) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 flex items-center gap-3">
      <div className={`p-2.5 rounded-lg ${color} shrink-0`}><Icon size={18} className="text-white" /></div>
      <div className="min-w-0">
        <p className="text-slate-400 text-xs truncate">{label}</p>
        <p className="text-white font-bold text-lg leading-tight">{value}</p>
        {sub && <p className="text-slate-500 text-xs truncate">{sub}</p>}
      </div>
    </div>
  )
}

// Compact engine status line shown below the hero
function EngineStatus({ data, meta }) {
  if (!data) return null
  const fixtures = data.fixtures || []
  const predicted = fixtures.filter(f => !f.no_prediction_reason).length
  const total = fixtures.length
  const mlActive = data.ml_active ?? false
  const generatedAt = data.generated_at ? format(new Date(data.generated_at), 'HH:mm UTC, d MMM') : null

  return (
    <div className="flex flex-wrap justify-center gap-x-5 gap-y-1 text-xs text-slate-500">
      <span className="flex items-center gap-1">
        <Database size={11} />
        {total} fixtures loaded · {predicted} predicted
      </span>
      <span className="flex items-center gap-1">
        <Cpu size={11} />
        {mlActive ? (
          <span className="text-emerald-400">ML ensemble active ({meta?.training_samples?.toLocaleString()} samples)</span>
        ) : (
          <span>Dixon-Coles Poisson · ML training pending</span>
        )}
      </span>
      {generatedAt && (
        <span className="flex items-center gap-1">
          <RefreshCw size={11} />
          Last run: {generatedAt}
        </span>
      )}
    </div>
  )
}

export default function HomePage() {
  const [data, setData]       = useState(null)
  const [topPicks, setTopPicks] = useState([])
  const [accuracy, setAccuracy] = useState(null)
  const [meta, setMeta]       = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getTodaysPredictions(),
      getTopPicks('over25', 68, 8),
      getAccuracyData(),
      getModelMeta(),
    ]).then(([pred, picks, acc, m]) => {
      setData(pred); setTopPicks(picks || []); setAccuracy(acc); setMeta(m)
    }).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner />

  const fixtures = data?.fixtures || []
  const featured = fixtures.filter(f => f.is_featured).slice(0, 6)
  const totalFixtures  = fixtures.length
  const predicted      = fixtures.filter(f => !f.no_prediction_reason).length
  const highConf       = fixtures.filter(f => {
    const p = f.predictions || {}
    return Object.values(p).some(m => m?.confidence >= 75 && m?.pick && m.pick !== 'no_pick')
  }).length

  const o25Stats    = accuracy?.by_market?.over25
  const winnerStats = accuracy?.by_market?.winner
  const accuracyPct = o25Stats?.total > 0
    ? `${Math.round(o25Stats.correct / o25Stats.total * 100)}%`
    : 'Tracking...'

  return (
    <div className="space-y-10">
      {/* Hero */}
      <section className="text-center py-8 space-y-3">
        <h1 className="text-4xl font-bold text-white">
          <span className="text-emerald-400">Statistical</span> Football Predictions
        </h1>
        <p className="text-slate-400 max-w-xl mx-auto">
          Dixon-Coles Poisson model + XGBoost machine learning.
          Fresh predictions every morning across 20 leagues. Zero guesswork.
        </p>
        <EngineStatus data={data} meta={meta} />
      </section>

      {/* Pipeline stats strip — 4 cards */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard icon={Database}    label="Fixtures today"    value={totalFixtures}  sub="across all leagues"  color="bg-slate-600" />
        <StatCard icon={Target}      label="Predictions made"  value={predicted}      sub={`${totalFixtures - predicted} skipped (no data)`} color="bg-emerald-600" />
        <StatCard icon={Zap}         label="High confidence"   value={highConf}       sub="≥75% confidence"     color="bg-yellow-600" />
        <StatCard icon={BarChart2}   label="Over 2.5 accuracy" value={accuracyPct}    sub={o25Stats?.total > 0 ? `${o25Stats.correct}/${o25Stats.total} correct` : 'Accumulating...'} color="bg-orange-600" />
      </section>

      {/* Accuracy quick bar (if we have data) */}
      {(winnerStats?.total > 0 || o25Stats?.total > 0) && (
        <section className="bg-slate-800/60 border border-slate-700 rounded-xl px-5 py-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide mb-3 font-medium">Live accuracy track record</p>
          <div className="flex flex-wrap gap-4">
            {winnerStats?.total > 0 && (
              <div className="flex items-center gap-2">
                <CheckCircle2 size={14} className="text-blue-400 shrink-0" />
                <span className="text-sm text-slate-300">
                  Match winner: <strong className="text-white">{Math.round(winnerStats.correct / winnerStats.total * 100)}%</strong>
                  <span className="text-slate-500 ml-1 text-xs">({winnerStats.total} evaluated)</span>
                </span>
              </div>
            )}
            {o25Stats?.total > 0 && (
              <div className="flex items-center gap-2">
                <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />
                <span className="text-sm text-slate-300">
                  Over 2.5 goals: <strong className="text-white">{Math.round(o25Stats.correct / o25Stats.total * 100)}%</strong>
                  <span className="text-slate-500 ml-1 text-xs">({o25Stats.total} evaluated)</span>
                </span>
              </div>
            )}
            <Link to="/accuracy" className="text-xs text-emerald-400 hover:underline ml-auto self-center">Full track record →</Link>
          </div>
        </section>
      )}

      {/* Top picks */}
      {topPicks.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold text-white">🔥 Top Picks Today</h2>
            <Link to="/fixtures" className="text-sm text-emerald-400 hover:underline">All fixtures →</Link>
          </div>
          <div className="space-y-2">
            {topPicks.slice(0, 6).map(f => (
              <Link key={f.id} to={`/fixture/${f.id}`}
                className="flex items-center justify-between bg-slate-800 border border-slate-700 hover:border-emerald-500/50 rounded-xl px-4 py-3 transition-all"
              >
                <div className="min-w-0">
                  <p className="text-white font-medium text-sm truncate">
                    {f.home_team_name} <span className="text-slate-500">vs</span> {f.away_team_name}
                  </p>
                  <p className="text-slate-500 text-xs">{f.league_name} · Over 2.5 Goals</p>
                </div>
                <div className="flex items-center gap-2 ml-3 shrink-0">
                  <span className="text-xs font-bold bg-emerald-600 text-white px-2 py-0.5 rounded uppercase">
                    {f.predictions?.over25?.pick || '—'}
                  </span>
                  <ConfidenceMeter value={f.predictions?.over25?.confidence} size="sm" />
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Featured matches */}
      {featured.length > 0 && (
        <section>
          <h2 className="text-xl font-bold text-white mb-4">⭐ Featured Matches</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {featured.map(f => <PredictionCard key={f.id} fixture={f} />)}
          </div>
        </section>
      )}

      {/* Disclaimer */}
      <div className="bg-slate-800/40 border border-slate-700 rounded-xl p-4 text-center text-slate-500 text-xs">
        Predictions are generated by statistical models using historical data. Confidence scores reflect
        statistical certainty, not guaranteed outcomes. Football is inherently unpredictable.
      </div>
    </div>
  )
}
