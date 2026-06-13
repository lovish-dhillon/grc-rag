import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, ask } from './api'
import type { AskResponse } from './types'

const FIXTURE: AskResponse = {
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
  retrieved: [{ chunk_id: 'eu-ai-act::5', clause_label: 'EU AI Act — Article 5', score: 8.2 }],
  prompt_version: 'cite-or-refuse/v2',
  latency_ms: 142,
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ask()', () => {
  it('POSTs the question to ${VITE_API_BASE}/ask and parses the AskResponse', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => FIXTURE })
    vi.stubGlobal('fetch', fetchMock)

    const result = await ask('Which AI practices are prohibited?')

    expect(result).toEqual(FIXTURE)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toMatch(/\/ask$/)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({
      question: 'Which AI practices are prohibited?',
    })
  })

  it('throws an ApiError carrying the status on a non-2xx (500)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }))

    await expect(ask('boom')).rejects.toBeInstanceOf(ApiError)
    await expect(ask('boom')).rejects.toMatchObject({ status: 500 })
  })

  it('throws an ApiError (status 0) when the request never reaches the server', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(ask('offline?')).rejects.toMatchObject({ status: 0 })
  })
})
