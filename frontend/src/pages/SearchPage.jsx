// src/pages/SearchPage.jsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { searchFixtures } from '../services/data'
import { safeFormat } from '../services/data'
import { Search, Loader } from 'lucide-react'

export default function SearchPage() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)

  const handleSearch = async (e) => {
    e.preventDefault()
    if (q.length < 2) return
    setLoading(true)
    const found = await searchFixtures(q)
    setResults(found)
    setLoading(false)
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-white">Search Fixtures</h1>
      <form onSubmit={handleSearch} className="flex gap-2">
        <input type="text" value={q} onChange={e => setQ(e.target.value)}
          placeholder="Search by team name, e.g. Arsenal, Bayern..."
          className="flex-1 bg-slate-800 border border-slate-600 text-white rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-emerald-500"
        />
        <button type="submit"
          className="bg-emerald-600 hover:bg-emerald-500 text-white px-5 py-3 rounded-xl flex items-center gap-2 transition-colors">
          {loading ? <Loader size={16} className="animate-spin" /> : <Search size={16} />}
          Search
        </button>
      </form>

      {results !== null && (
        <div className="space-y-3">
          <p className="text-slate-400 text-sm">{results.length} fixture{results.length !== 1 ? 's' : ''} found</p>
          {results.length === 0
            ? <p className="text-slate-500 text-center py-10">No fixtures matched "{q}"</p>
            : results.map(f => (
              <Link key={f.id} to={`/fixture/${f.id}`}
                className="flex items-center justify-between bg-slate-800 border border-slate-700 hover:border-emerald-500/50 rounded-xl px-4 py-3 transition-all">
                <div>
                  <p className="text-white font-medium text-sm">{f.home_team_name} vs {f.away_team_name}</p>
                  <p className="text-slate-500 text-xs mt-0.5">
                    {f.league_name} · {f.fixture_date ? safeFormat(f.fixture_date, 'datetime') : '—'}
                  </p>
                </div>
                {!f.no_prediction_reason && (
                  <span className="text-xs bg-emerald-600/20 text-emerald-400 border border-emerald-600/30 px-2 py-0.5 rounded-full">
                    Predicted
                  </span>
                )}
              </Link>
            ))
          }
        </div>
      )}
    </div>
  )
}
