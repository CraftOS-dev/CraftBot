/**
 * Check a declared views.json against the app's operations. The rules make
 * "every feature is reachable through a declared op" hold for everything a
 * person sees: a source must be a read op, an action must name a declared op,
 * and keys must be unique and free.
 */
import { isReadOp, RESERVED_KEYS } from './generate.ts'
import type { Action, Block, OpRef, Operation, Screen } from './types.ts'

export interface ViewsProblem {
  where: string
  message: string
}

const BLOCK_FIELDS: Record<Block['type'], string[]> = {
  metrics: ['items'],
  keyvalue: [],
  table: ['rows', 'columns'],
  list: ['items', 'primary'],
  bars: ['series', 'x', 'y'],
  sparkline: ['series', 'y'],
  text: [],
  auto: [],
}

export function validateViews(raw: unknown, operations: Operation[]): ViewsProblem[] {
  const problems: ViewsProblem[] = []
  const add = (where: string, message: string) => problems.push({ where, message })
  const byName = new Map(operations.map(op => [op.name, op]))

  if (raw === null || typeof raw !== 'object') return [{ where: 'views.json', message: 'must be a JSON object' }]
  const views = raw as { viewsVersion?: unknown; home?: unknown; screens?: unknown }
  if (views.viewsVersion !== 1) add('viewsVersion', 'must be 1')
  if (!Array.isArray(views.screens) || views.screens.length === 0) {
    add('screens', 'declare at least one screen')
    return problems
  }

  const checkOp = (ref: OpRef | undefined, where: string, mustRead: boolean, inRow: boolean) => {
    if (ref === undefined) return
    const op = byName.get(ref.op)
    if (!op) {
      add(where, `op "${ref.op}" is not declared in operations.json`)
      return
    }
    if (mustRead && !isReadOp(op)) add(where, `source op "${ref.op}" changes data; a source must be a read op (GET, or readOnly: true)`)
    for (const [name, value] of Object.entries(ref.params ?? {})) {
      if (!(name in (op.params ?? {}))) add(where, `op "${ref.op}" has no param "${name}"`)
      if (typeof value === 'string' && value.startsWith('$row.') && !inRow) add(where, `"${value}" binds a row, which only row actions have`)
    }
  }

  const ids = new Set<string>()
  views.screens.forEach((s: unknown, i: number) => {
    const where = `screens[${i}]`
    if (s === null || typeof s !== 'object') {
      add(where, 'must be an object')
      return
    }
    const screen = s as Screen
    if (typeof screen.id !== 'string' || !screen.id) add(where, 'needs an id')
    else if (ids.has(screen.id)) add(where, `duplicate screen id "${screen.id}"`)
    else ids.add(screen.id)
    if (typeof screen.title !== 'string' || !screen.title) add(where, 'needs a title written for people')
    checkOp(screen.source, `${where}.source`, true, false)

    const keys = new Set<string>()
    const checkActions = (actions: Action[] | undefined, at: string, inRow: boolean) => {
      for (const [j, action] of (actions ?? []).entries()) {
        const w = `${at}[${j}]`
        if (typeof action.key !== 'string' || [...action.key].length !== 1) add(w, 'key must be one character')
        else if (RESERVED_KEYS.has(action.key)) add(w, `key "${action.key}" is kept for navigation; pick another`)
        else if (!inRow && keys.has(action.key)) add(w, `key "${action.key}" is used twice on this screen`)
        else if (!inRow) keys.add(action.key)
        checkOp(action, w, false, inRow)
      }
    }
    checkActions(screen.actions, `${where}.actions`, false)

    if (!Array.isArray(screen.blocks)) {
      add(where, 'needs a blocks list')
      return
    }
    screen.blocks.forEach((b: Block, j: number) => {
      const bw = `${where}.blocks[${j}]`
      const required = BLOCK_FIELDS[b?.type]
      if (!required) {
        add(bw, `unknown block type "${String(b?.type)}"`)
        return
      }
      for (const field of required) if ((b as unknown as Record<string, unknown>)[field] === undefined) add(bw, `${b.type} needs "${field}"`)
      if (!b.source && !screen.source && b.type !== 'text') add(bw, 'has no data: give it a source op or give the screen one')
      checkOp(b.source, `${bw}.source`, true, false)
      if (b.type === 'table' || b.type === 'list') checkActions(b.rowActions, `${bw}.rowActions`, true)
    })
  })
  if (views.home !== undefined && (typeof views.home !== 'string' || !ids.has(views.home))) add('home', 'must name one of the screens')
  return problems
}
