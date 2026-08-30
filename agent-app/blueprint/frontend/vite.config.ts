import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, type PluginOption } from 'vite';

// SYSTEM FILE — managed by tooling (spec P1).
// Build output goes to ../pb/pb_public: PocketBase serves the app (spec D5).

/**
 * Coverage instrumentation for DEV builds only (scoped walk-verify,
 * docs/design/scoped-walk-verify.md). The host sets LUI_COVERAGE=1 when it
 * gates a dev copy; live builds never see the flag and stay byte-identical.
 * The plugin is optional: a project whose package.json predates it simply
 * builds uninstrumented (the verifier then records no coverage).
 */
async function coveragePlugins(): Promise<PluginOption[]> {
  if (process.env['LUI_COVERAGE'] !== '1') return [];
  try {
    const spec = 'vite-plugin-istanbul';
    const mod = (await import(/* @vite-ignore */ spec)) as {
      default: (options: Record<string, unknown>) => PluginOption;
    };
    return [
      mod.default({
        include: 'src/app/**',
        exclude: ['node_modules', 'src/kit/**'],
        extension: ['.ts', '.tsx'],
        forceBuildInstrument: true,
      }),
    ];
  } catch {
    return [];
  }
}

export default defineConfig(async () => ({
  plugins: [react(), tailwindcss(), ...(await coveragePlugins())],
  build: {
    outDir: '../pb/pb_public',
    emptyOutDir: true,
  },
  server: {
    port: Number(process.env['LUI_DEV_PORT'] ?? 5173),
    strictPort: false,
  },
}));
