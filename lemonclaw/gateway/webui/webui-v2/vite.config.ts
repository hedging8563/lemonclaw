import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import preact from '@preact/preset-vite'

// https://vite.dev/config/
export default defineConfig({
  // Force the preset to use its Babel path with the current Vite 8 beta toolchain.
  // This avoids the deprecated `esbuild` option warning until preset-vite fully aligns with Vite 8 / oxc.
  plugins: [preact({ babel: {} })],
  build: {
    // The Python gateway serves files from ../static, so production builds write there directly.
    outDir: fileURLToPath(new URL('../static', import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:18789',
      '/ws': { target: 'ws://localhost:18789', ws: true },
      '/health': 'http://localhost:18789',
    }
  }
})
