import { useState } from 'react'

import type { CitationOut } from '../types'
import { CitationCard } from './CitationCard'

interface AnswerViewProps {
  answer: string
  citations: CitationOut[]
}

// Matches an inline `[chunk_id]` citation marker (no nested brackets). Only a marker that resolves
// to a real citation becomes a chip; an unresolved marker stays literal text.
const CITATION_RE = /\[([^[\]]+)\]/g

type Segment = { kind: 'text'; value: string } | { kind: 'cite'; citation: CitationOut }

function tokenize(answer: string, byId: Map<string, CitationOut>): Segment[] {
  const segments: Segment[] = []
  let lastIndex = 0
  for (const match of answer.matchAll(CITATION_RE)) {
    const citation = byId.get(match[1])
    const start = match.index ?? 0
    if (citation) {
      if (start > lastIndex) segments.push({ kind: 'text', value: answer.slice(lastIndex, start) })
      segments.push({ kind: 'cite', citation })
      lastIndex = start + match[0].length
    }
  }
  if (lastIndex < answer.length) segments.push({ kind: 'text', value: answer.slice(lastIndex) })
  return segments
}

/**
 * Renders the answer in the document serif, with each resolved `[chunk_id]` marker turned into an
 * inline citation **chip** labelled by its `clause_label` (falling back to the chunk id). Clicking
 * a chip reveals the cited clause's exact text in a `CitationCard` — locally, no extra request.
 */
export function AnswerView({ answer, citations }: AnswerViewProps) {
  const byId = new Map(citations.map((c) => [c.chunk_id, c]))
  const [activeId, setActiveId] = useState<string | null>(null)
  const segments = tokenize(answer, byId)
  const active = activeId ? (byId.get(activeId) ?? null) : null
  const n = citations.length

  return (
    <section className="answer" aria-label="Answer">
      <div className="answer__head">
        <span className="grc-eyebrow" style={{ color: 'var(--accent)' }}>
          Grounded answer
        </span>
        <span className="answer__rule" />
        <span className="answer__count">
          {n} citation{n === 1 ? '' : 's'}
        </span>
      </div>

      <p className="answer__text">
        {segments.map((segment, i) =>
          segment.kind === 'text' ? (
            <span key={i}>{segment.value}</span>
          ) : (
            <button
              key={i}
              type="button"
              className={'grc-cite' + (activeId === segment.citation.chunk_id ? ' grc-cite--active' : '')}
              aria-pressed={activeId === segment.citation.chunk_id}
              onClick={() =>
                setActiveId((current) =>
                  current === segment.citation.chunk_id ? null : segment.citation.chunk_id,
                )
              }
            >
              <span>{segment.citation.clause_label ?? segment.citation.chunk_id}</span>
              <span className="grc-cite__mark" aria-hidden="true">
                ¶
              </span>
            </button>
          ),
        )}
      </p>

      {active && <CitationCard citation={active} onClose={() => setActiveId(null)} />}
    </section>
  )
}
