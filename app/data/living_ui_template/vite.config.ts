import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: {{PORT}},
    host: true,
    // Never show Vite's red error overlay: the live preview must degrade to
    // the last working state while the agent is mid-write, not to a stack
    // trace (the host UI and the reveal engine handle broken states).
    hmr: { overlay: false },
    proxy: {
      '/api': 'http://localhost:{{BACKEND_PORT}}',
    },
  },
  preview: {
    port: {{PORT}},
    host: true,
    proxy: {
      '/api': 'http://localhost:{{BACKEND_PORT}}',
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
