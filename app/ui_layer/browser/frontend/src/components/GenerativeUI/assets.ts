import type { GenerativeUIArtifact } from '../../types'

/** A preloaded library: one classic script setting its global, and its CSS. */
export interface LibraryBundle { script: string; style?: string }

/** What an output's document needs besides its own markup. */
export interface OutputAssets {
  libraries: LibraryBundle[]
  /** By name: the image as a data: URL (the sandbox loads no host files). */
  images: Record<string, string>
  /** With Leaflet: what its base map shows beside the tiles CraftBot serves. */
  map: { attribution: string; maxZoom: number } | null
}

// Bundled on demand by generativeUILibraries.ts; mirrors LIBRARIES in
// app/generative_ui.py.
const LIBRARIES: Record<string, () => Promise<{ default: LibraryBundle }>> = {
  chart: () => import('virtual:generative-ui-library/chart'),
  leaflet: () => import('virtual:generative-ui-library/leaflet'),
  lucide: () => import('virtual:generative-ui-library/lucide'),
  motion: () => import('virtual:generative-ui-library/motion'),
  three: () => import('virtual:generative-ui-library/three'),
}
const MAX_IMAGES = 8

/** Revalidate persisted metadata; an invalid list loads nothing. */
export function validLibraries(value: unknown): string[] {
  if (!Array.isArray(value) || value.some(name => typeof name !== 'string' || !Object.prototype.hasOwnProperty.call(LIBRARIES, name))) return []
  return [...new Set(value as string[])].sort()
}

/** Revalidate persisted metadata: names map to stored image paths
 *  (app/usage/chat_storage.py); anything else loads no images. */
export function validImages(value: unknown): Record<string, string> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  const entries = Object.entries(value)
  if (entries.length > MAX_IMAGES || entries.some(([name, path]) => !/^[A-Za-z_][A-Za-z0-9_]{0,39}$/.test(name) ||
    typeof path !== 'string' || !/^[0-9a-f]{16}\/[A-Za-z0-9_-]{1,80}\/[0-9a-f]{16}\.(?:png|jpg|gif|webp)$/.test(path))) return {}
  return Object.fromEntries(entries) as Record<string, string>
}

function readDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

async function loadMap(): Promise<OutputAssets['map']> {
  const response = await fetch('/api/generative-ui/tiles')
  if (!response.ok) throw new Error(`The map is unavailable (${response.status})`)
  const { attribution, maxZoom } = await response.json()
  return { attribution: String(attribution), maxZoom: Number(maxZoom) }
}

export async function loadAssets(artifact: GenerativeUIArtifact): Promise<OutputAssets> {
  const names = validLibraries(artifact.libraries)
  const [libraries, images, map] = await Promise.all([
    Promise.all(names.map(async name => (await LIBRARIES[name]()).default)),
    Promise.all(Object.entries(validImages(artifact.images)).map(async ([name, path]) => {
      const response = await fetch(`/api/generative-ui/${path}`)
      if (!response.ok) throw new Error(`Image "${name}" is unavailable (${response.status})`)
      return [name, await readDataUrl(await response.blob())] as const
    })),
    names.includes('leaflet') ? loadMap() : null,
  ])
  return { libraries, images: Object.fromEntries(images), map }
}
