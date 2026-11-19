/**
 * The app screen's view engine: screens generated from an app's declared
 * operations, laid out as text.
 */
export type * from './types'
export { get, bindParams } from './pointer'
export { formatValue, humanize, looksLikeDate } from './format'
export { cellWidth, fit, pad } from './width'
export {
  HOME_OPS,
  RESERVED_KEYS,
  areaOf,
  assignKeys,
  generateViews,
  isReadOp,
  opLabel,
  recordActions,
  requiredParams,
  verbOf,
} from './generate'
export { fitColumns, inferColumns, renderBlock, toText, wrapText, type BlockOutput, type RenderOptions, type ViewMarks } from './render'
