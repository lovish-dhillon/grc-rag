// The project's measured, CI-gated trust numbers — the golden-set scorecard, NOT per-query
// telemetry. Sourced verbatim from the repo's committed evidence so the UI never invents a
// number: faithfulness + run metadata from `data/eval/scorecard.json`; recall@10, refusal, and
// answer-relevancy from the case-study results (`docs/01-overview.md` / `docs/04-evaluation.md`).
// Shown in the collapsible "Eval scorecard" strip, clearly labelled "Measured on the golden set".

export interface MetricCard {
  label: string
  value: string
  target: string
  status: 'pass' | 'warn'
  delta?: string
}

export interface GatedBar {
  label: string
  value: number
  target: number
}

export interface Scorecard {
  runDate: string
  promptVersion: string
  judgeModel: string
  goldenItems: number
  judged: number
  corpusChunks: number
  clauseLabelled: number
  supportThreshold: number
  faithfulness: number
  recall: number
  metrics: MetricCard[]
  gatedBars: GatedBar[]
}

export const SCORECARD: Scorecard = {
  runDate: '2026-07-11',
  promptVersion: 'cite-or-refuse/v3',
  judgeModel: 'claude-haiku-4-5',
  goldenItems: 41,
  judged: 36,
  corpusChunks: 451,
  clauseLabelled: 0.76,
  supportThreshold: 0.3325,
  faithfulness: 0.924,
  recall: 0.889,
  metrics: [
    { label: 'Faithfulness', value: '0.924', target: 'judge ≥ 0.90', status: 'pass', delta: '+0.019 vs v2' },
    { label: 'Recall@10', value: '0.889', target: 'target ≥ 0.85', status: 'pass' },
    { label: 'Refusal', value: '5/5', target: 'out-of-corpus', status: 'pass' },
    { label: 'Answer relevancy', value: '0.806', target: 'tracked', status: 'pass', delta: '+0.084 vs v2' },
  ],
  gatedBars: [
    { label: 'Faithfulness (LLM-judge, n=36)', value: 0.924, target: 0.9 },
    { label: 'Recall@10 (verified clauses)', value: 0.889, target: 0.85 },
  ],
}
