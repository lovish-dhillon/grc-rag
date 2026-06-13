/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the grc-rag API (e.g. http://localhost:8000). Config, not hardcode. */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
