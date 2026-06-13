// The wire DTO — kept in sync with `AskResponse` in `src/grc_rag/api.py` (PRD-P4-12).
// The API resolves each citation to its clause + text at the edge, so click-through is local:
// the UI never needs a second request to show the cited clause.

export interface CitationOut {
  chunk_id: string
  doc_id: string
  /** The human clause this citation resolves to (e.g. "EU AI Act — Article 5"); null if unlabelled. */
  clause_label: string | null
  /** The cited chunk's exact text — what the click-through reveals. */
  text: string
  score: number
}

export interface RetrievedOut {
  chunk_id: string
  clause_label: string | null
  score: number
}

export interface AskResponse {
  question: string
  answer: string
  /** True when the system declined to answer (no clause grounded it) — a first-class state, not an error. */
  refused: boolean
  citations: CitationOut[]
  retrieved: RetrievedOut[]
  prompt_version: string
  latency_ms: number
}
