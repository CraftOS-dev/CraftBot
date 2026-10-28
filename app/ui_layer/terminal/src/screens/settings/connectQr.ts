/**
 * WhatsApp's link QR in the terminal. The backend only sends the QR as a PNG
 * data URL (the bridge renders it with `qrcode.toDataURL`), so this module
 * decodes the PNG, finds the module grid and draws it with half blocks: one
 * column and half a row per module, which is square in a 1:2 terminal cell.
 * Pure functions, no I/O (unit-tested).
 */
import { inflateSync } from 'node:zlib'

export interface GrayImage {
  width: number
  height: number
  /** Luminance 0..255 per pixel, row by row, alpha composited on white. */
  gray: Uint8Array
}

/** The bytes of a `data:image/png;base64,...` URL; null for anything else. */
export function pngFromDataUrl(dataUrl: string): Buffer | null {
  const match = /^data:image\/png;base64,([A-Za-z0-9+/=\s]+)$/.exec(dataUrl.trim())
  if (!match) return null
  const bytes = Buffer.from(match[1].replace(/\s+/g, ''), 'base64')
  return bytes.length > 8 ? bytes : null
}

const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10]
const CHANNELS: Record<number, number> = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c
  const pa = Math.abs(p - a)
  const pb = Math.abs(p - b)
  const pc = Math.abs(p - c)
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c
}

/** Decode a non-interlaced PNG to luminance. Throws on anything it cannot read. */
export function decodePng(png: Buffer): GrayImage {
  for (let i = 0; i < SIGNATURE.length; i++) {
    if (png[i] !== SIGNATURE[i]) throw new Error('not a PNG')
  }
  let width = 0
  let height = 0
  let depth = 0
  let colorType = 0
  let interlace = 0
  let palette: Buffer | null = null
  let paletteAlpha: Buffer | null = null
  const idat: Buffer[] = []
  let pos = 8
  while (pos + 8 <= png.length) {
    const length = png.readUInt32BE(pos)
    const type = png.toString('latin1', pos + 4, pos + 8)
    const data = png.subarray(pos + 8, pos + 8 + length)
    pos += 12 + length
    if (type === 'IHDR') {
      width = data.readUInt32BE(0)
      height = data.readUInt32BE(4)
      depth = data[8]
      colorType = data[9]
      interlace = data[12]
    } else if (type === 'PLTE') palette = data
    else if (type === 'tRNS') paletteAlpha = data
    else if (type === 'IDAT') idat.push(data)
    else if (type === 'IEND') break
  }
  const channels = CHANNELS[colorType]
  if (!width || !height || !channels) throw new Error('unsupported PNG header')
  if (interlace !== 0) throw new Error('interlaced PNG')
  if (colorType === 3 && !palette) throw new Error('PNG palette missing')

  const raw = inflateSync(Buffer.concat(idat))
  const bitsPerPixel = channels * depth
  const stride = Math.ceil((width * bitsPerPixel) / 8)
  const bpp = Math.max(1, bitsPerPixel >> 3)
  if (raw.length < height * (stride + 1)) throw new Error('PNG data truncated')

  const pixels = Buffer.alloc(height * stride)
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)]
    const src = y * (stride + 1) + 1
    const row = y * stride
    const prev = row - stride
    for (let x = 0; x < stride; x++) {
      const value = raw[src + x]
      const left = x >= bpp ? pixels[row + x - bpp] : 0
      const up = y > 0 ? pixels[prev + x] : 0
      const upLeft = y > 0 && x >= bpp ? pixels[prev + x - bpp] : 0
      let out: number
      if (filter === 0) out = value
      else if (filter === 1) out = value + left
      else if (filter === 2) out = value + up
      else if (filter === 3) out = value + ((left + up) >> 1)
      else if (filter === 4) out = value + paeth(left, up, upLeft)
      else throw new Error(`unknown PNG filter ${filter}`)
      pixels[row + x] = out & 0xff
    }
  }

  const max = (1 << depth) - 1
  const sample = (row: number, index: number): number => {
    if (depth === 8) return pixels[row + index]
    if (depth === 16) return pixels[row + index * 2]
    const bit = index * depth
    return (pixels[row + (bit >> 3)] >> (8 - depth - (bit & 7))) & max
  }
  const scale = depth === 16 || depth === 8 ? 1 : 255 / max
  const gray = new Uint8Array(width * height)
  for (let y = 0; y < height; y++) {
    const row = y * stride
    for (let x = 0; x < width; x++) {
      let r: number
      let g: number
      let b: number
      let a = 255
      if (colorType === 3) {
        const index = sample(row, x)
        r = palette![index * 3]
        g = palette![index * 3 + 1]
        b = palette![index * 3 + 2]
        if (paletteAlpha && index < paletteAlpha.length) a = paletteAlpha[index]
      } else {
        const base = x * channels
        if (colorType === 0 || colorType === 4) {
          r = g = b = Math.round(sample(row, base) * scale)
          if (colorType === 4) a = sample(row, base + 1)
        } else {
          r = sample(row, base)
          g = sample(row, base + 1)
          b = sample(row, base + 2)
          if (colorType === 6) a = sample(row, base + 3)
        }
      }
      const lum = 0.299 * r + 0.587 * g + 0.114 * b
      gray[y * width + x] = Math.round((lum * a + 255 * (255 - a)) / 255)
    }
  }
  return { width, height, gray }
}

/**
 * Recover a QR code's module matrix (true = dark) from an image of it. The
 * top-left finder pattern starts the dark area with a run of exactly seven
 * modules, which gives the module size; the dark area's width gives the
 * module count, snapped to a valid QR size (17 + 4 * version).
 */
export function qrMatrixFromImage(image: GrayImage): boolean[][] | null {
  const { width, height, gray } = image
  const dark = (x: number, y: number) => gray[y * width + x] < 128
  let minX = width
  let minY = height
  let maxX = -1
  let maxY = -1
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (!dark(x, y)) continue
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (y < minY) minY = y
      if (y > maxY) maxY = y
    }
  }
  if (maxX < 0) return null
  let run = 0
  while (minX + run <= maxX && dark(minX + run, minY)) run++
  const moduleSize = run / 7
  if (moduleSize < 1) return null
  const span = maxX - minX + 1
  let count = Math.round(span / moduleSize)
  const snapped = Math.round((count - 17) / 4) * 4 + 17
  if (Math.abs(snapped - count) <= 1) count = snapped
  if (count < 21 || count > 177) return null
  const sizeX = span / count
  const sizeY = (maxY - minY + 1) / count
  const matrix: boolean[][] = []
  for (let row = 0; row < count; row++) {
    const line: boolean[] = []
    const y = Math.min(height - 1, Math.floor(minY + (row + 0.5) * sizeY))
    for (let col = 0; col < count; col++) {
      const x = Math.min(width - 1, Math.floor(minX + (col + 0.5) * sizeX))
      line.push(dark(x, y))
    }
    matrix.push(line)
  }
  return matrix
}

/** The module matrix of a PNG data URL QR code; null when it cannot be read. */
export function qrMatrixFromDataUrl(dataUrl: string): boolean[][] | null {
  const png = pngFromDataUrl(dataUrl)
  if (!png) return null
  try {
    return qrMatrixFromImage(decodePng(png))
  } catch {
    return null
  }
}

/**
 * Half-block lines for a module matrix with a light quiet zone of `quiet`
 * modules. Each character carries two modules (top and bottom).
 * `invert` false: glyphs draw the DARK modules, for text drawn black on an
 * explicit white background. `invert` true: glyphs draw the LIGHT modules,
 * for a terminal without colors whose background is dark.
 */
export function halfBlockLines(matrix: boolean[][], quiet: number, invert: boolean): string[] {
  const size = matrix.length
  const total = size + quiet * 2
  const isDark = (row: number, col: number): boolean => {
    const r = row - quiet
    const c = col - quiet
    if (r < 0 || c < 0 || r >= size || c >= size) return false
    return matrix[r][c]
  }
  const lines: string[] = []
  for (let row = 0; row < total; row += 2) {
    let line = ''
    for (let col = 0; col < total; col++) {
      const top = isDark(row, col) !== invert
      const bottom = row + 1 < total ? isDark(row + 1, col) !== invert : invert
      line += top && bottom ? '█' : top ? '▀' : bottom ? '▄' : ' '
    }
    lines.push(line)
  }
  return lines
}

/** Rows and columns a half-block QR of `size` modules takes with a quiet zone. */
export function qrFootprint(size: number, quiet: number): { rows: number; columns: number } {
  const total = size + quiet * 2
  return { rows: Math.ceil(total / 2), columns: total }
}
