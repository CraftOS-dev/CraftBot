import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// SYSTEM FILE — managed by tooling (spec P1).
// Build output goes to ../pb/pb_public: PocketBase serves the app (spec D5).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../pb/pb_public',
    emptyOutDir: true,
  },
  server: {
    port: Number(process.env['LUI_DEV_PORT'] ?? 5173),
    strictPort: false,
  },
});
