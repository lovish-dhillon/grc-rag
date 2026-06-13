interface GateBadgeProps {
  /** Sub-label under the verdict (e.g. "eval gate", "all thresholds met · judge claude-haiku-4-5"). */
  sub?: string
}

function Check() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="3.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  )
}

/** The CI eval-gate verdict, made visible. Green because every gated threshold is met on the
 * committed scorecard (faithfulness ≥ 0.90, recall@10 ≥ 0.85). The project's trust headline. */
export function GateBadge({ sub }: GateBadgeProps) {
  return (
    <div className="grc-gate grc-gate--pass" role="status">
      <span className="grc-gate__icon">
        <Check />
      </span>
      <span className="grc-gate__body">
        <span className="grc-gate__title">CI gate · green</span>
        {sub && <span className="grc-gate__sub">{sub}</span>}
      </span>
    </div>
  )
}
