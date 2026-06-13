import { useState, type FormEvent } from 'react'

interface AskBoxProps {
  onAsk: (question: string) => void
  loading: boolean
}

function SearchIcon() {
  return (
    <svg
      className="grc-ask__icon"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.2-3.2" />
    </svg>
  )
}

/** The question input: a bordered field with a leading search glyph and an inline submit. Submit
 * is guarded — disabled while a request is in flight, and while the box is empty or whitespace. */
export function AskBox({ onAsk, loading }: AskBoxProps) {
  const [value, setValue] = useState('')
  const canSubmit = !loading && value.trim().length > 0

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) return
    onAsk(value.trim())
  }

  return (
    <form className="grc-ask" onSubmit={handleSubmit}>
      <label className="grc-ask__label" htmlFor="question">
        Ask a question about AI-governance regulation
      </label>
      <div className="grc-ask__row">
        <div className="grc-ask__field">
          <SearchIcon />
          <input
            id="question"
            className="grc-ask__input"
            type="text"
            value={value}
            autoComplete="off"
            placeholder="e.g. Which AI practices are prohibited under the EU AI Act?"
            onChange={(event) => setValue(event.target.value)}
            disabled={loading}
          />
        </div>
        <button type="submit" className="grc-ask__submit" disabled={!canSubmit}>
          {loading ? (
            <>
              <span className="grc-ask__spinner" />
              Retrieving…
            </>
          ) : (
            'Ask'
          )}
        </button>
      </div>
    </form>
  )
}
