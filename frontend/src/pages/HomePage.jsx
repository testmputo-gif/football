// src/pages/HomePage.jsx
import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { getAllFixtures, getAccuracyData, getBestConfidence, getConfidenceLabel, safeFormat } from '../services/data'
import { Spinner } from '../components/ui'

import { Database, Target, Zap, BarChart2, CheckCircle2, History, Calendar, TrendingUp } from 'lucide-react'

function StatCard({ icon: Icon, label, value, sub, color }) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 flex items-center gap-3">
      <div className={`p-2.5 rounded-lg ${color} shrink-0`}><Icon size={18} className="text-white" /></div>
      <div className="min-w-0">
        <p className="text-slate-400 text-xs truncate">{label}</p>
        <p className="text-white font-bold text-xl leading-tight">{value}</p>
        {sub && <p className="text-slate-500 text-xs truncate">{sub}</p>}
      </div>
    </div>
  )
}

export default function HomePage() {
  const [data, setData]       = useState({ upcoming: [], past: [], meta: {} })
  const [accuracy, setAccuracy] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([getAllFixtures(), getAccuracyData()])
      .then(([d, acc]) => { setData(d); setAccuracy(acc) })
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner />

  const { upcoming, past, meta } = data
  const predictedCount = upcoming.filter(f => getBestConfidence(f) != null).length
  const highConfCount  = upcoming.filter(f => (getBestConfidence(f) ?? 0) >= 75).length

  // Top 5 highest confidence upcoming fixtures
  const topPicks = [...upcoming]
    .filter(f => getBestConfidence(f) != null)
    .sort((a, b) => (getBestConfidence(b) ?? 0) - (getBestConfidence(a) ?? 0))
    .slice(0, 5)

  const winnerAcc = accuracy?.by_market?.winner
  const o25Acc    = accuracy?.by_market?.over25

  const generatedAt = meta?.generated_at
    ? safeFormat(meta.generated_at, 'datetime')
    : null

  return (
    <div className="space-y-10">
      {/* Hero */}
      <section className="text-center py-8 space-y-3">
        <h1 className="text-4xl font-bold text-white">
          <span className="text-emerald-400">Statistical</span> Football Analysis
        </h1>
        <p className="text-slate-400 max-w-lg mx-auto">
          Every fixture fetched from live APIs, graded by confidence level.
          Dixon-Coles Poisson model + ML ensemble. Updated daily.
        </p>
        {generatedAt && (
          <p className="text-slate-600 text-xs">Last pipeline run: {generatedAt}</p>
        )}
        <div className="flex justify-center gap-3 pt-2">
          <Link to="/fixtures"
            className="bg-emerald-600 hover:bg-emerald-500 text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors"
          >
            View All Fixtures
          </Link>
          <Link to="/history"
            className="bg-slate-700 hover:bg-slate-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors"
          >
            Prediction History
          </Link>
        </div>
      </section>

      {/* Stats strip */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard icon={Database}  label="Fixtures today"     value={upcoming.length}  sub="across all leagues"   color="bg-slate-600" />
        <StatCard icon={Target}    label="Predictions ready"  value={predictedCount}   sub={`${upcoming.length - predictedCount} building data`} color="bg-emerald-600" />
        <StatCard icon={Zap}       label="High confidence"    value={highConfCount}    sub="≥ 75% confidence"     color="bg-yellow-600" />
        <StatCard icon={History}   label="Past fixtures"      value={past.length}      sub={`${accuracy?.total_evaluated ?? 0} self-scored`} color="bg-blue-600" />
      </section>

      {/* Accuracy track record */}
      {(winnerAcc?.total > 0 || o25Acc?.total > 0) && (
        <section className="bg-slate-800/60 border border-slate-700 rounded-xl px-5 py-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <TrendingUp size={14} className="text-emerald-400" />
              <span className="text-sm font-bold text-white">Live Track Record</span>
            </div>
            <Link to="/accuracy" className="text-xs text-emerald-400 hover:underline">Full stats →</Link>
          </div>
          <div className="flex flex-wrap gap-4">
            {winnerAcc?.total > 0 && (
              <div className="flex items-center gap-2">
                <CheckCircle2 size={13} className="text-blue-400 shrink-0" />
                <span className="text-sm text-slate-300">
                  Match winner: <strong className="text-white">{Math.round(winnerAcc.correct / winnerAcc.total * 100)}%</strong>
                  <span className="text-slate-500 text-xs ml-1">({winnerAcc.total} picks)</span>
                </span>
              </div>
            )}
            {o25Acc?.total > 0 && (
              <div className="flex items-center gap-2">
                <CheckCircle2 size={13} className="text-emerald-400 shrink-0" />
                <span className="text-sm text-slate-300">
                  Over 2.5 goals: <strong className="text-white">{Math.round(o25Acc.correct / o25Acc.total * 100)}%</strong>
                  <span className="text-slate-500 text-xs ml-1">({o25Acc.total} picks)</span>
                </span>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Top picks */}
      {topPicks.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold text-white">🔥 Top Confidence Picks</h2>
            <Link to="/fixtures" className="text-sm text-emerald-400 hover:underline">All fixtures →</Link>
          </div>
          <div className="space-y-2">
            {topPicks.map(f => {
              const conf = getBestConfidence(f)
              const { color, label } = getConfidenceLabel(conf)
              const pred = f.predictions || {}
              const bestMkt = Object.entries(pred)
                .filter(([, p]) => p?.confidence != null && p?.pick && p.pick !== 'no_pick')
                .sort(([, a], [, b]) => b.confidence - a.confidence)[0]

              return (
                <Link key={f.id} to={`/fixture/${encodeURIComponent(f.id)}`}
                  className="flex items-center gap-4 bg-slate-800 border border-slate-700 hover:border-emerald-500/50 rounded-xl px-4 py-3 transition-all"
                >
                  <div className={`text-xl font-bold w-14 text-center shrink-0 ${color}`}>
                    {Math.round(conf)}%
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-white font-medium text-sm truncate">
                      {f.home_team_name} <span className="text-slate-500">vs</span> {f.away_team_name}
                    </p>
                    <p className="text-slate-500 text-xs">{f.league_name}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    {bestMkt && (
                      <p className="text-emerald-400 text-xs font-medium uppercase">{bestMkt[1].pick}</p>
                    )}
                    <p className={`text-xs ${color}`}>{label}</p>
                  </div>
                </Link>
              )
            })}
          </div>
        </section>
      )}

      {/* Quick nav cards */}
      <section className="grid md:grid-cols-2 gap-4">
        <Link to="/fixtures"
          className="bg-slate-800 border border-slate-700 hover:border-emerald-500/50 rounded-xl p-5 transition-all group"
        >
          <Calendar size={20} className="text-emerald-400 mb-3" />
          <h3 className="font-bold text-white mb-1">All Fixtures</h3>
          <p className="text-slate-400 text-sm">
            {upcoming.length} upcoming fixtures graded by confidence. Filter by league, confidence range, or top N picks.
          </p>
        </Link>
        <Link to="/history"
          className="bg-slate-800 border border-slate-700 hover:border-blue-500/50 rounded-xl p-5 transition-all group"
        >
          <History size={20} className="text-blue-400 mb-3" />
          <h3 className="font-bold text-white mb-1">Prediction History</h3>
          <p className="text-slate-400 text-sm">
            {past.length} past fixtures · see predictions vs actual results · self-scoring accuracy tracking.
          </p>
        </Link>
      </section>

      <div className="bg-slate-800/40 border border-slate-700 rounded-xl p-4 text-center text-slate-500 text-xs">
        Confidence scores are statistical estimates based on historical data. Not financial advice.
      </div>
    </div>
  )
  }
                                          
