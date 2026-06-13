import type { AskResponse } from './types'

// Config, not hardcode: the API base comes from a Vite env var so dev (localhost) and a deployed
// build differ by configuration, not code. Falls back to the local uvicorn default.
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

/**
 * A non-2xx response from the API — a genuine *failure* (network, 4xx, 5xx), as distinct from a
 * *refusal* (a successful 200 carrying `refused: true`). The UI branches on the two differently:
 * a refusal is the trust story shown calmly; an ApiError is an error toast.
 */
export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** POST a question to `${VITE_API_BASE}/ask` and parse the `AskResponse`. Throws `ApiError` on
 * any non-2xx so the caller can distinguish failure from a refusal. */
export async function ask(question: string): Promise<AskResponse> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    })
  } catch {
    // A transport failure (server down, CORS, offline) never reached an HTTP status.
    throw new ApiError('Could not reach the grc-rag API.', 0)
  }

  if (!response.ok) {
    throw new ApiError(`The grc-rag API responded with status ${response.status}.`, response.status)
  }

  return (await response.json()) as AskResponse
}
