// src/pages/DataSourcesPage.jsx
// Shows live status of every data source — what pulled, how many games, any errors.
// Reads from /logs/import_report.json which step1 writes after every run.

import { useState, useEffect } from 'react'
import { safeFormat } from '../services/data'
import { Spinner } from '../components/ui'
import {
  CheckCircle2, XCircle, AlertCircle, RefreshCw,
  Database, Globe, TrendingUp, List, Clock, Layers,
} from 'lucide-react'

const BASE = import.meta.env.VITE_DATA_BASE_URL || ''

async function fetchReport() {
  try {
    const r = await fetch(`${BASE}/logs/import_report.json?t=${Date.now()}`)
    if (!r.ok) return null
    return await r.json()
  } catch {
    return null
  }
}

function SourceCard({ s }) {
  const ok      = s.status === 'ok' && (s.fixtures > 0 || s.history > 0)
  const partial = s.status === 'ok' && s.fixtures === 0 && s.history === 0
  const errored = s.status === 'error'

  const statusIcon = errored
    ? <XCircle size={16} className="text-red-400 shrink-0" />
    : partial
    ? <AlertCircle size={16} className="text-yellow-400 shrink-0" />
    : <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />

  const border = errored
    ? 'border-red-700/40'
    : partial
    ? 'border-yellow-700/40'
    : 'border-emerald-700/30'

  const SOURCE_LABELS = {
    openligadb:    'OpenLigaDB',
    thesportsdb:   'TheSportsDB',
    espn:          'ESPN API',
    football_data: 'football-data.org',
    clubelo:       'ClubElo',
  }

  const SOURCE_URLS = {
    openligadb:    'https://api.openligadb.de',
    thesportsdb:   'https://www.thesportsdb.com',
    espn:          'https://site.api.espn.com',
    football_data: 'https://www.football-data.org',
    clubelo:       'http://clubelo.com',
  }

  const name = SOURCE_LABELS[s.source] || s.source
  const url  = SOURCE_URLS[s.source]   || '#'

  return (
    <div className={`bg-slate-800 border ${border} rounded-xl p-4 space-y-3`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {statusIcon}
          <a href={url} target="_blank" rel="noreferrer"
             className="font-semibold text-white hover:text-emerald-400 transition-colors truncate">
            {name}
          </a>
          <span className="text-xs text-slate-500 bg-slate-700 px-1.5 py-0.5 rounded shrink-0">
            no key
          </span>
        </div>
        <span className={`text-xs font-medium shrink-0 ${
          errored ? 'text-red-400' : partial ? 'text-yellow-400' : 'text-emerald-400'
        }`}>
          {errored ? 'FAILED' : partial ? 'NO DATA' : 'OK'}
        </span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-slate-700/50 rounded-lg p-2.5 text-center">
          <p className="text-xl font-bold text-emerald-400">{s.fixtures ?? 0}</p>
          <p className="text-xs text-slate-400">Upcoming added</p>
        </div>
        <div className="bg-slate-700/50 rounded-lg p-2.5 text-center">
          <p className="text-xl font-bold text-blue-400">{s.history ?? 0}</p>
          <p className="text-xs text-slate-400">History added</p>
        </div>
      </div>

      {/* Leagues */}
      {s.leagues && s.leagues.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 mb-1.5">Leagues pulled:</p>
          <div className="flex flex-wrap gap-1">
            {s.leagues.slice(0, 8).map(l => (
              <span key={l}
                className="text-xs bg-slate-700 text-slate-300 px-2 py-0.5 rounded-full">
                {l}
              </span>
            ))}
            {s.leagues.length > 8 && (
              <span className="text-xs text-slate-500">+{s.leagues.length - 8} more</span>
            )}
          </div>
        </div>
      )}

      {/* Errors */}
      {s.errors && s.errors.length > 0 && (
        <div className="bg-red-900/20 border border-red-700/30 rounded-lg p-2">
          <p className="text-xs text-red-400 font-medium mb-1">
            {s.errors.length} error{s.errors.length > 1 ? 's' : ''}:
          </p>
          <ul className="space-y-0.5">
            {s.errors.slice(0, 3).map((e, i) => (
              <li key={i} className="text-xs text-red-300/70 truncate">{e}</li>
            ))}
            {s.errors.length > 3 && (
              <li className="text-xs text-slate-500">…and {s.errors.length - 3} more</li>
            )}
          </ul>
        </div>
      )}
    </div>
  )
}

function LeagueBar({ league, count, max }) {
  const pct = max > 0 ? (count / max) * 100 : 0
  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-slate-300 w-44 truncate shrink-0">{league}</span>
      <div className="flex-1 bg-slate-700 rounded-full h-1.5">
        <div
          className="bg-emerald-500 h-1.5 rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-slate-400 w-6 text-right shrink-0">{count}</span>
    </div>
  )
}

export default function DataSourcesPage() {
  const [report,   setReport]   = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [lastFetch, setLastFetch] = useState(null)

  const load = () => {
    setLoading(true)
    fetchReport()
      .then(r => { setReport(r); setLastFetch(new Date()) })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  if (loading) return <Spinner />

  if (!report) {
    return (
      <div className="text-center py-20 space-y-4">
        <Database size={40} className="text-slate-600 mx-auto" />
        <p className="text-slate-400 font-medium">No import report found yet</p>
        <p className="text-slate-500 text-sm max-w-sm mx-auto">
          The import report is generated when the pipeline runs.
          Trigger a manual run from GitHub Actions to populate this page.
        </p>
      </div>
    )
  }

  const sources = report.sources || []
  const okCount      = sources.filter(s => s.status === 'ok' && (s.fixtures > 0 || s.history > 0)).length
  const partialCount = sources.filter(s => s.status === 'ok' && s.fixtures === 0 && s.history === 0).length
  const failCount    = sources.filter(s => s.status === 'error').length

  const leagueEntries = Object.entries(report.upcoming_by_league || {})
    .sort((a, b) => b[1] - a[1])
  const maxLeagueCount = leagueEntries[0]?.[1] || 1

  const sourceEntries = Object.entries(report.upcoming_by_source || {})
    .sort((a, b) => b[1] - a[1])

  const genAt = report.generated_at
    ? safeFormat(report.generated_at, 'datetime')
    : 'Unknown'

  return (
    <div className="space-y-8 max-w-4xl mx-auto">

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Globe size={22} className="text-emerald-400" />
            Data Sources
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            All sources are 100% free — no API keys required.
            Each source runs independently; if one fails the others continue.
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 bg-slate-700 hover:bg-slate-600
                     text-slate-300 px-3 py-2 rounded-lg text-sm transition-colors shrink-0"
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      {/* Last run info */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl px-5 py-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center">
            <p className="text-2xl font-bold text-white">{report.total_upcoming ?? 0}</p>
            <p className="text-xs text-slate-400 mt-0.5">Total upcoming fixtures</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold text-white">{report.total_history ?? 0}</p>
            <p className="text-xs text-slate-400 mt-0.5">Historical matches</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold text-white">{report.leagues_covered ?? 0}</p>
            <p className="text-xs text-slate-400 mt-0.5">Leagues covered</p>
          </div>
          <div className="text-center">
            <p className={`text-2xl font-bold ${failCount > 0 ? 'text-yellow-400' : 'text-emerald-400'}`}>
              {okCount}/{sources.length}
            </p>
            <p className="text-xs text-slate-400 mt-0.5">Sources with data</p>
          </div>
        </div>
        <div className="mt-3 pt-3 border-t border-slate-700 flex items-center gap-2">
          <Clock size={12} className="text-slate-500" />
          <span className="text-xs text-slate-500">Last import run: {genAt}</span>
          {lastFetch && (
            <span className="text-xs text-slate-600 ml-auto">
              Page loaded: {lastFetch.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {/* Source status summary badges */}
      <div className="flex flex-wrap gap-2">
        {okCount > 0 && (
          <div className="flex items-center gap-1.5 bg-emerald-900/30 border border-emerald-700/40
                          text-emerald-300 text-sm px-3 py-1.5 rounded-full">
            <CheckCircle2 size={13} />
            {okCount} source{okCount > 1 ? 's' : ''} pulling data
          </div>
        )}
        {partialCount > 0 && (
          <div className="flex items-center gap-1.5 bg-yellow-900/30 border border-yellow-700/40
                          text-yellow-300 text-sm px-3 py-1.5 rounded-full">
            <AlertCircle size={13} />
            {partialCount} returned no data (off-season / no fixtures today)
          </div>
        )}
        {failCount > 0 && (
          <div className="flex items-center gap-1.5 bg-red-900/30 border border-red-700/40
                          text-red-300 text-sm px-3 py-1.5 rounded-full">
            <XCircle size={13} />
            {failCount} source{failCount > 1 ? 's' : ''} failed
          </div>
        )}
      </div>

      {/* Source cards */}
      <section>
        <h2 className="text-lg font-bold text-white mb-3 flex items-center gap-2">
          <Layers size={16} className="text-slate-400" />
          Source Detail
        </h2>
        <div className="grid md:grid-cols-2 gap-4">
          {sources.map(s => (
            <SourceCard key={s.source} s={s} />
          ))}
        </div>
      </section>

      {/* Fixtures by league */}
      {leagueEntries.length > 0 && (
        <section>
          <h2 className="text-lg font-bold text-white mb-3 flex items-center gap-2">
            <List size={16} className="text-slate-400" />
            Upcoming fixtures by league
          </h2>
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-3">
            {leagueEntries.map(([league, count]) => (
              <LeagueBar key={league} league={league} count={count} max={maxLeagueCount} />
            ))}
          </div>
        </section>
      )}

      {/* Fixtures by source */}
      {sourceEntries.length > 0 && (
        <section>
          <h2 className="text-lg font-bold text-white mb-3 flex items-center gap-2">
            <TrendingUp size={16} className="text-slate-400" />
            Upcoming fixtures by source
          </h2>
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-3">
            {sourceEntries.map(([src, count]) => (
              <LeagueBar key={src} league={src} count={count} max={sourceEntries[0]?.[1] || 1} />
            ))}
          </div>
        </section>
      )}

      {/* Info box */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4
                      text-slate-400 text-xs space-y-1.5">
        <p className="font-medium text-slate-300">How deduplication works</p>
        <p>
          Every fixture is identified by <code className="bg-slate-700 px-1 rounded">
          league_id : home_team_id : away_team_id : date</code>.
          Because team IDs are derived from team name within a league, the same match
          from two different sources produces the same key and is stored only once.
        </p>
        <p>
          The source that finds a fixture first "wins". Priority order:
          OpenLigaDB → TheSportsDB → ESPN → football-data.org → ClubElo.
        </p>
      </div>
    </div>
  )
}
