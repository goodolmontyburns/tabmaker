import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/process': 'http://127.0.0.1:8000',
      '/polish': 'http://127.0.0.1:8000',
      '/session': 'http://127.0.0.1:8000',
      '/benchmark': 'http://127.0.0.1:8000',
      '/jobs': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/output': 'http://127.0.0.1:8000',
    },
  },
})
