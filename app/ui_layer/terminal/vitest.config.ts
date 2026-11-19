import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

const here = dirname(fileURLToPath(import.meta.url))
const browserSrc = resolve(here, '../browser/frontend/src')

// The same swaps as build.mjs: the browser's i18n config and connection
// module are browser-only, so tests load the terminal's own.
const swaps = new Map([
  [join(browserSrc, 'i18n', 'config'), join(here, 'src', 'platform', 'i18n.ts')],
  [join(browserSrc, 'utils', 'connection'), join(here, 'src', 'platform', 'connection.ts')],
])

const LOCALES_ID = '\0virtual:locales'

/** Every locale catalog, as build.mjs bundles them (virtual:locales). */
function localeCatalogs() {
  const catalogs: Record<string, Record<string, unknown>> = {}
  for (const root of [join(browserSrc, 'locales'), join(here, 'locales')]) {
    if (!existsSync(root)) continue
    for (const lng of readdirSync(root)) {
      for (const file of readdirSync(join(root, lng))) {
        if (!file.endsWith('.json')) continue
        ;(catalogs[lng] ??= {})[file.slice(0, -5)] = JSON.parse(readFileSync(join(root, lng, file), 'utf8'))
      }
    }
  }
  return catalogs
}

export default defineConfig({
  plugins: [
    {
      name: 'browser-store-bridge',
      enforce: 'pre',
      resolveId(source, importer) {
        if (source === 'virtual:locales') return LOCALES_ID
        if (!importer || !source.startsWith('.')) return null
        const target = resolve(dirname(importer), source).replace(/\.(ts|tsx)$/, '')
        return swaps.get(target) ?? null
      },
      load(id) {
        return id === LOCALES_ID ? `export default ${JSON.stringify(localeCatalogs())}` : null
      },
    },
  ],
  test: {
    include: ['test/unit/**/*.test.ts'],
    environment: 'node',
    setupFiles: ['test/setup.ts'],
    // Glyphs follow the terminal; tests pin the modern set (and switch per test).
    env: { CRAFTBOT_GLYPHS: 'modern' },
  },
})
