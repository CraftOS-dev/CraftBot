// Build the terminal client into one ES module: dist/craftbot-tui.mjs.
//
//   node build.mjs          minified release bundle
//   node build.mjs --dev    readable bundle with a source map
//
// The client reuses the browser frontend's Redux store read-only. Two of the
// store's imports are browser-only, so this build swaps them for terminal
// modules (never editing the browser frontend):
//   browser/frontend/src/i18n/config.ts      -> src/platform/i18n.ts
//   browser/frontend/src/utils/connection.ts -> src/platform/connection.ts
// Bare imports made by browser files resolve from THIS package's
// node_modules, so there is one copy of each library and the build does not
// depend on the browser frontend's node_modules.
import { build } from 'esbuild'
import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { dirname, join, resolve, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const browserSrc = resolve(here, '../browser/frontend/src')
const dev = process.argv.includes('--dev')

const swaps = new Map([
  [join(browserSrc, 'i18n', 'config'), join(here, 'src', 'platform', 'i18n.ts')],
  [join(browserSrc, 'utils', 'connection'), join(here, 'src', 'platform', 'connection.ts')],
])

function isInside(file, dir) {
  const rel = relative(dir, file)
  return rel !== '' && !rel.startsWith('..') && !rel.startsWith(sep)
}

/** Every locale catalog: the browser's namespaces plus the terminal's own. */
function localeCatalogs() {
  const catalogs = {}
  for (const root of [join(browserSrc, 'locales'), join(here, 'locales')]) {
    if (!existsSync(root)) continue
    for (const lng of readdirSync(root)) {
      const dir = join(root, lng)
      for (const file of readdirSync(dir)) {
        if (!file.endsWith('.json')) continue
        const ns = file.slice(0, -5)
        ;(catalogs[lng] ??= {})[ns] = JSON.parse(readFileSync(join(dir, file), 'utf8'))
      }
    }
  }
  return catalogs
}

const bridge = {
  name: 'browser-store-bridge',
  setup(b) {
    b.onResolve({ filter: /^virtual:locales$/ }, () => ({ path: 'locales', namespace: 'virtual' }))
    b.onLoad({ filter: /.*/, namespace: 'virtual' }, () => ({
      contents: `export default ${JSON.stringify(localeCatalogs())}`,
      loader: 'js',
    }))
    b.onResolve({ filter: /^react-devtools-core$/ }, () => ({ path: 'devtools-stub', namespace: 'stub' }))
    b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ contents: 'export default {}', loader: 'js' }))

    b.onResolve({ filter: /.*/ }, async args => {
      if (!args.importer || !isInside(args.importer, browserSrc)) return undefined
      if (args.path.startsWith('.')) {
        const target = resolve(args.resolveDir, args.path).replace(/\.(ts|tsx)$/, '')
        const swapped = swaps.get(target)
        return swapped ? { path: swapped } : undefined
      }
      if (args.pluginData === 'bridged') return undefined
      // A bare import from a browser file: resolve it from this package.
      const result = await b.resolve(args.path, {
        kind: args.kind,
        resolveDir: here,
        pluginData: 'bridged',
      })
      return result.errors.length ? undefined : { path: result.path, external: result.external }
    })
  },
}

/** Bundle one entry point (the client, or a test harness) the same way. */
export async function bundle(entry, outfile, { devBuild = dev } = {}) {
  await build({
    entryPoints: [entry],
    outfile,
    ...options(devBuild),
  })
}

function options(devBuild) {
  return {
    bundle: true,
    platform: 'node',
    format: 'esm',
    target: 'node24',
    jsx: 'automatic',
    minify: !devBuild,
    sourcemap: devBuild ? 'linked' : false,
    legalComments: 'none',
    logLevel: 'warning',
    define: {
      'process.env.NODE_ENV': devBuild ? '"development"' : '"production"',
      'import.meta.env': '{}',
    },
    banner: {
      // CommonJS dependencies call require(); give the ES module one.
      js: "import { createRequire as __cbCreateRequire } from 'node:module'; const require = __cbCreateRequire(import.meta.url);",
    },
    plugins: [bridge],
  }
}

// `node build.mjs`: build the client. Imported (test harnesses): build nothing.
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  await bundle(join(here, 'src', 'main.tsx'), join(here, 'dist', 'craftbot-tui.mjs'))
}
