import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
// The `debug` mode (`vite build --mode debug`) produces the build the
// platform serves for the verification walk: React runs in DEVELOPMENT so
// runtime errors carry their FULL message and name the offending component
// ("Rendered fewer hooks than expected. Check the render method of `X`")
// instead of the opaque "Minified React error #300", and the output is
// unminified so stack frames keep real names. Legible failures are what let
// a runtime bug be localized and fixed; the production `build` script is
// unchanged.
export default defineConfig(({ mode }) => {
  const debug = mode === 'debug'
  return {
  plugins: [react()],
  define: debug
    ? { 'process.env.NODE_ENV': JSON.stringify('development') }
    : {},
  resolve: {
    // `@/` = frontend/ — the import shape the component library
    // (shadcn/ui) and generated code use: `@/components/ui/button`.
    alias: {
      '@': path.resolve(__dirname, 'frontend'),
    },
  },
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
    // Debug build stays unminified so React error stacks name real
    // components/files; production build minifies as usual.
    minify: debug ? false : 'esbuild',
  },
  }
})
