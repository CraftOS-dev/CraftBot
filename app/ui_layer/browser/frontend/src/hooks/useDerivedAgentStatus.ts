import { useMemo } from 'react'
import type { ActionItem, AgentState, AgentStatus, ChatMessage } from '../types'
import { normalizeActionName } from '../components/activity/actionNames'

interface DerivedStatusOptions {
  /** Activity items (actions + reasoning) to derive status from — a single
   *  session's timeline, or the flattened all-sessions list for global
   *  consumers like the dashboard header and the mascot. */
  actions: ActionItem[]
  messages: ChatMessage[]
  connected: boolean
}

/**
 * Pure derivation of agent status from activity items and messages.
 *
 * This is more robust than relying on separate status_update messages because:
 * 1. Single source of truth - the activity and message arrays contain all state
 * 2. Always in sync - computed status can never be stale
 * 3. Shows meaningful info - displays actual action names
 */
function deriveAgentStatus(
  actions: ActionItem[],
  messages: ChatMessage[],
  connected: boolean,
): AgentStatus {
  // If not connected, show error state
  if (!connected) {
    return {
      state: 'error' as AgentState,
      message: 'Disconnected',
      loading: false,
    }
  }

  // Priority 1: an item is waiting on the user's reply.
  const waiting = actions.find(a => a.status === 'waiting')
  if (waiting) {
    return {
      state: 'waiting' as AgentState,
      message: 'Agent is waiting for your reply',
      loading: false,
    }
  }

  // Priority 2: something is running right now. send_message is excluded
  // from the named-tool derivation (it isn't rendered in the timeline
  // either — the chat bubble is its visible form); if it's the only thing
  // running, the reasoning fallback below reports "thinking" instead.
  const running = actions.filter(a =>
    a.itemType === 'action' &&
    a.status === 'running' &&
    normalizeActionName(a.name) !== 'send_message',
  )
  if (running.length > 0) {
    const names = running.map(a => a.name)
    const message = names.length === 1
      ? `Agent is running ${names[0]}`
      : `Agent is running ${names.join(', ')}`
    return {
      state: 'working' as AgentState,
      message,
      loading: true,
    }
  }
  if (actions.some(a => a.status === 'running')) {
    // A reasoning block is streaming — the agent is thinking.
    return {
      state: 'thinking' as AgentState,
      message: 'Agent is thinking',
      loading: true,
    }
  }

  // Priority 3: the last message is from the user and the agent hasn't
  // visibly acted since — it's still preparing a response. This covers
  // the gap right after a send, before the first action item arrives.
  if (messages.length > 0) {
    const lastMessage = messages[messages.length - 1]
    if (lastMessage.style === 'user') {
      // ChatMessage.timestamp is epoch seconds; ActionItem times are ms.
      const lastMessageMs = lastMessage.timestamp * 1000
      const agentActedSince = actions.some(
        a =>
          (a.createdAt ?? 0) >= lastMessageMs ||
          (a.completedAt ?? 0) >= lastMessageMs
      )
      if (!agentActedSince) {
        return {
          state: 'working' as AgentState,
          message: 'Agent is working',
          loading: true,
        }
      }
    }
  }

  // Default: Idle state
  return {
    state: 'idle' as AgentState,
    message: 'Agent is idle',
    loading: false,
  }
}

/** Full status object — used by global consumers (dashboard header). */
export function useDerivedAgentStatus(
  options: DerivedStatusOptions
): AgentStatus {
  const { actions, messages, connected } = options

  return useMemo(
    () => deriveAgentStatus(actions, messages, connected),
    [actions, messages, connected],
  )
}

// NOTE: the chat's typing indicator is NOT derived here — it is run-scoped
// and driven by the backend's session_busy events (agentSlice.busyBySession),
// so it stays steady across turn boundaries.
