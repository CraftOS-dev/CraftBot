import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: {{PORT}},
    host: true,
    // Accept any Host header so a hosted reverse proxy (e.g. lui-{{PORT}}.craft-dev.com)
    // can forward to this server without Vite's "Blocked request" host check.
    allowedHosts: true,
    proxy: {
      '/api': 'http://localhost:{{BACKEND_PORT}}',
      '/health': 'http://localhost:{{BACKEND_PORT}}',
    },
  },
  preview: {
    port: {{PORT}},
    host: true,
    allowedHosts: true,
    proxy: {
      '/api': 'http://localhost:{{BACKEND_PORT}}',
      '/health': 'http://localhost:{{BACKEND_PORT}}',
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
