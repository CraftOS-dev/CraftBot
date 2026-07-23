// Parsing helpers shared by the action display surfaces (timeline rows + mascot formatters).
//
// Action input/output strings arrive as either JSON or Python dict repr
// (e.g. `{'file_path': 'C:\\...', 'count': 42, 'flag': True, 'val': None}`).
// `parseDict` is lenient — it tries JSON first, then falls back to a small
// Python-literal parser that handles single-quoted strings and True/False/None.

export function parseDict(content: string | undefined | null): Record<string, unknown> | null {
  if (!content) return null
  try {
    const parsed = JSON.parse(content)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>
    }
  } catch {
    // fall through to Python dict parser
  }

  const result: Record<string, unknown> = {}
  let inner = content.trim()
  if (inner.startsWith('{') && inner.endsWith('}')) {
    inner = inner.slice(1, -1).trim()
  } else {
    return null
  }

  let i = 0
  while (i < inner.length) {
    while (i < inner.length && (inner[i] === ' ' || inner[i] === ',' || inner[i] === '\n')) i++
    if (i >= inner.length) break

    const keyQuote = inner[i]
    if (keyQuote !== "'" && keyQuote !== '"') {
      i++
      continue
    }
    i++

    let key = ''
    while (i < inner.length && inner[i] !== keyQuote) {
      if (inner[i] === '\\' && i + 1 < inner.length) {
        key += inner[i + 1]
        i += 2
      } else {
        key += inner[i]
        i++
      }
    }
    i++

    while (i < inner.length && (inner[i] === ':' || inner[i] === ' ')) i++
    if (i >= inner.length) break

    let value: unknown
    const valueStart = inner[i]

    if (valueStart === "'" || valueStart === '"') {
      i++
      let str = ''
      while (i < inner.length && inner[i] !== valueStart) {
        if (inner[i] === '\\' && i + 1 < inner.length) {
          const next = inner[i + 1]
          if (next === 'n') str += '\n'
          else if (next === 't') str += '\t'
          else if (next === 'r') str += '\r'
          else str += next
          i += 2
        } else {
          str += inner[i]
          i++
        }
      }
      i++
      value = str
    } else if (valueStart === '{') {
      let depth = 1
      const start = i
      i++
      while (i < inner.length && depth > 0) {
        if (inner[i] === '{') depth++
        else if (inner[i] === '}') depth--
        i++
      }
      value = parseDict(inner.slice(start, i)) ?? inner.slice(start, i)
    } else if (valueStart === '[') {
      let depth = 1
      const start = i
      i++
      while (i < inner.length && depth > 0) {
        if (inner[i] === '[') depth++
        else if (inner[i] === ']') depth--
        i++
      }
      // Store array slices as raw string; renderers that need it can call parseArray.
      value = inner.slice(start, i)
    } else {
      let raw = ''
      while (i < inner.length && inner[i] !== ',' && inner[i] !== '}') {
        raw += inner[i]
        i++
      }
      raw = raw.trim()
      if (raw === 'True') value = true
      else if (raw === 'False') value = false
      else if (raw === 'None') value = null
      else if (!isNaN(Number(raw))) value = Number(raw)
      else value = raw
    }

    if (key) result[key] = value
  }

  return result
}

// Parses a raw "[...]" literal — used to recover arrays that parseDict left
// as raw strings (its top-level dict parser only stores nested arrays as
// slices to keep the implementation small).
export function parseArray(raw: unknown): unknown[] | null {
  if (Array.isArray(raw)) return raw
  if (typeof raw !== 'string') return null

  const trimmed = raw.trim()
  try {
    const parsed = JSON.parse(trimmed)
    if (Array.isArray(parsed)) return parsed
  } catch {
    // fall through
  }
  try {
    const normalized = trimmed
      .replace(/\bTrue\b/g, 'true')
      .replace(/\bFalse\b/g, 'false')
      .replace(/\bNone\b/g, 'null')
      .replace(/'/g, '"')
    const parsed = JSON.parse(normalized)
    if (Array.isArray(parsed)) return parsed
  } catch {
    // ignore
  }
  return null
}

// Typed accessors — keep consumers readable.
export function strField(obj: Record<string, unknown> | null, key: string): string | undefined {
  const v = obj?.[key]
  return typeof v === 'string' ? v : undefined
}

export function arrField(obj: Record<string, unknown> | null, key: string): unknown[] | null {
  return parseArray(obj?.[key])
}

export function dictField(obj: Record<string, unknown> | null, key: string): Record<string, unknown> | null {
  const v = obj?.[key]
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    return v as Record<string, unknown>
  }
  if (typeof v === 'string') {
    return parseDict(v)
  }
  return null
}

// Best-effort filename extraction from a path (handles both / and \).
export function basename(path: string): string {
  const m = path.match(/[/\\]([^/\\]+)$/)
  return m ? m[1] : path
}
