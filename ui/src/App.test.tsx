import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from './App'
import { ApiError, ask } from './api'
import type { AskResponse } from './types'

// Mock only `ask` — keep the real `ApiError` so App's `instanceof ApiError` branch works.
vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return { ...actual, ask: vi.fn() }
})

const askMock = vi.mocked(ask)

const CITED: AskResponse = {
  question: 'Which AI practices are prohibited?',
  answer: 'Certain practices are prohibited [eu-ai-act::5].',
  refused: false,
  citations: [
    {
      chunk_id: 'eu-ai-act::5',
      doc_id: 'eu-ai-act',
      clause_label: 'EU AI Act — Article 5',
      text: 'The following AI practices shall be prohibited.',
      score: 8.2,
    },
  ],
  retrieved: [
    { chunk_id: 'eu-ai-act::5', clause_label: 'EU AI Act — Article 5', score: 8.2 },
    { chunk_id: 'eu-ai-act::10', clause_label: 'EU AI Act — Article 10', score: 4.1 },
  ],
  prompt_version: 'cite-or-refuse/v3',
  latency_ms: 142,
}

const REFUSAL: AskResponse = {
  question: 'What does ISO 42001 clause 6 require?',
  answer: 'Not supported by the corpus.',
  refused: true,
  citations: [],
  retrieved: [],
  prompt_version: 'cite-or-refuse/v3',
  latency_ms: 11,
}

afterEach(() => {
  vi.clearAllMocks()
})

async function submitQuestion(user: ReturnType<typeof userEvent.setup>, question: string) {
  await user.type(screen.getByLabelText(/ask a question/i), question)
  await user.click(screen.getByRole('button', { name: /^ask$/i }))
}

describe('App — result states', () => {
  it('renders a cited answer with a working click-through', async () => {
    const user = userEvent.setup()
    askMock.mockResolvedValue(CITED)
    render(<App />)

    await submitQuestion(user, 'Which AI practices are prohibited?')

    const chip = await screen.findByRole('button', { name: 'EU AI Act — Article 5' })
    expect(screen.queryByText(CITED.citations[0].text)).not.toBeInTheDocument()
    await user.click(chip)
    expect(screen.getByText(CITED.citations[0].text)).toBeInTheDocument()
    // Not a refusal (the header CI-gate badge is also role="status", so scope by name) / not an error.
    expect(screen.queryByRole('status', { name: 'Refusal' })).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows a first-class refusal — distinct from an error, with no citation chips', async () => {
    const user = userEvent.setup()
    askMock.mockResolvedValue(REFUSAL)
    render(<App />)

    await submitQuestion(user, 'What does ISO 42001 clause 6 require?')

    const refusal = await screen.findByRole('status', { name: 'Refusal' })
    expect(within(refusal).getByText(REFUSAL.answer)).toBeInTheDocument()
    // A refusal is NOT an error, and fabricates no citation.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /article/i })).not.toBeInTheDocument()
  })

  it('shows an error notice (not a refusal) when the request fails', async () => {
    const user = userEvent.setup()
    askMock.mockRejectedValue(new ApiError('The grc-rag API responded with status 500.', 500))
    render(<App />)

    await submitQuestion(user, 'trigger a failure')

    const error = await screen.findByRole('alert')
    expect(within(error).getByText(/status 500/i)).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Refusal' })).not.toBeInTheDocument() // not a refusal
  })
})

describe('App — ask box guards', () => {
  it('disables submit on empty / whitespace-only input', async () => {
    const user = userEvent.setup()
    render(<App />)
    const submit = screen.getByRole('button', { name: /^ask$/i })

    expect(submit).toBeDisabled() // empty
    await user.type(screen.getByLabelText(/ask a question/i), '   ')
    expect(submit).toBeDisabled() // whitespace only
    await user.type(screen.getByLabelText(/ask a question/i), 'real question')
    expect(submit).toBeEnabled()
  })

  it('disables submit while a request is in flight', async () => {
    const user = userEvent.setup()
    let resolve!: (value: AskResponse) => void
    askMock.mockReturnValue(new Promise<AskResponse>((r) => (resolve = r)))
    render(<App />)

    await submitQuestion(user, 'a question in flight')

    const submit = screen.getByRole('button', { name: /retrieving/i })
    expect(submit).toBeDisabled()
    resolve(CITED) // let it settle so React state updates after the test
    await screen.findByRole('button', { name: /^ask$/i })
  })
})

describe('App — retrieval panel', () => {
  it('is collapsed by default and expands to ranked clauses + scores + latency', async () => {
    const user = userEvent.setup()
    askMock.mockResolvedValue(CITED)
    render(<App />)

    await submitQuestion(user, 'Which AI practices are prohibited?')

    const toggle = await screen.findByRole('button', { name: /how it answered/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('list', { name: /retrieved clauses/i })).not.toBeInTheDocument()
    expect(screen.getByText('142 ms')).toBeInTheDocument() // latency visible on the toggle

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const list = screen.getByRole('list', { name: /retrieved clauses/i })
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
    expect(within(list).getByText('8.200')).toBeInTheDocument() // a rendered score
  })
})
