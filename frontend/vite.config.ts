import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const backendUrl = process.env.FORMA_BACKEND_URL || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  test: { exclude: ['e2e/**', 'node_modules/**', 'dist/**'] },
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': backendUrl,
      '/apps': backendUrl,
    },
  },
})
