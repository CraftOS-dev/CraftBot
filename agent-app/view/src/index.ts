/**
 * Agent App view engine: declared or generated screens over an app's
 * operations, laid out as text. Shared by the CraftBot terminal edition and
 * the `agent-app view` command.
 */
export type * from './types.ts'
export { get, bindParams } from './pointer.ts'
export { formatValue, humanize, looksLikeDate } from './format.ts'
export { cellWidth, fit, pad } from './width.ts'
export {
  HOME_OPS,
  RESERVED_KEYS,
  areaOf,
  assignKeys,
  generateViews,
  isReadOp,
  opLabel,
  requiredParams,
  verbOf,
} from './generate.ts'
export { fitColumns, inferColumns, renderBlock, toText, wrapText, type BlockOutput, type RenderOptions, type ViewMarks } from './render.ts'
export { validateViews, type ViewsProblem } from './validate.ts'
