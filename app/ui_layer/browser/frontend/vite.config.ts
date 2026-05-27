import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@mascot': path.resolve(__dirname, '../../components/Mascot'),
      // The Mascot module lives outside frontend/, so its imports of
      // bare specifiers like 'react' can't be resolved by walking up
      // from the file. Map them explicitly to the frontend's node_modules.
      'react': path.resolve(__dirname, 'node_modules/react'),
      'react-dom': path.resolve(__dirname, 'node_modules/react-dom'),
      'lucide-react': path.resolve(__dirname, 'node_modules/lucide-react'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: parseInt(process.env.VITE_PORT || '7925'),
    strictPort: true,
    // The Mascot module lives in ../../components/Mascot (outside frontend/),
    // so add the ui_layer root to the FS allowlist.
    fs: {
      allow: [path.resolve(__dirname, '../../')],
    },
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
