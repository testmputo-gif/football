// src/pages/FixturesPage.jsx
import { useState, useEffect } from 'react'
import { getTodaysPredictions } from '../services/data'
import PredictionCard from '../components/PredictionCard'
import { Spinner, Empty } from '../components/ui'
import { format } from 'date-fns'

const FILTERS = ['All', 'Has Prediction', 'High Confidence (≥70%)']

export default function FixturesPage() {
  const [fixtures, setFixtures] = useState([])
  const [filter, setFilter] = useState('All')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getTodaysPredictions().then(d => {
      setFixtures(d?.fixtures || [])
    }).finally(() => setLoading(false))
  }, [])

  const filtered = fixtures.filter(f => {
    if (filter === 'Has Prediction') return !f.no_prediction_reason
    if (filter === 'High Confidence (≥70%)') {
      const p = f.predictions || {}
      return Object.values(p).some(m => m.confidence >= 70)
    }
    return true
  })

  const grouped = filtered.reduce((acc, f) => {
    const key = f.fixture_date?.split('T')[0]
    if (!acc[key]) acc[key] = []
    acc[key].push(f)
    return acc
  }, {})

  if (loading) return <Spinner />

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-white">Upcoming Fixtures</h1>
        <select value={filter} onChange={e => setFilter(e.target.value)}
          className="bg-slate-700 text-slate-300 text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none focus:border-emerald-500">
          {FILTERS.map(f => <option key={f}>{f}</option>)}
        </select>
      </div>

      {Object.keys(grouped).length === 0
        ? <Empty message="No fixtures found for selected filter" />
        : Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).map(([date, dayFixtures]) => (
          <section key={date}>
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
              {format(new Date(date), 'EEEE, MMMM d')}
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
