/**
 * An app's screens, generated from the operations it declares:
 *   - Home: the first overview op the app has (home.summary, app.status,
 *     today.get, app.guide), laid out by its shape;
 *   - one screen per module (the op's declared module, else its name prefix:
 *     "expenses.add" -> "expenses"), showing the module's read ops that need
 *     no parameters and offering its other ops as actions.
 */
import { humanize } from './format'
import type { Action, Operation, Screen, ViewsFile } from './types'

export const HOME_OPS = ['home.summary', 'app.status', 'today.get', 'app.guide']

export function areaOf(op: Pick<Operation, 'name' | 'module'>): string {
  if (op.module) return op.module
  const i = op.name.lastIndexOf('.')
  return i > 0 ? op.name.slice(0, i) : op.name
}

export function verbOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1) : name
}

/** A read op changes nothing: declared read-only and not destructive. */
export function isReadOp(op: Operation): boolean {
  return op.readOnly === true && op.destructive !== true
}

export function requiredParams(op: Operation): string[] {
  return Object.entries(op.params ?? {})
    .filter(([, p]) => p.required === true)
    .map(([name]) => name)
}

/** "expenses.add" reads "Add expenses"; a bare name reads as itself. */
export function opLabel(op: Pick<Operation, 'name'>): string {
  const i = op.name.lastIndexOf('.')
  const area = i > 0 ? (op.name.slice(0, i).split('.').pop() ?? '') : ''
  return humanize(`${verbOf(op.name)} ${area}`.trim())
}

const VERB_KEYS: [RegExp, string][] = [
  [/^(add|create|new|log|record)/, 'a'],
  [/^(update|edit|set|rename|change)/, 'e'],
  [/^(delete|remove|archive|cancel)/, 'd'],
]

/** a, e and d always mean add, edit and delete; no other verb borrows them. */
const SEMANTIC_KEYS = new Set(VERB_KEYS.map(([, key]) => key))

/** One key per action: a/e/d by verb when free, else the next free letter of the verb. */
export function assignKeys(ops: Operation[], reserved: Set<string> = new Set()): Action[] {
  const used = new Set(reserved)
  const actions: Action[] = []
  for (const op of ops) {
    const verb = verbOf(op.name).toLowerCase()
    let key = VERB_KEYS.find(([re]) => re.test(verb))?.[1]
    if (key === undefined || used.has(key)) {
      key = [...verb.replace(/[^a-z]/g, ''), ...'bfimuwz'].find(ch => !used.has(ch) && !SEMANTIC_KEYS.has(ch))
    }
    if (key === undefined) continue
    used.add(key)
    actions.push({ key, op: op.name, label: opLabel(op) })
  }
  return actions
}

/**
 * The operations that act on one entity, as keys on its record: the param
 * that names the record (a ref to the entity, or its id) is bound to it.
 */
export function recordActions(ops: Operation[], entity: string): Action[] {
  const bound = ops.filter(op => op.entity === entity && !op.system)
  return assignKeys(bound, RESERVED_KEYS).map(action => {
    const op = bound.find(o => o.name === action.op)!
    const target = Object.entries(op.params ?? {}).find(([name, p]) => (p.type === 'ref' && p.entity === entity) || name === 'id')?.[0]
    return target ? { ...action, params: { [target]: '$row.id' } } : action
  })
}

/** Keys the app screen keeps for itself; generated actions never take them. */
export const RESERVED_KEYS = new Set(['q', 'j', 'k', 'g', 'h', 'l', 'c', 'r', 'J', 'G', 's', 't', 'p', 'o', 'x', 'v', 'y', 'n'])

/** `modules` orders the screens (the manifest's order); modules no op names come last. */
export function generateViews(ops: Operation[], modules: string[] = []): ViewsFile {
  const visible = ops.filter(op => op.system !== true)
  const screens: Screen[] = []
  const home = HOME_OPS.map(name => visible.find(op => op.name === name)).find(
    (op): op is Operation => op !== undefined && isReadOp(op) && requiredParams(op).length === 0,
  )
  if (home) {
    screens.push({ id: 'home', title: 'Home', source: { op: home.name }, blocks: [{ type: 'auto' }] })
  }

  const areas: string[] = [...modules]
  for (const op of visible) {
    const area = areaOf(op)
    if (!areas.includes(area)) areas.push(area)
  }
  for (const area of areas) {
    const inArea = visible.filter(op => areaOf(op) === area && op.name !== home?.name)
    if (inArea.length === 0) continue
    const reads = inArea.filter(op => isReadOp(op) && requiredParams(op).length === 0)
    const others = inArea.filter(op => !reads.includes(op))
    screens.push({
      id: `area:${area}`,
      title: humanize(area.split('.').pop() ?? area),
      blocks: reads.map(op => ({ type: 'auto' as const, source: { op: op.name }, title: opLabel(op) })),
      actions: assignKeys(others, RESERVED_KEYS),
    })
  }
  return { viewsVersion: 1, ...(home ? { home: 'home' } : {}), screens }
}
