import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

function copyAlphaTabWorkersPlugin() {
  return {
    name: 'copy-alphatab-workers',
    closeBundle() {
      const srcDir = path.resolve(__dirname, 'node_modules/@coderline/alphatab/dist')
      const outDir = path.resolve(__dirname, 'dist/assets')
      if (!fs.existsSync(srcDir) || !fs.existsSync(path.resolve(__dirname, 'dist'))) return
      fs.mkdirSync(outDir, { recursive: true })
      for (const file of ['alphaTab.worker.mjs', 'alphaTab.worklet.mjs', 'alphaTab.core.mjs']) {
        const src = path.join(srcDir, file)
        if (fs.existsSync(src)) {
          fs.copyFileSync(src, path.join(outDir, file))
        }
      }
    },
  }
}

const apiTarget = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), copyAlphaTabWorkersPlugin()],
  optimizeDeps: {
    exclude: ['@coderline/alphatab'],
  },
  server: {
    proxy: {
      '/process': apiTarget,
      '/polish': apiTarget,
      '/session': apiTarget,
      '/benchmark': apiTarget,
      '/jobs': apiTarget,
      '/health': apiTarget,
      '/output': apiTarget,
    },
  },
})
