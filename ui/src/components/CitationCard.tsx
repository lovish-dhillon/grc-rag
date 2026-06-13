import type { CitationOut } from '../types'

interface CitationCardProps {
  citation: CitationOut
  onClose: () => void
}

/** The click-through target: the cited clause's label, its source + score metadata, and its exact
 * text in the document serif, so a reader can verify the answer against the source with no second
 * request. */
export function CitationCard({ citation, onClose }: CitationCardProps) {
  const meta = [citation.doc_id, citation.chunk_id, `score ${citation.score.toFixed(3)}`].join('  ·  ')
  return (
    <aside className="grc-clause" aria-label="Cited clause">
      <header className="grc-clause__head">
        <div>
          <h3 className="grc-clause__label">{citation.clause_label ?? citation.chunk_id}</h3>
          <p className="grc-clause__meta">{meta}</p>
        </div>
        <button type="button" className="grc-clause__close" aria-label="Close clause" onClick={onClose}>
          ×
        </button>
      </header>
      <blockquote className="grc-clause__text">{citation.text}</blockquote>
    </aside>
  )
}
