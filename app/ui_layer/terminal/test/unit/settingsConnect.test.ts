import { describe, expect, it } from 'vitest'
import { deflateSync } from 'node:zlib'
import QRCode from 'qrcode'
import {
  decodePng,
  halfBlockLines,
  pngFromDataUrl,
  qrFootprint,
  qrMatrixFromDataUrl,
  qrMatrixFromImage,
} from '../../src/screens/settings/connectQr'
import { clipboardPlan, osc52Sequence } from '../../src/screens/settings/connectClipboard'
import { openCommand } from '../../src/screens/settings/connectOpen'

// ── A tiny PNG encoder, to feed the decoder every format it may meet ──

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
  return c >>> 0
})

function crc32(buf: Buffer): number {
  let c = 0xffffffff
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

function chunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length)
  const body = Buffer.concat([Buffer.from(type, 'latin1'), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(body))
  return Buffer.concat([length, body, crc])
}

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c
  const pa = Math.abs(p - a)
  const pb = Math.abs(p - b)
  const pc = Math.abs(p - c)
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c
}

/** Encode raw (unfiltered) scanlines with one filter type for every row. */
function encodePng(opts: {
  width: number
  height: number
  colorType: number
  depth: number
  rows: Buffer[]
  bpp: number
  filter: number
  palette?: Buffer
}): Buffer {
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(opts.width, 0)
  ihdr.writeUInt32BE(opts.height, 4)
  ihdr[8] = opts.depth
  ihdr[9] = opts.colorType
  const filtered: Buffer[] = []
  opts.rows.forEach((row, y) => {
    const prev = y > 0 ? opts.rows[y - 1] : Buffer.alloc(row.length)
    const out = Buffer.alloc(row.length + 1)
    out[0] = opts.filter
    for (let x = 0; x < row.length; x++) {
      const left = x >= opts.bpp ? row[x - opts.bpp] : 0
      const up = prev[x]
      const upLeft = x >= opts.bpp ? prev[x - opts.bpp] : 0
      const predictor =
        opts.filter === 1 ? left : opts.filter === 2 ? up : opts.filter === 3 ? (left + up) >> 1 : opts.filter === 4 ? paeth(left, up, upLeft) : 0
      out[x + 1] = (row[x] - predictor) & 0xff
    }
    filtered.push(out)
  })
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr),
    ...(opts.palette ? [chunk('PLTE', opts.palette)] : []),
    chunk('IDAT', deflateSync(Buffer.concat(filtered))),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

/** A matrix with the three finder patterns and seeded noise elsewhere. */
function syntheticMatrix(size: number, seed: number): boolean[][] {
  let state = seed
  const rand = () => {
    state = (state * 1103515245 + 12345) & 0x7fffffff
    return state / 0x7fffffff
  }
  const m = Array.from({ length: size }, () => Array.from({ length: size }, () => rand() < 0.5))
  const finder = (r0: number, c0: number) => {
    for (let r = -1; r <= 7; r++) {
      for (let c = -1; c <= 7; c++) {
        const rr = r0 + r
        const cc = c0 + c
        if (rr < 0 || cc < 0 || rr >= size || cc >= size) continue
        const ring = Math.max(Math.abs(r - 3), Math.abs(c - 3))
        m[rr][cc] = r >= 0 && r <= 6 && c >= 0 && c <= 6 && ring !== 2
      }
    }
  }
  finder(0, 0)
  finder(0, size - 7)
  finder(size - 7, 0)
  return m
}

/** Rasterize a matrix: `scale` pixels per module, `margin` light modules around. */
function raster(matrix: boolean[][], scale: number, margin: number): boolean[][] {
  const total = (matrix.length + margin * 2) * scale
  return Array.from({ length: total }, (_, y) =>
    Array.from({ length: total }, (_, x) => {
      const r = Math.floor(y / scale) - margin
      const c = Math.floor(x / scale) - margin
      return r >= 0 && c >= 0 && r < matrix.length && c < matrix.length && matrix[r][c]
    }),
  )
}

function modulesOf(text: string): boolean[][] {
  const { modules } = QRCode.create(text, { errorCorrectionLevel: 'M' })
  return Array.from({ length: modules.size }, (_, r) => Array.from({ length: modules.size }, (_, c) => modules.get(r, c) === 1))
}

// A string shaped like a WhatsApp Web link reference (ref plus three base64 keys).
const WHATSAPP_LIKE =
  '2@Xk4m9QpR7sT2vW8yZ1aB3cD5eF6gH0iJ4kL7mN9oP2qR5sT8uV1wX3yZ6aB9cD2eF5gH8iJ1kL4mN7oP0qR3sT6uV9wX2yZ5aB8cD1eF4,' +
  'a2V5LW9uZS1pbi10aGUtd2hhdHNhcHAtbGluay1xcg==,aWRlbnRpdHkta2V5LWZvci10aGUtcXItdGVzdA==,YWR2LXNlY3JldC1mb3ItdGhlLXRlc3Qtb25seQ=='

describe('QR from a PNG data URL', () => {
  it('reads the exact modules of qrcode.toDataURL output (what the WhatsApp bridge sends)', async () => {
    const dataUrl = await QRCode.toDataURL(WHATSAPP_LIKE)
    expect(qrMatrixFromDataUrl(dataUrl)).toEqual(modulesOf(WHATSAPP_LIKE))
  })

  it('reads a 1-bit grayscale PNG with a one-module border (Python qrcode)', () => {
    const matrix = syntheticMatrix(29, 7)
    const pixels = raster(matrix, 10, 1)
    const size = pixels.length
    const rows = pixels.map(line => {
      const row = Buffer.alloc(Math.ceil(size / 8))
      line.forEach((dark, x) => {
        if (!dark) row[x >> 3] |= 0x80 >> (x & 7)
      })
      return row
    })
    const png = encodePng({ width: size, height: size, colorType: 0, depth: 1, rows, bpp: 1, filter: 0 })
    expect(qrMatrixFromImage(decodePng(png))).toEqual(matrix)
  })

  it('undoes every PNG filter on RGBA and palette images', () => {
    const matrix = syntheticMatrix(25, 3)
    const pixels = raster(matrix, 4, 4)
    const size = pixels.length
    for (const filter of [1, 2, 3, 4]) {
      const rgba = pixels.map(line => Buffer.from(line.flatMap(dark => (dark ? [0, 0, 0, 255] : [255, 255, 255, 255]))))
      const png = encodePng({ width: size, height: size, colorType: 6, depth: 8, rows: rgba, bpp: 4, filter })
      expect(qrMatrixFromImage(decodePng(png))).toEqual(matrix)
    }
    const indexed = pixels.map(line => Buffer.from(line.map(dark => (dark ? 1 : 0))))
    const palette = Buffer.from([255, 255, 255, 0, 0, 0])
    const png = encodePng({ width: size, height: size, colorType: 3, depth: 8, rows: indexed, bpp: 1, filter: 4, palette })
    expect(qrMatrixFromImage(decodePng(png))).toEqual(matrix)
  })

  it('composites transparent pixels on white', () => {
    const rows = [Buffer.from([0, 0, 0, 0, 0, 0, 0, 255])]
    const image = decodePng(encodePng({ width: 2, height: 1, colorType: 6, depth: 8, rows, bpp: 4, filter: 0 }))
    expect(Array.from(image.gray)).toEqual([255, 0])
  })

  it('rejects what is not a PNG data URL', () => {
    expect(pngFromDataUrl('data:image/svg+xml;base64,PHN2Zz4=')).toBeNull()
    expect(qrMatrixFromDataUrl('data:image/png;base64,AAAAAAAAAAAAAA==')).toBeNull()
  })
})

describe('half-block QR drawing', () => {
  const m = [
    [true, false],
    [false, true],
  ]

  it('draws dark modules for black-on-white output', () => {
    expect(halfBlockLines(m, 0, false)).toEqual(['▀▄'])
    expect(halfBlockLines([[true, true], [true, true]], 0, false)).toEqual(['██'])
  })

  it('draws light modules when the terminal has no colors', () => {
    expect(halfBlockLines(m, 0, true)).toEqual(['▄▀'])
  })

  it('adds a light quiet zone and handles an odd row count', () => {
    const lines = halfBlockLines([[true]], 1, false)
    // 3x3 modules: rows (0,1) then (2, beyond).
    expect(lines).toEqual([' ▄ ', '   '])
    expect(halfBlockLines([[true]], 1, true)).toEqual(['█▀█', '███'])
  })

  it('reports the footprint', () => {
    expect(qrFootprint(61, 2)).toEqual({ rows: 33, columns: 65 })
    expect(qrFootprint(21, 1)).toEqual({ rows: 12, columns: 23 })
    const lines = halfBlockLines(modulesOf('hello'), 2, false)
    expect(lines.length).toBe(qrFootprint(21, 2).rows)
    expect(lines.every(line => line.length === 25)).toBe(true)
  })
})

describe('clipboard method selection', () => {
  const kinds = (plan: ReturnType<typeof clipboardPlan>) => plan.map(m => (m.kind === 'osc52' ? 'osc52' : m.name))

  it('uses PowerShell Set-Clipboard on Windows, OSC 52 last', () => {
    const plan = clipboardPlan({}, 'win32', true)
    expect(kinds(plan)).toEqual(['Set-Clipboard', 'osc52'])
    const ps = plan[0]
    expect(ps.kind === 'command' && ps.command).toBe('powershell.exe')
    // The value travels on stdin, base64-encoded, never on the command line.
    expect(ps.kind === 'command' && ps.encode).toBe('base64')
    expect(ps.kind === 'command' && ps.args.join(' ')).toContain('[Console]::In.ReadToEnd()')
  })

  it('uses pbcopy on macOS', () => {
    expect(kinds(clipboardPlan({}, 'darwin', true))).toEqual(['pbcopy', 'osc52'])
  })

  it('uses wl-copy on Wayland and xclip then xsel on X11', () => {
    expect(kinds(clipboardPlan({ WAYLAND_DISPLAY: 'wayland-0' }, 'linux', true))).toEqual(['wl-copy', 'osc52'])
    expect(kinds(clipboardPlan({ DISPLAY: ':0' }, 'linux', true))).toEqual(['xclip', 'xsel', 'osc52'])
    expect(kinds(clipboardPlan({ WSL_DISTRO_NAME: 'Ubuntu' }, 'linux', true))).toEqual(['Set-Clipboard', 'osc52'])
  })

  it('falls back to OSC 52 on a headless Linux terminal, and to nothing without a terminal', () => {
    expect(kinds(clipboardPlan({}, 'linux', true))).toEqual(['osc52'])
    expect(kinds(clipboardPlan({}, 'linux', false))).toEqual([])
  })

  it('prefers the local terminal over SSH', () => {
    expect(kinds(clipboardPlan({ SSH_CONNECTION: '1.2.3.4 5 6.7.8.9 22', DISPLAY: ':0' }, 'linux', true))).toEqual(['osc52'])
    expect(kinds(clipboardPlan({ SSH_TTY: '/dev/pts/1' }, 'darwin', true))).toEqual(['osc52'])
  })

  it('builds OSC 52, wrapped for tmux', () => {
    expect(osc52Sequence('hi', {})).toBe('\u001B]52;c;aGk=\u0007')
    expect(osc52Sequence('hi', { TMUX: '/tmp/tmux' })).toBe('\u001BPtmux;\u001B\u001B]52;c;aGk=\u0007\u001B\\')
  })
})

describe('opening links and files', () => {
  it('uses start on Windows, open on macOS, xdg-open on Linux', () => {
    expect(openCommand('https://example.com/?a=1&b=2', 'win32')).toEqual({
      command: 'cmd.exe',
      args: ['/d', '/s', '/c', '"start "" "https://example.com/?a=1&b=2""'],
      verbatim: true,
    })
    expect(openCommand('/tmp/qr.png', 'darwin')).toEqual({ command: 'open', args: ['/tmp/qr.png'], verbatim: false })
    expect(openCommand('/tmp/qr.png', 'linux')).toEqual({ command: 'xdg-open', args: ['/tmp/qr.png'], verbatim: false })
  })

  it('refuses targets that could break out of the argument', () => {
    expect(openCommand('x" & calc', 'win32')).toBeNull()
    expect(openCommand('a\nb', 'linux')).toBeNull()
    expect(openCommand('', 'darwin')).toBeNull()
  })
})
