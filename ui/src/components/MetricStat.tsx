interface MetricStatProps {
  label: string
  value: string
  target?: string
  status?: 'pass' | 'warn' | 'neutral'
  delta?: string
}

/** A single eval number in the scorecard: a label, a large mono value, and an optional
 * target / delta footer coloured by status (pass / warn). */
export function MetricStat({ label, value, target, status = 'neutral', delta }: MetricStatProps) {
  const tone = status === 'pass' || status === 'warn' ? status : null
  return (
    <div className="grc-metric">
      <span className="grc-metric__label">{label}</span>
      <span className={'grc-metric__value' + (tone ? ` grc-metric__value--${tone}` : '')}>{value}</span>
      {(target || delta) && (
        <span className="grc-metric__foot">
          {target && <span>{target}</span>}
          {delta && <span className={'grc-metric__delta' + (tone ? ` grc-metric__delta--${tone}` : '')}>{delta}</span>}
        </span>
      )}
    </div>
  )
}
