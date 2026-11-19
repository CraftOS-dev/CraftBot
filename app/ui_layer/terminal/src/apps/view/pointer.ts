/** JSON Pointer (RFC 6901) reads, plus "$row.<field>" bindings for actions. */

export function get(value: unknown, pointer: string | undefined): unknown {
  if (pointer === undefined || pointer === '' || pointer === '/') return value
  if (!pointer.startsWith('/')) return undefined
  let current: unknown = value
  for (const raw of pointer.slice(1).split('/')) {
    const key = raw.replace(/~1/g, '/').replace(/~0/g, '~')
    if (current === null || typeof current !== 'object') return undefined
    current = Array.isArray(current) ? current[Number(key)] : (current as Record<string, unknown>)[key]
  }
  return current
}

/** Fill an action's params: "$row.<field>" takes the field of the selected row. */
export function bindParams(
  params: Record<string, string | number | boolean> | undefined,
  row: Record<string, unknown> | undefined,
): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [name, value] of Object.entries(params ?? {})) {
    if (typeof value === 'string' && value.startsWith('$row.')) {
      const field = value.slice(5)
      const bound = row?.[field]
      if (bound !== undefined && bound !== null) out[name] = typeof bound === 'string' ? bound : JSON.stringify(bound)
    } else {
      out[name] = String(value)
    }
  }
  return out
}
