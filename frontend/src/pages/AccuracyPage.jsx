// src/pages/AccuracyPage.jsx
import { useState, useEffect } from 'react'
import { getAccuracyData, getModelMeta } from '../services/data'
import { Spinner } from '../components/ui'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ReferenceLine, Cell, ResponsiveContainer } from 'recharts'

const MARKET_LABELS = {
  winner: 'Match Winner', over25: 'Over 2.5 Goals',
  btts: 'BTTS', corners: 'Corners O/U', cards: 'Cards O/U'
}

function AccuracyCard({ market, total, correct }) {
  const pct = total > 0 ? Math.round(correct / total * 100) : null
  const color = pct >= 70 ? '#10b981' : pct >= 60 ? '#3b82f6' : '#f59e0b'
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
      <div className="flex justify-between items-center mb-2">
        <span className="text-white text-sm font-medium">{MARKET_LABELS[market] || market}</span>
        <span className="font-bold text-lg" style={{ color }}>{pct != null ? `${pct}%` : '—'}</span>
      </div>
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct || 0}%`, backgroundColor: color }} />
      </div>
      <p className="text-slate-500 text-xs mt-2">{correct || 0} correct of {total || 0}</p>
    </div>
  )
}

export default function AccuracyPage() {
  const [accuracy, setAccuracy] = useState(null)
  const [meta, setMeta] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([getAccuracyData(), getModelMeta()])
      .then(([acc, m]) => { setAccuracy(acc); setMeta(m) })
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner />

  const markets = accuracy?.by_market || {}
  const calibration = accuracy?.calibration || {}
  const recent = accuracy?.recent_results || []

  // Build calibration chart for over25 (most data)
  const calChartData = Object.values(calibration)
    .filter(c => c.market === 'over25' && c.total >= 10)
    .sort((a, b) => a.bucket - b.bucket)
    .map(c => ({
      bucket: `${c.bucket}%`,
      actual: Math.round(c.correct / c.total * 100),
      expected: c.bucket,
      n: c.total,
    }))

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white mb-1">Track Record</h1>
        <p className="text-slate-400 text-sm">
          Live accuracy across all markets. Updated daily after results.
          {meta?.ml_available && <span className="ml-2 text-emerald-400">· ML active ({meta.training_samples} training matches)</span>}
        </p>
      </div>

      {/* Accuracy grid */}
      {Object.keys(markets).length === 0
        ? <p className="text-slate-500 text-center py-10">No predictions evaluated yet. Check back after the first match day.</p>
        : <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(markets).map(([market, data]) => (
              <AccuracyCard key={market} market={market} {...data} />
            ))}
          </div>
      }

      {/* Calibration chart */}
      {calChartData.length >= 3 && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
          <h2 className="font-bold text-white mb-1">Confidence Calibration — Over 2.5</h2>
          <p className="text-slate-500 text-xs mb-4">
            When model says 70%, does it win ~70% of the time? Bars close to diagonal = well calibrated.
          </p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={calChartData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
              <XAxis dataKey="bucket" tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 11 }} unit="%" />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                formatter={(val, name) => [`${val}%`, name === 'actual' ? 'Actual' : 'Expected']}
              />
              <ReferenceLine y={50} stroke="#334155" strokeDasharray="3 3" />
              <Bar dataKey="actual" radius={[4, 4, 0, 0]}>
                {calChartData.map((entry, i) => (
                  <Cell key={i} fill={Math.abs(entry.actual - entry.expected) <= 8 ? '#10b981' : '#f59e0b'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Recent results */}
      {recent.length > 0 && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-700">
            <h2 className="font-bold text-white">Recent Results</h2>
          </div>
          <div className="divide-y divide-slate-700/60">
            {recent.slice(0, 15).map((r, i) => {
              const o25 = r.results?.over25
              const correct = o25?.correct
              return (
                <div key={i} className="px-5 py-3 flex items-center justify-between">
                  <div className="min-w-0">
                    <p className="text-sm text-white truncate">{r.home_team} vs {r.away_team}</p>
                    <p className="text-xs text-slate-500">{r.league} · Score: {r.actual_score}</p>
                  </div>
                  <div className="flex items-center gap-2 ml-3 shrink-0">
                    {o25?.pick && o25.pick !== 'no_pick' && (
                      <span className="text-xs text-slate-400">{o25.pick} @ {o25.confidence}%</span>
                    )}
                    {correct === true && <span className="text-xs font-bold text-emerald-400">✓ Correct</span>}
                    {correct === false && <span className="text-xs font-bold text-red-400">✗ Wrong</span>}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Honesty note */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4 text-slate-400 text-sm space-y-2">
        <p><strong className="text-white">Why not 90%+ accuracy?</strong> No model achieves that in football — not betting syndicates, not AI, not anyone. Our goal is for high-confidence picks (≥75%) to be right significantly more often than chance. A well-calibrated 70% pick should win roughly 70% of the time.</p>
        <p><strong className="text-white">Only verified picks count.</strong> No-pick outcomes are excluded from accuracy stats. The model knows when to say "not enough data."</p>
      </div>
    </div>
  )
}
