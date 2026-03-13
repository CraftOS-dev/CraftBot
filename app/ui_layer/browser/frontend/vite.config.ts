import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: parseInt(process.env.VITE_PORT || '7925'),
    proxy: {
      '/ws': {
        target: `ws://localhost:${process.env.VITE_BACKEND_PORT || '7926'}`,
        ws: true,
      },
      '/api': {
        target: `http://localhost:${process.env.VITE_BACKEND_PORT || '7926'}`,
      },
    },
  },
})
