import type { ReactNode } from 'react'

type BadgeTone = 'neutral' | 'accent' | 'pass' | 'refuse'

interface BadgeProps {
  children: ReactNode
  tone?: BadgeTone
  dot?: boolean
}

/** A small uppercase status pill — eval-gate verdicts, the refusal label, prompt-version markers. */
export function Badge({ children, tone = 'neutral', dot = false }: BadgeProps) {
  const cls = ['grc-badge', `grc-badge--${tone}`, dot ? 'grc-badge--dot' : ''].filter(Boolean).join(' ')
  return <span className={cls}>{children}</span>
}
