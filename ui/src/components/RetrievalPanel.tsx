import { useState } from 'react'

import type { RetrievedOut } from '../types'

interface RetrievalPanelProps {
  retrieved: RetrievedOut[]
  latencyMs: number
}

/**
 * Honest disclosure, **collapsed by default**: the ranked clauses retrieval actually surfaced
 * (with their real scores) plus wall-clock latency. A curious reader can open it to see the
 * retrieval behind the answer; the default view stays clean.
 */
export function RetrievalPanel({ retrieved, latencyMs }: RetrievalPanelProps) {
  const [open, setOpen] = useState(false)
  const max = Math.max(...retrieved.map((r) => r.score), 0.001)

  return (
    <section className="panel">
      <button type="button" className="panel__toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="panel__toggle-left">
          <span className={'panel__caret' + (open ? ' panel__caret--open' : '')}>▸</span>
          How it answered · {retrieved.length} clauses retrieved
        </span>
        <span className="panel__meta">
          <span>{latencyMs.toFixed(0)} ms</span>
          <span>· ~$0.00</span>
        </span>
      </button>

      {open && (
        <>
          <ol className="panel__list" aria-label="Retrieved clauses">
            {retrieved.map((r, i) => {
              const pct = Math.max(0, Math.min(1, r.score / max)) * 100
              return (
                <li key={r.chunk_id} className="panel__item">
                  <span className="panel__rank">{i + 1}</span>
                  <span className="panel__clause">{r.clause_label ?? r.chunk_id}</span>
                  <span className="panel__bar">
                    <span
                      className="panel__bar-fill"
                      style={{ width: `${pct}%`, background: i === 0 ? 'var(--accent)' : 'var(--blue-300)' }}
                    />
                  </span>
                  <span className="panel__score">{r.score.toFixed(3)}</span>
                </li>
              )
            })}
          </ol>
          <div className="panel__foot">
            hybrid (BM25 + dense, RRF) → cross-encoder re-rank → support gate ≥ 0.3325
          </div>
        </>
      )}
    </section>
  )
}
