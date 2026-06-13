interface ScoreBarProps {
  label: string
  value: number
  /** Optional gated threshold — drawn as a tick on the track, with a "target ≥ x" caption. */
  target?: number
  status?: 'pass' | 'neutral'
}

/** A labelled 0–1 progress bar with an optional threshold tick — used for the gated metrics
 * (faithfulness, recall@10) so the bar visibly clears its bar. */
export function ScoreBar({ label, value, target, status = 'neutral' }: ScoreBarProps) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  return (
    <div>
      <div className="grc-scorebar__head">
        <span className="grc-scorebar__label">{label}</span>
        <span className="grc-scorebar__value">{value.toFixed(3)}</span>
      </div>
      <div className="grc-scorebar__track">
        <span className={`grc-scorebar__fill grc-scorebar__fill--${status}`} style={{ width: `${pct}%` }} />
        {target != null && <span className="grc-scorebar__target" style={{ left: `${target * 100}%` }} />}
      </div>
      {target != null && <div className="grc-scorebar__targetlabel">target ≥ {target.toFixed(2)}</div>}
    </div>
  )
}
