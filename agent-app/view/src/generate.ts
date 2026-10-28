/**
 * Views for an app that declares none, generated from its operations:
 *   - Home: the first overview op the app has (home.summary, app.status,
 *     today.get, app.guide), laid out by its shape;
 *   - one screen per area (the op-name prefix: "expenses.add" -> "expenses"),
 *     showing the area's read ops that need no parameters and offering its
 *     other ops as actions.
 * The result has the same shape as a declared views.json, so one renderer
 * serves both.
 */
import { humanize } from './format.ts'
import type { Action, Operation, Screen, ViewsFile } from './types.ts'

export const HOME_OPS = ['home.summary', 'app.status', 'today.get', 'app.guide']

export function areaOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i > 0 ? name.slice(0, i) : name
}

export function verbOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1) : name
}

/** A read op changes nothing: declared readOnly, else an HTTP GET or a crud list. */
export function isReadOp(op: Operation): boolean {
  if (op.readOnly !== undefined) return op.readOnly
  const exec = op.executor
  if (exec.type === 'crud') return (exec.action ?? 'list') === 'list'
  return (exec.method ?? 'POST').toUpperCase() === 'GET'
}

export function requiredParams(op: Operation): string[] {
  return Object.entries(op.params ?? {})
    .filter(([, p]) => p.required === true)
    .map(([name]) => name)
}

export function opLabel(op: Operation): string {
  return op.label ?? humanize(`${verbOf(op.name)} ${areaOf(op.name) === op.name ? '' : areaOf(op.name).split('.').pop() ?? ''}`.trim())
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

/** Keys the app screen keeps for itself; generated actions never take them. */
export const RESERVED_KEYS = new Set(['q', 'j', 'k', 'g', 'h', 'l', 'c', 'r', 'J', 'G', 's', 't', 'p', 'o', 'x', 'v', 'y', 'n'])

export function generateViews(ops: Operation[]): ViewsFile {
  const visible = ops.filter(op => op.system !== true)
  const screens: Screen[] = []
  const home = HOME_OPS.map(name => visible.find(op => op.name === name)).find(
    (op): op is Operation => op !== undefined && requiredParams(op).length === 0,
  )
  if (home) {
    screens.push({ id: 'home', title: 'Home', source: { op: home.name }, blocks: [{ type: 'auto' }] })
  }

  const areas: string[] = []
  for (const op of visible) {
    const area = areaOf(op.name)
    if (!areas.includes(area)) areas.push(area)
  }
  for (const area of areas) {
    const inArea = visible.filter(op => areaOf(op.name) === area && op.name !== home?.name)
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
