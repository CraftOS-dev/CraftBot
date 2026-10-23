import { register } from './messageRegistry'
import { getSocketClient } from './socketInstance'
import { setUiState } from '../slices/uiSlice'
import { selectUiState } from '../selectors/ui'
import { UI_STATE } from '../uiState/catalog'

// Read receipts are durable on the backend. The local preference remains a
// cache and a migration source for messages read before this feature existed.
register('init', (data, dispatch, getState) => {
  const durable = (data as { lastSeenMessageIds?: Record<string, string> } | undefined)?.lastSeenMessageIds
  if (!durable) return // Older backends still use browser-only read status.
  const local = selectUiState(getState(), UI_STATE.chat.lastSeenMessageIds)
  dispatch(setUiState(UI_STATE.chat.lastSeenMessageIds, { ...local, ...durable }))
  // Import legacy/local receipts; the server validates ownership and only
  // advances a marker, so a stale tab can never overwrite a newer receipt.
  for (const [sessionId, messageId] of Object.entries(local)) {
    if (messageId && messageId !== durable[sessionId]) {
      getSocketClient().sendString(JSON.stringify({ type: 'session_seen', sessionId, messageId }))
    }
  }
})

register('session_seen', (data, dispatch, getState) => {
  const receipt = data as { sessionId?: string; messageId?: string } | undefined
  if (!receipt?.sessionId || !receipt.messageId) return
  const seen = selectUiState(getState(), UI_STATE.chat.lastSeenMessageIds)
  if (seen[receipt.sessionId] !== receipt.messageId) {
    dispatch(setUiState(UI_STATE.chat.lastSeenMessageIds, {
      ...seen, [receipt.sessionId]: receipt.messageId,
    }))
  }
})
