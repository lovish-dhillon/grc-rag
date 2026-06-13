import { useState } from 'react'

import { ApiError, ask } from './api'
import { AnswerView } from './components/AnswerView'
import { AskBox } from './components/AskBox'
import { ErrorNotice } from './components/ErrorNotice'
import { EvalStrip } from './components/EvalStrip'
import { GateBadge } from './components/GateBadge'
import { RefusalNotice } from './components/RefusalNotice'
import { RetrievalPanel } from './components/RetrievalPanel'
import { RetrievalPipeline } from './components/RetrievalPipeline'
import type { AskResponse } from './types'

const CORPUS_TAGS = ['NIST AI RMF', 'EU AI Act', 'NIST GenAI Profile']
const EXAMPLES = [
  'Which AI practices are prohibited under the EU AI Act?',
  'What does GOVERN 1.1 of the AI RMF require?',
  'What does ISO/IEC 42001 clause 6.1.2 require?',
]

// The mutually-exclusive result states. A discriminated union keeps the render a single,
// unambiguous branch: a refusal is never also an error; an answer is never also a refusal.
type Result =
  | { kind: 'idle' }
  | { kind: 'answer'; response: AskResponse }
  | { kind: 'refusal'; response: AskResponse }
  | { kind: 'error'; message: string }

function Wordmark() {
  return (
    <div className="wordmark">
      <span className="wordmark__glyph">¶</span>
      <span className="wordmark__text">
        grc&#8209;<b>rag</b>
      </span>
    </div>
  )
}

/** The grc-rag console: ask → cited answer → click a citation through to the exact clause, or an
 * honest refusal, with the retrieval pipeline shown while answering and the eval scorecard below. */
export function App() {
  const [loading, setLoading] = useState(false)
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<Result>({ kind: 'idle' })

  async function handleAsk(q: string) {
    setQuestion(q)
    setLoading(true)
    setResult({ kind: 'idle' })
    try {
      const response = await ask(q)
      setResult(response.refused ? { kind: 'refusal', response } : { kind: 'answer', response })
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'An unexpected error occurred.'
      setResult({ kind: 'error', message })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__header-inner">
          <Wordmark />
          <div className="app__brandside">
            <div className="corpus-tags">
              {CORPUS_TAGS.map((t) => (
                <span key={t} className="corpus-tags__tag">
                  {t}
                </span>
              ))}
            </div>
            <GateBadge sub="eval gate" />
          </div>
        </div>
      </header>

      <main className="app__main">
        <div className="hero">
          <h1 className="hero__title">Cited answers from AI governance standards</h1>
          <p className="hero__sub">
            Grounded, cite-or-refuse Q&amp;A over AI-governance regulation. Every claim cites the exact
            clause, or the system declines instead of guessing.
          </p>
        </div>

        <div className="ask-wrap">
          <AskBox onAsk={handleAsk} loading={loading} />
          <div className="example-chips">
            <span className="example-chips__label">Try</span>
            {EXAMPLES.map((q) => (
              <button
                key={q}
                type="button"
                className="example-chip"
                disabled={loading}
                onClick={() => handleAsk(q)}
              >
                {q}
              </button>
            ))}
          </div>
        </div>

        <div className="result" aria-live="polite">
          {loading && <RetrievalPipeline question={question} />}

          {!loading && result.kind === 'error' && <ErrorNotice message={result.message} />}

          {!loading && result.kind === 'refusal' && (
            <>
              <RefusalNotice answer={result.response.answer} />
              <RetrievalPanel retrieved={result.response.retrieved} latencyMs={result.response.latency_ms} />
              <EvalStrip />
            </>
          )}

          {!loading && result.kind === 'answer' && (
            <>
              <AnswerView answer={result.response.answer} citations={result.response.citations} />
              <RetrievalPanel retrieved={result.response.retrieved} latencyMs={result.response.latency_ms} />
              <EvalStrip />
            </>
          )}

          {!loading && result.kind === 'idle' && (
            <div className="idle-hint">
              <p>
                Ask a question to see hybrid retrieval, reranking, and a cited answer, with the eval
                scorecard below.
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
