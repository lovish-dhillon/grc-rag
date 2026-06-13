/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Vite + React. Vitest reads the `test` block (jsdom + Testing Library) from this same config,
// so component tests run in a browser-like DOM with no live API (fetch is mocked per test).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.ts',
    css: false,
  },
})
