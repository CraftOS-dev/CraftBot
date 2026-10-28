/**
 * Selection and scrolling for keyboard lists: j/k or arrows move, g/G jump
 * to the ends, PgUp/PgDn move a page. The window keeps the selection in view.
 */
import type { Key } from 'ink'

export interface ListState {
  index: number
  top: number
}

export const LIST_START: ListState = { index: 0, top: 0 }

export function clampList(state: ListState, count: number, height: number): ListState {
  if (count <= 0) return LIST_START
  const index = Math.min(Math.max(0, state.index), count - 1)
  let top = Math.min(state.top, index)
  if (index >= top + height) top = index - height + 1
  top = Math.max(0, Math.min(top, Math.max(0, count - height)))
  return { index, top }
}

/** Apply a navigation key; null when the key is not a list key. */
export function listKey(state: ListState, input: string, key: Key, count: number, height: number): ListState | null {
  let index = state.index
  if (key.upArrow || input === 'k') index -= 1
  else if (key.downArrow || input === 'j') index += 1
  else if (key.pageUp) index -= height
  else if (key.pageDown) index += height
  else if (key.home || input === 'g') index = 0
  else if (key.end || input === 'G') index = count - 1
  else return null
  return clampList({ ...state, index }, count, height)
}
