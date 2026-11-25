import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Dev server proxies API calls to the FastAPI backend (spec section 5).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
