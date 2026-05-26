import type { RootState } from '../index'
import { messagesAdapter } from '../slices/messagesSlice'

const adapterSelectors = messagesAdapter.getSelectors<RootState>((state) => state.messages)

// All messages in timestamp order (the adapter's sortComparer keeps this in sync).
export const selectAllMessages = adapterSelectors.selectAll
export const selectMessageById = adapterSelectors.selectById
export const selectMessageIds = adapterSelectors.selectIds

export const selectHasMoreMessages = (state: RootState): boolean =>
  state.messages.hasMore

export const selectLoadingOlderMessages = (state: RootState): boolean =>
  state.messages.loadingOlder

export const selectOldestMessageTimestamp = (state: RootState): number | undefined => {
  const first = state.messages.ids[0]
  return first !== undefined ? state.messages.entities[first]?.timestamp : undefined
}
