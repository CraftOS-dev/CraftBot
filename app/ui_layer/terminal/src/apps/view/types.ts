/**
 * What the app screen shows: blocks of an app's data laid out by shape, and
 * the operations the app declares (operations.json, the A2App protocol's
 * vocabulary). Screens are generated from the operations (generate.ts).
 */

export type Format =
  | 'text'
  | 'number'
  | 'percent'
  | 'date'
  | 'datetime'
  | 'boolean'
  | 'money'
  /** money with a currency: a JSON Pointer into the source ("money:/currency") or an ISO code ("money:JPY"). */
  | `money:${string}`

/** A call to a declared operation. Param values may bind to the selected row: "$row.<field>". */
export interface OpRef {
  op: string
  params?: Record<string, string | number | boolean>
}

export interface Column {
  field: string
  label?: string
  format?: Format
  /** 0 = always shown; higher numbers drop first as the width shrinks. */
  priority?: number
}

export interface Action {
  /** One key that runs it. */
  key: string
  op: string
  label?: string
  params?: Record<string, string | number | boolean>
}

interface BlockBase {
  /** Overrides the screen's source for this block. */
  source?: OpRef
  title?: string
}

export interface MetricsBlock extends BlockBase {
  type: 'metrics'
  items: { label: string; value: string; format?: Format }[]
}

export interface KeyValueBlock extends BlockBase {
  type: 'keyvalue'
  /** Pointer to an object; all its scalar fields when `fields` is absent. */
  value?: string
  fields?: { field: string; label?: string; format?: Format }[]
}

export interface TableBlock extends BlockBase {
  type: 'table'
  rows: string
  rowKey?: string
  columns: Column[]
  rowActions?: Action[]
  empty?: string
}

export interface ListBlock extends BlockBase {
  type: 'list'
  items: string
  primary: string
  secondary?: string
  rowKey?: string
  rowActions?: Action[]
  empty?: string
}

export interface BarsBlock extends BlockBase {
  type: 'bars'
  series: string
  x: string
  y: string
  format?: Format
}

export interface SparklineBlock extends BlockBase {
  type: 'sparkline'
  series: string
  y: string
  x?: string
  format?: Format
}

export interface TextBlock extends BlockBase {
  type: 'text'
  /** Pointer to a string in the source, or literal `text`. */
  value?: string
  text?: string
}

/** Lay the value out by its shape (generated views). */
export interface AutoBlock extends BlockBase {
  type: 'auto'
  value?: string
}

export type Block =
  | MetricsBlock
  | KeyValueBlock
  | TableBlock
  | ListBlock
  | BarsBlock
  | SparklineBlock
  | TextBlock
  | AutoBlock

export interface Screen {
  id: string
  title: string
  source?: OpRef
  /** Collections whose changes refresh this screen. */
  refreshOn?: string[]
  blocks: Block[]
  actions?: Action[]
}

export interface ViewsFile {
  viewsVersion: 1
  home?: string
  screens: Screen[]
}

// --- the app's own declarations (operations.json) --------------------------------

/** A parameter's type: the protocol's closed set. */
export type ParamType =
  | 'string'
  | 'number'
  | 'boolean'
  | 'datetime'
  | 'enum'
  | 'ref'
  | 'list<enum>'
  | 'list<ref>'
  | 'json'
  | 'binary'

export interface OpParam {
  type: ParamType | string
  description?: string
  required?: boolean
  /** The choices of an enum or list<enum>. */
  values?: string[]
  /** The entity a ref points at. */
  entity?: string
  max?: number
  format?: string
}

export interface Operation {
  name: string
  description?: string
  destructive?: boolean
  readOnly?: boolean
  idempotent?: boolean
  /** The manifest module it belongs to. */
  module?: string
  /** The entity it acts on, when it acts on one. */
  entity?: string
  /** Framework plumbing, never offered to a person. */
  system?: boolean
  params?: Record<string, OpParam>
}

// --- rendered output ------------------------------------------------------------

export type Tone = 'plain' | 'muted' | 'bold' | 'accent' | 'error' | 'success' | 'selected' | 'heading'

export interface Segment {
  text: string
  tone?: Tone
}

export type Line = Segment[]
