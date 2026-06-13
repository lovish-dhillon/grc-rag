import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import './styles.css'

const root = document.getElementById('root')
if (!root) {
  // Fail fast: a missing mount point is a build/HTML error, not something to swallow.
  throw new Error('Root element #root not found in index.html')
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
