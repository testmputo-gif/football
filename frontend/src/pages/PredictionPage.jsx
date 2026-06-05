// src/pages/PredictionPage.jsx — Full fixture detail page
import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ConfidenceMeter, MarketBadge, FormGuide, Spinner, ScoreMatrix, StatBar, WinProbBar } from '../components/ui'
import { format } from 'date-fns'
import { ArrowLeft, Info, AlertCircle } from 'lucide-react'

// ── Market row used in predictions tab ────────────────────────────────────────
function MarketRow({ label, pick, confidence, note }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-slate-700/60 last:border-0">
      <div>
        <p className="text-sm font-medium text-white">{label}</p>
        {note && <p className="text-xs text-slate-500 mt-0.5">{note}</p>}
      </div>
      <div className="flex items-center gap-2">
        <MarketBadge pick={pick} />
        <ConfidenceMeter value={confidence} size="sm" />
      </div>
    </div>
  )
}

const TABS = ['predictions', 'stats', 'matrix', 'reasoning']
const TAB_LABELS = {
  predictions: 'Predictions',
  stats:       'Stats',
  matrix:      'Score Matrix',
  reasoning:   'Reasoning',
}

// ── Fixture lookup — searches latest.json then last 14 days ──────────────────
async function findFixture(targetId) {
  if (!targetId) return null
  const decoded = decodeURIComponent(targetId)

  const isMatch = (f) => {
    if (!f) return false
    const fid  = String(f.id || '')
    const afid = String(f.api_fixture_id || '')
    return fid === decoded || afid === decoded || fid === targetId || afid === targetId
  }

  // Always try latest first
  const urls = ['/predictions/latest.json']
  const today = new Date()
  for (let i = 0; i < 14; i++) {
    const d = new Date(today)
    d.setDate(today.getDate() - i)
    urls.push(`/predictions/${d.toISOString().split('T')[0]}.json`)
  }

  for (const url of urls) {
    try {
      const res = await fetch(url)
      if (!res.ok) continue
      const data = await res.json()
      const found = (data.fixtures || []).find(isMatch)
      if (found) return found
    } catch (_) {}
  }
  return null
}

// ── Main component ────────────────────────────────────────────────────────────
export default function PredictionPage() {
  const { id } = useParams()
  const [fixture, setFixture] = useState(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [activeTab, setActiveTab] = useState('predictions')

  useEffect(() => {
    setLoading(true)
    setNotFound(false)
    findFixture(id).then(f => {
      if (f) setFixture(f)
      else setNotFound(true)
    }).finally(() => setLoading(false))
  }, [id])

  if (loading) return <Spinner />

  if (notFound || !fixture) {
    return (
      <div className="max-w-2xl mx-auto text-center py-20 space-y-4">
        <AlertCircle size={40} className="text-slate-600 mx-auto" />
        <h2 className="text-xl font-bold text-white">Match not found</h2>
        <p className="text-slate-400 text-sm">
          This fixture may have expired from the prediction window (14 days) or the ID format changed.
        </p>
        <Link to="/fixtures" className="inline-block mt-2 text-sm text-emerald-400 hover:underline">
          ← Back to fixtures
        </Link>
      </div>
    )
  }

  const pred = fixture.predictions || {}
  const dateStr = fixture.fixture_date
    ? format(new Date(fixture.fixture_date), "EEEE d MMMM yyyy · HH:mm 'UTC'")
    : '—'

  return (
    <div className="max-w-2xl mx-auto space-y-5">
      {/* Back link */}
      <Link to="/fixtures" className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors">
        <ArrowLeft size={14} /> Back to fixtures
      </Link>

      {/* Match header card */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-6">
        {/* League + date */}
        <div className="flex items-center justify-between mb-5 text-xs text-slate-500">
          <div className="flex items-center gap-1.5">
            {fixture.league_logo && (
              <img src={fixture.league_logo} alt="" className="w-4 h-4 object-contain"
                onError={e => { e.target.style.display = 'none' }} />
            )}
            <span className="font-medium text-slate-400">{fixture.league_name}</span>
            {fixture.round && <span className="text-slate-600">· {fixture.round}</span>}
          </div>
          <span>{dateStr}</span>
        </div>

        {/* Teams */}
        <div className="flex items-center justify-between gap-4 mb-5">
          <div className="flex-1 flex flex-col items-center gap-2 text-center">
            {fixture.home_team_logo && (
              <img src={fixture.home_team_logo} alt="" className="w-14 h-14 object-contain"
                onError={e => { e.target.style.display = 'none' }} />
            )}
            <span className="font-bold text-white text-sm">{fixture.home_team_name}</span>
            {fixture.home_form && <FormGuide form={fixture.home_form} />}
            {fixture.home_elo && (
              <span className="text-xs text-slate-500">Elo {Math.round(fixture.home_elo)}</span>
            )}
          </div>

          <div className="text-center px-2 shrink-0">
            {fixture.most_likely_score ? (
              <>
                <div className="text-2xl font-bold text-emerald-400">{fixture.most_likely_score}</div>
                <div className="text-xs text-slate-500 mt-0.5">most likely</div>
              </>
            ) : (
              <div className="text-xl font-bold text-slate-500">VS</div>
            )}
            {fixture.venue && (
              <div className="text-xs text-slate-600 mt-2 max-w-[100px] mx-auto leading-tight">{fixture.venue}</div>
            )}
          </div>

          <div className="flex-1 flex flex-col items-center gap-2 text-center">
            {fixture.away_team_logo && (
              <img src={fixture.away_team_logo} alt="" className="w-14 h-14 object-contain"
                onError={e => { e.target.style.display = 'none' }} />
            )}
            <span className="font-bold text-white text-sm">{fixture.away_team_name}</span>
            {fixture.away_form && <FormGuide form={fixture.away_form} />}
            {fixture.away_elo && (
              <span className="text-xs text-slate-500">Elo {Math.round(fixture.away_elo)}</span>
            )}
          </div>
        </div>

        {/* Win probability bar */}
        {!fixture.no_prediction_reason && (
          <WinProbBar
            homeProb={fixture.home_win_probability}
            drawProb={fixture.draw_probability}
            awayProb={fixture.away_win_probability}
            homeTeam={fixture.home_team_name}
            awayTeam={fixture.away_team_name}
          />
        )}

        {/* No prediction notice */}
        {fixture.no_prediction_reason && (
          <div className="flex items-start gap-2 bg-amber-900/20 border border-amber-700/30 rounded-lg p-3 mt-4">
            <Info size={14} className="text-amber-400 mt-0.5 shrink-0" />
            <div>
              <p className="text-amber-300 text-xs font-medium">Prediction not available</p>
              <p className="text-amber-500 text-xs mt-0.5">{fixture.no_prediction_reason}</p>
              <p className="text-slate-500 text-xs mt-1">
                Stats and xG data shown below. Predictions unlock after {fixture.home_matches_used ?? 0 < 8 ? fixture.home_team_name : fixture.away_team_name} has 8+ matches.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* xG strip (always shown if available) */}
      {(fixture.xg_home != null || fixture.xg_away != null) && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl px-5 py-3 flex items-center justify-around text-center">
          <div>
            <p className="text-2xl font-bold text-blue-400">{fixture.xg_home?.toFixed(2) ?? '—'}</p>
            <p className="text-xs text-slate-500">xG home</p>
          </div>
          <div className="text-slate-600 text-sm">Expected goals</div>
          <div>
            <p className="text-2xl font-bold text-orange-400">{fixture.xg_away?.toFixed(2) ?? '—'}</p>
            <p className="text-xs text-slate-500">xG away</p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-800 border border-slate-700 rounded-xl p-1">
        {TABS.map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)}
            className={`flex-1 py-2 text-xs font-medium rounded-lg transition-colors ${
              activeTab === tab
                ? 'bg-emerald-600 text-white'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">

        {/* ── PREDICTIONS TAB ── */}
        {activeTab === 'predictions' && (
          fixture.no_prediction_reason
            ? <p className="text-slate-500 text-sm text-center py-4">No predictions available — see notice above.</p>
            : <div>
                <MarketRow label="Match winner"      pick={pred.winner?.pick}     confidence={pred.winner?.confidence} />
                <MarketRow label="Over 1.5 goals"    pick={pred.over15?.pick}     confidence={pred.over15?.confidence} />
                <MarketRow label="Over 2.5 goals"    pick={pred.over25?.pick}     confidence={pred.over25?.confidence} />
                <MarketRow label="Over 3.5 goals"    pick={pred.over35?.pick}     confidence={pred.over35?.confidence} />
                <MarketRow label="Both teams score"  pick={pred.btts?.pick}       confidence={pred.btts?.confidence} />
                <MarketRow label="Corners over 8.5"  pick={pred.corners_85?.pick} confidence={pred.corners_85?.confidence}
                  note={fixture.expected_corners ? `Expected ${fixture.expected_corners} total` : null} />
                <MarketRow label="Corners over 9.5"  pick={pred.corners_95?.pick} confidence={pred.corners_95?.confidence} />
                <MarketRow label="Cards over 3.5"    pick={pred.cards_35?.pick}   confidence={pred.cards_35?.confidence}
                  note={fixture.expected_cards ? `Expected ${fixture.expected_cards} cards` : null} />
                <MarketRow label="1st half over 0.5" pick={pred.fh_over05?.pick}  confidence={pred.fh_over05?.confidence} />
                {fixture.red_card_probability != null && (
                  <div className="pt-3 border-t border-slate-700/60 flex justify-between text-sm">
                    <span className="text-slate-400">Red card probability</span>
                    <span className="text-white font-medium">{Math.round(fixture.red_card_probability * 100)}%</span>
                  </div>
                )}
                <div className="mt-3 pt-3 border-t border-slate-700/60 text-xs text-slate-500 flex justify-between">
                  <span>ML ensemble: {fixture.ml_used ? <span className="text-emerald-400">active</span> : 'Dixon-Coles only'}</span>
                  <span>{fixture.home_matches_used ?? '?'} / {fixture.away_matches_used ?? '?'} matches used</span>
                </div>
              </div>
        )}

        {/* ── STATS TAB ── */}
        {activeTab === 'stats' && (
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-slate-500 mb-3 font-medium">
              <span className="text-blue-400">{fixture.home_team_name}</span>
              <span>Stat</span>
              <span className="text-orange-400">{fixture.away_team_name}</span>
            </div>
            <StatBar label="Attack strength"  homeVal={fixture.home_attack_strength}  awayVal={fixture.away_attack_strength} />
            <StatBar label="Defense strength" homeVal={fixture.home_defense_strength} awayVal={fixture.away_defense_strength} />
            <StatBar label="Expected goals"   homeVal={fixture.xg_home}               awayVal={fixture.xg_away} />
            {fixture.home_elo && fixture.away_elo && (
              <StatBar label="Elo rating" homeVal={fixture.home_elo} awayVal={fixture.away_elo} />
            )}
            {fixture.referee_name && (
              <div className="pt-3 border-t border-slate-700/60 text-sm text-slate-400">
                Referee: <span className="text-white">{fixture.referee_name}</span>
              </div>
            )}
          </div>
        )}

        {/* ── SCORE MATRIX TAB ── */}
        {activeTab === 'matrix' && (
          fixture.score_matrix
            ? <ScoreMatrix matrix={fixture.score_matrix} mostLikelyScore={fixture.most_likely_score} />
            : <p className="text-slate-500 text-sm text-center py-4">Score matrix not available for this fixture.</p>
        )}

        {/* ── REASONING TAB ── */}
        {activeTab === 'reasoning' && (
          fixture.reasoning
            ? <div className="space-y-4">
                {Object.entries(fixture.reasoning).map(([market, text]) => (
                  <div key={market} className="border-b border-slate-700/60 pb-4 last:border-0 last:pb-0">
                    <p className="text-xs text-emerald-400 uppercase tracking-wider font-medium mb-1">
                      {market.replace(/_/g, ' ')}
                    </p>
                    <p className="text-slate-300 text-sm leading-relaxed">{text}</p>
                  </div>
                ))}
              </div>
            : <p className="text-slate-500 text-sm text-center py-4">Reasoning not available for this fixture.</p>
        )}
      </div>
    </div>
  )
    }
    
