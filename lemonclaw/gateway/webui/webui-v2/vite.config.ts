import { defineConfig } from 'vite'
import preact from '@preact/preset-vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [preact()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:18789',
      '/ws': { target: 'ws://localhost:18789', ws: true },
      '/health': 'http://localhost:18789',
    }
  }
})
