import { Badge } from './Badge'

interface RefusalNoticeProps {
  /** The refusal sentinel the API returned, shown verbatim. */
  answer: string
}

/**
 * The honest, **first-class** refusal state — the project's differentiator, not an error to hide.
 * When retrieval can't ground a clause, the system declines rather than guessing one. Deliberately
 * distinct (role="status", calm amber) from `ErrorNotice` (role="alert"): a refusal is the system
 * working correctly, not a failure.
 */
export function RefusalNotice({ answer }: RefusalNoticeProps) {
  return (
    <section className="refusal" role="status" aria-label="Refusal">
      <Badge tone="refuse">Not supported by the corpus</Badge>
      <p className="refusal__lead">{answer}</p>
      <p className="refusal__detail">
        The system won&rsquo;t guess a clause. Nothing in the governed corpus (NIST AI RMF, NIST GenAI
        Profile, EU AI Act) grounded this question strongly enough to support it. The top candidate
        fell below the calibrated support threshold of 0.3325, so it declines rather than risk a
        confident, wrong citation.
      </p>
    </section>
  )
}
