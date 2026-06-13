import { useEffect, useRef, useState } from 'react'

// The real pipeline stages, in order. Shown as a calm staged animation while a question is in
// flight. These are the actual stages the backend runs (hybrid retrieval → cross-encoder
// re-rank → support gate → generation) — an honest illustration of the architecture, not
// fabricated per-query telemetry. The real ranked clauses + scores appear afterward in the
// "How it answered" panel, sourced from the live AskResponse.
const STAGES = [
  { key: 'embed', label: 'Embed', trace: 'query → dense embedding · BM25 tokens' },
  { key: 'hybrid', label: 'Hybrid', trace: 'hybrid search · lexical + vector candidates' },
  { key: 'fuse', label: 'Fuse', trace: 'reciprocal-rank fusion · merge + dedupe' },
  { key: 'rerank', label: 'Re-rank', trace: 'cross-encoder re-rank · scoring top candidates' },
  { key: 'gate', label: 'Gate', trace: 'support gate · top score vs threshold 0.3325' },
  { key: 'generate', label: 'Generate', trace: 'generating cited answer · cite-or-refuse/v2' },
] as const

// Time to advance through the first five stages; the run then holds on "Generate" (which truly
// dominates wall-clock for the local generator) until the real response arrives and unmounts this.
const STEP_MS = 520
const DETAIL_NOTE: Record<string, string> = {
  embed: '→ 384-d vector + BM25 terms',
  hybrid: 'lexical + semantic recall, in parallel',
  fuse: 'one ranked candidate pool',
  rerank: 'precise relevance scores, top-k',
  gate: 'answer only on sufficient support',
  generate: 'grounded, every claim cited',
}

interface RetrievalPipelineProps {
  question: string
}

export function RetrievalPipeline({ question }: RetrievalPipelineProps) {
  const [stageIdx, setStageIdx] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef<number>(0)

  useEffect(() => {
    setStageIdx(0)
    startRef.current = performance.now()
    const timers = STAGES.slice(1).map((_, i) =>
      window.setTimeout(() => setStageIdx(i + 1), STEP_MS * (i + 1)),
    )
    const tick = window.setInterval(() => {
      setElapsed(Math.round(performance.now() - startRef.current))
    }, 50)
    return () => {
      timers.forEach(window.clearTimeout)
      window.clearInterval(tick)
    }
  }, [question])

  const stage = STAGES[stageIdx]

  return (
    <div className="pipe" aria-label="Retrieving">
      <div className="pipe__rail">
        {STAGES.map((s, i) => {
          const done = i < stageIdx
          const active = i === stageIdx
          const dotCls = 'pipe__dot' + (done ? ' pipe__dot--done' : active ? ' pipe__dot--active' : '')
          const labelCls =
            'pipe__stagelabel' +
            (done ? ' pipe__stagelabel--done' : active ? ' pipe__stagelabel--active' : '')
          return (
            <div key={s.key} style={{ display: 'contents' }}>
              <div className="pipe__stage">
                <span className={dotCls}>{done ? '✓' : i + 1}</span>
                <span className={labelCls}>{s.label}</span>
              </div>
              {i < STAGES.length - 1 && (
                <span className={'pipe__connector' + (i < stageIdx ? ' pipe__connector--done' : '')} />
              )}
            </div>
          )
        })}
      </div>

      <div className="pipe__stagebar" />

      <div className="pipe__detail">
        <span className="pipe__query">“{question}”</span>
        <span className="pipe__detailnote">{DETAIL_NOTE[stage.key]}</span>
      </div>

      <div className="pipe__foot">
        <span className="pipe__trace">
          <span className="pipe__trace-arrow">›</span> {stage.trace}
        </span>
        <span className="pipe__latency">{elapsed} ms</span>
      </div>
    </div>
  )
}
