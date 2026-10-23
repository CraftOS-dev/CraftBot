import { build } from 'esbuild'
import { readFileSync } from 'fs'
import path from 'path'
import type { Plugin } from 'vite'

/**
 * The libraries a Generative UI output can preload (render_ui's `libraries`;
 * the names mirror LIBRARIES in app/generative_ui.py). An output's sandbox
 * runs inline code only, so each library is bundled here into one classic
 * script that sets its global, and the runtime inlines it before the
 * output's own scripts. Nothing is fetched from the network.
 *
 * Each `virtual:generative-ui-library/<name>` module's default export is
 * `{ script, style? }`, loaded on demand (src/components/GenerativeUI/assets.ts).
 */
const PREFIX = 'virtual:generative-ui-library/'
const root = __dirname
const modules = path.join(root, 'node_modules')

const dataUrl = (file: string) => `data:image/png;base64,${readFileSync(file).toString('base64')}`
const leafletImage = (name: string) => dataUrl(path.join(modules, 'leaflet/dist/images', name))
// Reduced motion is honoured here for what the libraries animate; the
// runtime's stylesheet covers CSS animations and transitions.
const reduceMotion = "matchMedia('(prefers-reduced-motion: reduce)').matches"

const ENTRIES: Record<string, () => { entry: string; style?: string }> = {
  // Charts take the host's type and colours (the runtime sets --cb-* before
  // any library runs) and follow its theme; a page can still set its own.
  // A chart copies its axes' default colours into its own config when it is
  // built, so a theme change carries those copies over before redrawing.
  chart: () => ({
    entry: `import Chart from 'chart.js/auto'
      let current
      const theme = () => {
        const token = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim()
        current = { font: token('--cb-font'), color: token('--cb-muted'), border: token('--cb-border') }
        Chart.defaults.font.family = current.font
        Chart.defaults.color = current.color
        // Axis lines only: changing Chart.defaults.borderColor would switch
        // off Chart.js's default dataset palette.
        Chart.defaults.scale.grid.color = current.border
        Chart.defaults.scale.border.color = current.border
      }
      const recolor = (options, from) => {
        for (const key in options) {
          const value = options[key]
          if (value && typeof value === 'object') recolor(value, from)
          else if (value === from.color) options[key] = current.color
          else if (value === from.border) options[key] = current.border
        }
      }
      theme()
      addEventListener('craftbot-theme', () => {
        const from = current
        theme()
        Object.values(Chart.instances).forEach(chart => { recolor(chart.config.options.scales || {}, from); chart.update() })
      })
      if (${reduceMotion}) Chart.defaults.animation = false
      globalThis.Chart = Chart`,
  }),
  // Marker and layer images ship inline: the sandbox loads data: images only.
  // L.tileLayer.craftbot() is the base map: tiles CraftBot fetches for the
  // page (window.craftbot.map). The controls and popups follow the theme.
  leaflet: () => ({
    entry: `import * as L from 'leaflet/dist/leaflet-src.esm.js'
      L.Icon.Default.imagePath = ''
      L.Icon.Default.mergeOptions(${JSON.stringify({
        iconUrl: leafletImage('marker-icon.png'),
        iconRetinaUrl: leafletImage('marker-icon-2x.png'),
        shadowUrl: leafletImage('marker-shadow.png'),
      })})
      L.tileLayer.craftbot = (options = {}) => {
        const { tiles, attribution, maxZoom } = window.craftbot.map
        return L.tileLayer(tiles, { attribution, maxZoom, ...options })
      }
      globalThis.L = L`,
    style: readFileSync(path.join(modules, 'leaflet/dist/leaflet.css'), 'utf8')
      .replace(/url\(images\/([\w-]+\.png)\)/g, (_, name: string) => `url(${leafletImage(name)})`) +
      '.leaflet-container{background:var(--cb-surface);font-family:var(--cb-font)}' +
      '.leaflet-bar,.leaflet-control-layers{border-color:var(--cb-border)!important}' +
      '.leaflet-bar a,.leaflet-control-layers,.leaflet-popup-content-wrapper,.leaflet-popup-tip{background:var(--cb-surface);color:var(--cb-text)}' +
      '.leaflet-bar a{border-bottom-color:var(--cb-border)}.leaflet-bar a:hover{background:var(--cb-bg)}' +
      '.leaflet-container .leaflet-control-attribution{background:color-mix(in srgb,var(--cb-surface) 85%,transparent);color:var(--cb-muted)}' +
      '.leaflet-container .leaflet-control-attribution a{color:var(--cb-text)}',
  }),
  // The UMD build's API: createIcons() replaces every <i data-lucide="name">.
  lucide: () => ({
    entry: `import { createIcons, icons } from 'lucide'
      globalThis.lucide = { icons, createIcons: (options = {}) => createIcons({ icons, ...options }) }`,
  }),
  motion: () => ({
    entry: `import * as Motion from 'motion'
      if (${reduceMotion}) Motion.MotionGlobalConfig.skipAnimations = true
      globalThis.Motion = Motion`,
  }),
  three: () => ({
    entry: `import * as THREE from 'three'
      import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
      globalThis.THREE = { ...THREE, OrbitControls }`,
  }),
}

async function bundle(name: string): Promise<{ script: string; style?: string }> {
  const { entry, style } = ENTRIES[name]()
  const result = await build({
    stdin: { contents: entry, resolveDir: root, loader: 'js' },
    bundle: true,
    format: 'iife',
    platform: 'browser',
    target: 'es2020',
    minify: true,
    write: false,
    // The libraries' license notices travel with their code.
    legalComments: 'eof',
    define: { 'process.env.NODE_ENV': '"production"' },
  })
  const script = result.outputFiles[0].text
  // The runtime inserts these as raw element text: nothing in them may end
  // the element early or open an HTML comment.
  if (/<\/script|<!--/i.test(script) || (style && /<\/style/i.test(style))) {
    throw new Error(`Generative UI library ${name} contains markup that would end its element`)
  }
  return { script, style }
}

export function generativeUILibraries(): Plugin {
  const built = new Map<string, Promise<{ script: string; style?: string }>>()
  return {
    name: 'generative-ui-libraries',
    resolveId(id) {
      if (id.startsWith(PREFIX) && id.slice(PREFIX.length) in ENTRIES) return '\0' + id
    },
    async load(id) {
      if (!id.startsWith('\0' + PREFIX)) return
      const name = id.slice(PREFIX.length + 1)
      if (!built.has(name)) built.set(name, bundle(name))
      return `export default ${JSON.stringify(await built.get(name))}`
    },
  }
}
