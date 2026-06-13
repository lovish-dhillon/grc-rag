import { useState } from 'react'

import { SCORECARD } from '../scorecard'
import { Badge } from './Badge'
import { GateBadge } from './GateBadge'
import { MetricStat } from './MetricStat'
import { ScoreBar } from './ScoreBar'

/**
 * The measured trust story, collapsed by default so the answer stays the focus. This is the
 * project's CI-gated **golden-set** scorecard — system-level evidence, not per-answer telemetry,
 * and labelled as such ("Measured on the golden set"). Every number comes from `scorecard.ts`,
 * which mirrors the repo's committed evidence.
 */
export function EvalStrip() {
  const [open, setOpen] = useState(false)
  const sc = SCORECARD

  return (
    <section className={'eval' + (open ? ' eval--open' : '')}>
      <button type="button" className="panel__toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="panel__toggle-left">
          <span className={'panel__caret' + (open ? ' panel__caret--open' : '')}>▸</span>
          <span>Eval scorecard</span>
          <Badge tone="pass" dot>
            Gate green
          </Badge>
        </span>
        <span className="eval__summary">
          <span>
            <span className="eval__dot-pass">●</span> faithful {sc.faithfulness.toFixed(3)}
          </span>
          <span>
            <span className="eval__dot-pass">●</span> recall {sc.recall.toFixed(3)}
          </span>
          <span style={{ color: 'var(--text-soft)' }}>{open ? 'Hide' : 'Details'}</span>
        </span>
      </button>

      {open && (
        <div className="eval__body">
          <div className="eval__bodyhead">
            <span className="grc-eyebrow">Measured on the golden set</span>
            <span style={{ flex: 1, minWidth: 20, height: 1, background: 'var(--border-soft)' }} />
            <Badge tone="accent">{sc.promptVersion}</Badge>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
              {sc.goldenItems}-item golden · {sc.runDate}
            </span>
          </div>

          <div className="eval__metrics">
            {sc.metrics.map((m) => (
              <MetricStat
                key={m.label}
                label={m.label}
                value={m.value}
                target={m.target}
                status={m.status}
                delta={m.delta}
              />
            ))}
          </div>

          <div className="eval__bars">
            {sc.gatedBars.map((b) => (
              <ScoreBar key={b.label} label={b.label} value={b.value} target={b.target} status="pass" />
            ))}
          </div>

          <div className="eval__gatewrap">
            <GateBadge sub={`all thresholds met · judge ${sc.judgeModel}`} />
            <span className="eval__gatenote">
              {sc.corpusChunks} chunks · {Math.round(sc.clauseLabelled * 100)}% clause-labelled
              <br />
              support threshold {sc.supportThreshold} · a seeded regression turns it red
            </span>
          </div>
        </div>
      )}
    </section>
  )
}
