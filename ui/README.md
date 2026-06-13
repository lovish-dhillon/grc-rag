# grc-rag UI

The demo surface for **grc-rag** — ask a question over AI-governance regulation, read an answer
whose every claim is a clickable citation, and click through to the **exact clause text**, or see
an honest, first-class **refusal** when the corpus can't ground an answer.

A standalone **Vite + React + TypeScript** package. It is intentionally separate from the Python
side — it does **not** touch `pyproject.toml`. It talks to the M12 FastAPI backend
(`POST /ask` → `AskResponse`) over HTTP and owns no cite-or-refuse logic of its own.

## Run it

```bash
# 1. Start the API (from the repo root) — needs the built index + a local Ollama generator
uvicorn grc_rag.api:app --port 8000

# 2. Start the UI (from ui/)
cp .env.example .env.local          # set VITE_API_BASE if the API isn't on :8000
npm install
npm run dev                         # http://localhost:5173
```

| Script | Does |
|---|---|
| `npm run dev` | Vite dev server (HMR) |
| `npm run build` | typecheck (`tsc --noEmit`) + static production bundle → `dist/` |
| `npm run preview` | serve the built `dist/` |
| `npm run test` | Vitest component + API-client tests (jsdom, `fetch` mocked) |
| `npm run typecheck` | `tsc --noEmit` |

## Config, not hardcode

The API base URL comes from `VITE_API_BASE` (see `.env.example`), so dev (localhost) and a
deployed build differ by configuration, not code. Default: `http://localhost:8000`.

## Layout

```
src/
  types.ts              # the wire DTO (mirrors AskResponse in src/grc_rag/api.py)
  api.ts                # typed client: ask(question) → AskResponse; throws ApiError on non-2xx
  App.tsx               # one discriminated result state: idle | answer | refusal | error
  components/
    AskBox.tsx          # input + submit (guarded: disabled while empty/whitespace or in flight)
    AnswerView.tsx      # answer text → inline citation chips
    CitationCard.tsx    # click-through target: clause_label + exact chunk text (no extra request)
    RefusalNotice.tsx   # the honest, first-class refusal (role="status", distinct from errors)
    ErrorNotice.tsx     # network / non-2xx failure (role="alert")
    RetrievalPanel.tsx  # collapsible "how it answered": ranked clauses + scores + latency
  styles.css            # hand-written CSS — no framework (one fewer dependency to defend)
```

## Deploy

`npm run build` emits a static bundle in `dist/`, deployable to any static host (Vercel / Netlify /
GitHub Pages). Point `VITE_API_BASE` at the deployed API and set the API's CORS origin
(`GRC_RAG_CORS_ORIGINS`) to the frontend origin.

## Note on `npm audit`

The reported advisories are all in the **dev toolchain** (`esbuild`'s dev-server CORS issue, via
`vite`/`vitest`) — they affect only `vite dev` on a local machine and **do not** ship in the
production `dist/` bundle. The only remediation is a breaking `vite@8` major bump; we stay on the
stable `vite@6` for the demo and revisit when the ecosystem settles.
