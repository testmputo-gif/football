// src/pages/HomePage.jsx
import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { getTodaysPredictions, getTopPicks, getAccuracyData } from '../services/data'
import PredictionCard from '../components/PredictionCard'
import { ConfidenceMeter } from '../components/ui'
import { Spinner } from '../components/ui'
import { TrendingUp, Target, Zap, BarChart2 } from 'lucide-react'
import { format } from 'date-fns'

function StatCard({ icon: Icon, label, value, color }) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 flex items-center gap-3">
      <div className={`p-2.5 rounded-lg ${color}`}><Icon size={18} className="text-white" /></div>
      <div>
        <p className="text-slate-400 text-xs">{label}</p>
        <p className="text-white font-bold text-lg">{value}</p>
      </div>
    </div>
  )
}

export default function HomePage() {
  const [data, setData] = useState(null)
  const [topPicks, setTopPicks] = useState([])
  const [accuracy, setAccuracy] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getTodaysPredictions(),
      getTopPicks('over25', 68, 8),
      getAccuracyData(),
    ]).then(([pred, picks, acc]) => {
      setData(pred)
      setTopPicks(picks || [])
      setAccuracy(acc)
    }).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner />

  const fixtures = data?.fixtures || []
  const featured = fixtures.filter(f => f.is_featured).slice(0, 6)
  const generatedAt = data?.generated_at ? format(new Date(data.generated_at), 'HH:mm, d MMM') : null

  const o25Stats = accuracy?.by_market?.over25
  const accuracyPct = o25Stats?.total > 0
    ? `${Math.round(o25Stats.correct / o25Stats.total * 100)}%`
    : 'Tracking...'

  return (
    <div className="space-y-10">
      {/* Hero */}
      <section className="text-center py-8">
        <h1 className="text-4xl font-bold text-white mb-3">
          <span className="text-emerald-400">Statistical</span> Football Predictions
        </h1>
        <p className="text-slate-400 max-w-xl mx-auto">
          Dixon-Coles Poisson model + XGBoost machine learning.
          Fresh predictions every morning. Zero guesswork.
        </p>
        {generatedAt && (
          <p className="text-slate-600 text-xs mt-2">Last updated: {generatedAt} UTC</p>
        )}
      </section>

      {/* Stats strip */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard icon={Target}     label="Today's fixtures" value={fixtures.length}   color="bg-emerald-600" />
        <StatCard icon={TrendingUp} label="Predictions made"  value={fixtures.filter(f => !f.no_prediction_reason).length} color="bg-blue-600" />
        <StatCard icon={Zap}        label="High confidence"   value={topPicks.length}   color="bg-purple-600" />
        <StatCard icon={BarChart2}  label="Over 2.5 accuracy" value={accuracyPct}       color="bg-orange-600" />
      </section>

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
