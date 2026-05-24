// src/components/ui.jsx — All shared UI primitives

// ── Confidence meter ──────────────────────────────────────────────────────────
export function ConfidenceMeter({ value, size = 'md' }) {
  if (value == null) return <span className="text-slate-500 text-xs italic">No pick</span>
  const v = Math.round(value)
  const color =
    v >= 80 ? 'text-yellow-400 bg-yellow-400/10 border-yellow-500/40' :
    v >= 70 ? 'text-emerald-400 bg-emerald-400/10 border-emerald-500/40' :
    v >= 58 ? 'text-blue-400 bg-blue-400/10 border-blue-500/40' :
              'text-slate-400 bg-slate-400/10 border-slate-500/40'
  const label = v >= 80 ? '★ High' : v >= 70 ? 'Strong' : v >= 58 ? 'Moderate' : 'Low'
  const sz = size === 'sm' ? 'text-xs px-2 py-0.5' : 'text-sm px-3 py-1'
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border font-semibold ${color} ${sz}`}>
      {v}% <span className="opacity-60 font-normal">{label}</span>
    </span>
  )
}

// ── Market pick badge ─────────────────────────────────────────────────────────
export function MarketBadge({ pick, size = 'sm' }) {
  if (!pick || pick === 'no_pick') return <span className="text-slate-500 text-xs italic">—</span>
  const map = {
    over:  ['OVER',     'bg-emerald-600'],
    under: ['UNDER',    'bg-red-600'],
    yes:   ['YES',      'bg-emerald-600'],
    no:    ['NO',       'bg-red-600'],
    home:  ['HOME WIN', 'bg-blue-600'],
    draw:  ['DRAW',     'bg-slate-500'],
    away:  ['AWAY WIN', 'bg-orange-600'],
  }
  const [label, bg] = map[pick] || [pick.toUpperCase(), 'bg-slate-600']
  const sz = size === 'sm' ? 'text-xs px-2 py-0.5' : 'text-sm px-3 py-1'
  return <span className={`${sz} ${bg} text-white font-bold rounded uppercase`}>{label}</span>
}

// ── Form guide (WWDLW) ────────────────────────────────────────────────────────
export function FormGuide({ form }) {
  if (!form) return <span className="text-slate-600 text-xs">No form</span>
  return (
    <div className="flex gap-0.5">
      {form.split('').map((r, i) => (
        <span key={i} className={`w-5 h-5 rounded text-xs font-bold flex items-center justify-center text-white
          ${r === 'W' ? 'bg-emerald-600' : r === 'D' ? 'bg-slate-600' : 'bg-red-600'}`}>
          {r}
        </span>
      ))}
    </div>
  )
}

// ── Loading spinner ────────────────────────────────────────────────────────────
export function Spinner({ size = 10 }) {
  return (
    <div className="flex justify-center items-center py-20">
      <div className={`animate-spin rounded-full w-${size} h-${size} border-b-2 border-emerald-400`} />
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────
export function Empty({ message = 'Nothing to show' }) {
  return <div className="text-center py-20 text-slate-500">{message}</div>
}

// ── Score matrix heatmap ──────────────────────────────────────────────────────
export function ScoreMatrix({ matrix, mostLikelyScore }) {
  if (!matrix?.length) return null
  const flat = matrix.flat()
  const maxP = Math.max(...flat)
  const goals = [0,1,2,3,4,5,6]

  const cellColor = (p) => {
    const ratio = p / maxP
    if (ratio > 0.7)  return 'bg-emerald-500 text-white'
    if (ratio > 0.35) return 'bg-emerald-800 text-emerald-100'
    if (ratio > 0.15) return 'bg-slate-700 text-slate-300'
    return 'bg-slate-800/50 text-slate-600'
  }

  return (
    <div className="overflow-x-auto">
      <p className="text-xs text-slate-500 mb-2">Home (rows) vs Away (columns) — probability %</p>
      <div className="inline-grid gap-0.5" style={{ gridTemplateColumns: `1.5rem repeat(7, 2.2rem)` }}>
        {/* Header */}
        <div />
        {goals.map(g => <div key={g} className="text-xs text-slate-400 text-center font-bold py-1">{g}</div>)}
        {/* Rows */}
        {goals.map(i => (
          <>
            <div key={`r${i}`} className="text-xs text-slate-400 text-center font-bold flex items-center justify-center">{i}</div>
            {goals.map(j => {
              const p = matrix[i]?.[j] || 0
              const isTop = `${i}-${j}` === mostLikelyScore
              return (
                <div key={`${i}${j}`}
                  className={`text-xs text-center py-1 rounded font-mono ${cellColor(p)} ${isTop ? 'ring-2 ring-yellow-400 ring-offset-1 ring-offset-slate-900' : ''}`}
                  title={`${i}-${j}: ${(p*100).toFixed(1)}%`}
                >
                  {(p * 100).toFixed(1)}
                </div>
              )
            })}
          </>
        ))}
      </div>
      {mostLikelyScore && (
        <p className="mt-2 text-xs text-yellow-400">★ Most likely: <strong>{mostLikelyScore}</strong></p>
      )}
    </div>
  )
}

// ── Stat comparison bar ───────────────────────────────────────────────────────
export function StatBar({ label, homeVal, awayVal }) {
  const total = (homeVal || 0) + (awayVal || 0) || 1
  const hp = Math.round((homeVal || 0) / total * 100)
  return (
    <div className="mb-3">
      <div className="flex justify-between text-xs text-slate-400 mb-1">
        <span className="text-blue-400">{homeVal?.toFixed?.(2) ?? homeVal ?? '—'}</span>
        <span className="text-slate-500">{label}</span>
        <span className="text-orange-400">{awayVal?.toFixed?.(2) ?? awayVal ?? '—'}</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-700 flex overflow-hidden">
        <div className="bg-blue-500 transition-all" style={{ width: `${hp}%` }} />
        <div className="bg-orange-500 transition-all" style={{ width: `${100 - hp}%` }} />
      </div>
    </div>
  )
}

// ── Win probability bar ───────────────────────────────────────────────────────
export function WinProbBar({ homeProb, drawProb, awayProb, homeTeam, awayTeam }) {
  const h = Math.round((homeProb || 0) * 100)
  const d = Math.round((drawProb || 0) * 100)
  const a = Math.round((awayProb || 0) * 100)
  return (
    <div>
      <div className="h-3 rounded-full overflow-hidden flex">
        <div className="bg-blue-500 transition-all" style={{ width: `${h}%` }} title={`${homeTeam}: ${h}%`} />
        <div className="bg-slate-500 transition-all" style={{ width: `${d}%` }} title={`Draw: ${d}%`} />
        <div className="bg-orange-500 transition-all" style={{ width: `${a}%` }} title={`${awayTeam}: ${a}%`} />
      </div>
      <div className="flex justify-between text-xs mt-1">
        <span className="text-blue-400">{h}% H</span>
        <span className="text-slate-400">{d}% D</span>
        <span className="text-orange-400">{a}% A</span>
      </div>
    </div>
  )
}
