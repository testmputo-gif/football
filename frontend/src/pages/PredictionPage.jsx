// src/pages/PredictionPage.jsx
import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getFixtureById } from '../services/data'
import { ConfidenceMeter, MarketBadge, FormGuide, Spinner, ScoreMatrix, StatBar, WinProbBar } from '../components/ui'
import { format } from 'date-fns'
import { ArrowLeft, Info } from 'lucide-react'

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
const TAB_LABELS = { predictions: 'Predictions', stats: 'Stats', matrix: 'Score Matrix', reasoning: 'Reasoning' }

export default function PredictionPage() {
  const { id } = useParams()
  const [fixture, setFixture] = useState(null)
  const [tab, setTab] = useState('predictions')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getFixtureById(id).then(setFixture).finally(() => setLoading(false))
  }, [id])

  if (loading) return <Spinner />
  if (!fixture) return (
    <div className="text-center py-24 text-slate-500">
      Fixture not found.
      <Link to="/fixtures" className="block mt-2 text-emerald-400 hover:underline">← Back to fixtures</Link>
    </div>
  )

  const pred = fixture.predictions || {}
  const reasoning = fixture.reasoning || {}

  return (
    <div className="max-w-3xl mx-auto space-y-5">
      <Link to="/fixtures" className="flex items-center gap-1 text-slate-400 hover:text-white text-sm">
        <ArrowLeft size={14} /> Back to fixtures
      </Link>

      {/* Match header */}
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6">
        <p className="text-center text-xs text-slate-400 mb-4">{fixture.league_name} · {fixture.round}</p>

        <div className="flex items-center justify-between gap-4">
          <div className="flex flex-col items-center gap-2 flex-1">
            {fixture.home_team_logo && <img src={fixture.home_team_logo} alt="" className="w-14 h-14 object-contain" />}
            <span className="font-bold text-white text-center text-sm">{fixture.home_team_name}</span>
            <FormGuide form={fixture.home_form} />
          </div>

          <div className="flex flex-col items-center gap-1 px-3">
            {fixture.most_likely_score && (
              <span className="text-2xl font-bold text-emerald-400">{fixture.most_likely_score}</span>
            )}
            <span className="text-slate-500 text-xs">Most likely</span>
            <span className="text-slate-400 text-sm mt-1">
              {format(new Date(fixture.fixture_date), 'EEE d MMM · HH:mm')}
            </span>
            {fixture.venue && <span className="text-xs text-slate-600 text-center">{fixture.venue}</span>}
          </div>

          <div className="flex flex-col items-center gap-2 flex-1">
            {fixture.away_team_logo && <img src={fixture.away_team_logo} alt="" className="w-14 h-14 object-contain" />}
            <span className="font-bold text-white text-center text-sm">{fixture.away_team_name}</span>
            <FormGuide form={fixture.away_form} />
          </div>
        </div>

        {fixture.home_win_probability != null && (
          <div className="mt-5">
            <WinProbBar
              homeProb={fixture.home_win_probability}
              drawProb={fixture.draw_probability}
              awayProb={fixture.away_win_probability}
              homeTeam={fixture.home_team_name}
              awayTeam={fixture.away_team_name}
            />
          </div>
        )}

        {fixture.xg_home != null && (
          <div className="mt-3 flex justify-center gap-6 text-xs text-slate-500">
            <span>xG Home: <strong className="text-white">{fixture.xg_home}</strong></span>
            <span>xG Away: <strong className="text-white">{fixture.xg_away}</strong></span>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-800 p-1 rounded-xl border border-slate-700">
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex-1 py-2 rounded-lg text-xs md:text-sm font-medium transition-colors ${
              tab === t ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:text-white'
            }`}>
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {/* Predictions tab */}
      {tab === 'predictions' && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
          <h3 className="font-bold text-white mb-4">All Markets</h3>
          <MarketRow label="Match Winner" pick={pred.winner?.pick} confidence={pred.winner?.confidence} />
          <MarketRow label="Over 1.5 Goals" pick={pred.over15?.pick} confidence={pred.over15?.confidence} />
          <MarketRow label="Over 2.5 Goals" pick={pred.over25?.pick} confidence={pred.over25?.confidence} />
          <MarketRow label="Over 3.5 Goals" pick={pred.over35?.pick} confidence={pred.over35?.confidence} />
          <MarketRow label="Both Teams to Score" pick={pred.btts?.pick} confidence={pred.btts?.confidence} />
          <MarketRow label="Over 8.5 Corners" pick={pred.corners_85?.pick} confidence={pred.corners_85?.confidence}
            note={fixture.expected_corners ? `Expected: ${fixture.expected_corners} total` : null} />
          <MarketRow label="Over 9.5 Corners" pick={pred.corners_95?.pick} confidence={pred.corners_95?.confidence} />
          <MarketRow label="Over 3.5 Cards" pick={pred.cards_35?.pick} confidence={pred.cards_35?.confidence}
            note={fixture.expected_cards ? `Expected: ${fixture.expected_cards} total` : null} />
          <MarketRow label="First Half Over 0.5" pick={pred.fh_over05?.pick} confidence={pred.fh_over05?.confidence} />
          {fixture.red_card_probability != null && (
            <p className="text-sm text-slate-400 pt-3 border-t border-slate-700/60 mt-2">
              Red card probability: <span className="text-white font-bold">{Math.round(fixture.red_card_probability * 100)}%</span>
            </p>
          )}
          {fixture.no_prediction_reason && (
            <div className="mt-4 bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3 flex gap-2">
              <Info size={15} className="text-yellow-400 shrink-0 mt-0.5" />
              <p className="text-yellow-300 text-sm">{fixture.no_prediction_reason}</p>
            </div>
          )}
        </div>
      )}

      {/* Stats tab */}
      {tab === 'stats' && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-1">
          <div className="flex justify-between text-xs font-bold mb-3">
            <span className="text-blue-400">{fixture.home_team_name}</span>
            <span className="text-slate-500">Comparison</span>
            <span className="text-orange-400">{fixture.away_team_name}</span>
          </div>
          <StatBar label="Attack Strength" homeVal={fixture.home_attack_strength} awayVal={fixture.away_attack_strength} />
          <StatBar label="Defense Strength" homeVal={fixture.home_defense_strength} awayVal={fixture.away_defense_strength} />
          <div className="grid grid-cols-2 gap-4 pt-4 border-t border-slate-700 text-center">
            <div>
              <p className="text-xs text-slate-500">Elo Rating</p>
              <p className="font-bold text-white text-lg">{Math.round(fixture.home_elo || 1500)}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Elo Rating</p>
              <p className="font-bold text-white text-lg">{Math.round(fixture.away_elo || 1500)}</p>
            </div>
          </div>
          {fixture.referee_name && (
            <div className="pt-4 border-t border-slate-700">
              <p className="text-xs text-slate-500 mb-1">Referee</p>
              <p className="text-white text-sm font-medium">{fixture.referee_name}</p>
            </div>
          )}
          <p className="text-xs text-slate-600 pt-2">
            Based on {fixture.home_matches_used || '?'} home / {fixture.away_matches_used || '?'} away matches
            {fixture.ml_used ? ' · ML model active' : ' · Dixon-Coles only'}
          </p>
        </div>
      )}

      {/* Score matrix tab */}
      {tab === 'matrix' && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
          <h3 className="font-bold text-white mb-1">Scoreline Probability Matrix</h3>
          <ScoreMatrix matrix={fixture.score_matrix} mostLikelyScore={fixture.most_likely_score} />
        </div>
      )}

      {/* Reasoning tab */}
      {tab === 'reasoning' && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
          <h3 className="font-bold text-white">Model Reasoning</h3>
          {Object.keys(reasoning).length === 0
            ? <p className="text-slate-500 text-sm">No reasoning available.</p>
            : Object.entries(reasoning).map(([market, text]) => (
              <div key={market} className="border-l-2 border-emerald-500/40 pl-4">
                <p className="text-xs text-emerald-400 font-semibold uppercase mb-1">{market}</p>
                <p className="text-slate-300 text-sm leading-relaxed">{text}</p>
              </div>
            ))
          }
          <p className="text-xs text-slate-600 pt-2 border-t border-slate-700">
            Model v{fixture.model_version || '1.0.0'} ·
            Generated {fixture.generated_at ? format(new Date(fixture.generated_at), 'dd MMM HH:mm') : '—'}
          </p>
        </div>
      )}
    </div>
  )
}
