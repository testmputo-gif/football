// src/components/PredictionCard.jsx
import { Link } from 'react-router-dom'
import { format } from 'date-fns'
import { ConfidenceMeter, MarketBadge, FormGuide } from './ui'
import { Clock, AlertCircle } from 'lucide-react'

export default function PredictionCard({ fixture }) {
  const pred   = fixture.predictions || {}
  const winner = pred.winner || {}
  const over25 = pred.over25 || {}
  const btts   = pred.btts   || {}

  // Safe date formatting
  let dateStr = '—'
  try {
    if (fixture.fixture_date) {
      dateStr = format(new Date(fixture.fixture_date), 'EEE d MMM · HH:mm')
    }
  } catch (e) {}

  const fixtureUrl = `/fixture/${encodeURIComponent(fixture.id)}`
  const hasPrediction = !fixture.no_prediction_reason
  const hasAnyConfidence = hasPrediction && (
    winner.confidence != null || over25.confidence != null || btts.confidence != null
  )

  return (
    <Link
      to={fixtureUrl}
      className="block bg-slate-800 hover:bg-slate-750 border border-slate-700 hover:border-emerald-500/50 rounded-xl p-4 transition-all group"
    >
      {/* League + time */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-1.5">
          {fixture.league_logo && (
            <img src={fixture.league_logo} alt="" className="w-4 h-4 object-contain"
              onError={e => { e.target.style.display = 'none' }} />
          )}
          <span className="text-xs text-slate-400 font-medium truncate max-w-[150px]">
            {fixture.league_name}
          </span>
        </div>
        <span className="flex items-center gap-1 text-xs text-slate-500">
          <Clock size={10} />
          {dateStr}
        </span>
      </div>

      {/* Teams + most likely score */}
      <div className="flex items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {fixture.home_team_logo && (
            <img src={fixture.home_team_logo} alt="" className="w-7 h-7 object-contain shrink-0"
              onError={e => { e.target.style.display = 'none' }} />
          )}
          <span className="font-semibold text-sm text-white truncate">
            {fixture.home_team_name}
          </span>
        </div>

        <div className="flex flex-col items-center px-2 shrink-0">
          {fixture.most_likely_score && hasPrediction ? (
            <>
              <span className="text-emerald-400 font-bold text-sm">
                {fixture.most_likely_score}
              </span>
              <span className="text-slate-600 text-xs">likely</span>
            </>
          ) : (
            <span className="text-slate-600 text-xs">VS</span>
          )}
        </div>

        <div className="flex items-center gap-2 flex-1 min-w-0 justify-end">
          <span className="font-semibold text-sm text-white truncate text-right">
            {fixture.away_team_name}
          </span>
          {fixture.away_team_logo && (
            <img src={fixture.away_team_logo} alt="" className="w-7 h-7 object-contain shrink-0"
              onError={e => { e.target.style.display = 'none' }} />
          )}
        </div>
      </div>

      {/* Form guides */}
      {(fixture.home_form || fixture.away_form) && (
        <div className="flex justify-between mb-3 px-1">
          <FormGuide form={fixture.home_form} />
          <FormGuide form={fixture.away_form} />
        </div>
      )}

      {/* Bottom section */}
      <div className="pt-3 border-t border-slate-700">
        {hasPrediction && hasAnyConfidence ? (
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: 'Winner',   data: winner },
              { label: 'Over 2.5', data: over25 },
              { label: 'BTTS',     data: btts   },
            ].map(({ label, data }) => (
              <div key={label} className="text-center">
                <div className="text-xs text-slate-500 mb-1">{label}</div>
                <MarketBadge pick={data.pick} />
                <div className="mt-1">
                  <ConfidenceMeter value={data.confidence} size="sm" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          // Show xG if available even when no full prediction
          fixture.xg_home != null ? (
            <div className="flex items-center justify-between text-xs">
              <span className="text-blue-400 font-medium">xG {fixture.xg_home?.toFixed(2)}</span>
              <span className="text-slate-500 flex items-center gap-1">
                <AlertCircle size={10} />
                Building data ({fixture.home_matches_used ?? 0}/{8} matches)
              </span>
              <span className="text-orange-400 font-medium">xG {fixture.xg_away?.toFixed(2)}</span>
            </div>
          ) : (
            <div className="text-center text-xs text-slate-600 flex items-center justify-center gap-1">
              <AlertCircle size={10} />
              More data needed for prediction
            </div>
          )
        )}
      </div>

      <div className="mt-3 text-xs text-slate-600 group-hover:text-emerald-500 text-center transition-colors">
        Full analysis →
      </div>
    </Link>
  )
}
