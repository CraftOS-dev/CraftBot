import { useMemo } from 'react'
import type { AgentState, AgentStatus, ChatMessage } from '../types'
import type { ActivityOverview } from '../store/selectors/activity'
import { normalizeActionName } from '../components/activity/actionNames'
import i18n from '../i18n/config'
import { formatList } from '../i18n/format'

interface DerivedStatusOptions {
  /** Cross-session activity summary (selectActivityOverview): the in-progress
   *  items plus the newest activity time — all the derivation reads. */
  activity: ActivityOverview
  /** The newest message across sessions (selectLatestMessage). */
  lastMessage: ChatMessage | undefined
  connected: boolean
}

/**
 * Pure derivation of agent status from activity items and messages.
 *
 * This is more robust than relying on separate status_update messages because:
 * 1. Single source of truth - the activity and message state contain all state
 * 2. Always in sync - computed status can never be stale
 * 3. Shows meaningful info - displays actual action names
 */
function deriveAgentStatus(
  activity: ActivityOverview,
  lastMessage: ChatMessage | undefined,
  connected: boolean,
): AgentStatus {
  // If not connected, show error state
  if (!connected) {
    return {
      state: 'error' as AgentState,
      message: i18n.t('common:status.disconnected'),
      loading: false,
    }
  }

  // Waiting/running items are always in `live`, so scanning it is the same
  // as scanning every item.
  const { live } = activity

  // Priority 1: an item is waiting on the user's reply.
  const waiting = live.find(a => a.status === 'waiting')
  if (waiting) {
    return {
      state: 'waiting' as AgentState,
      message: i18n.t('nav:agentStatus.waiting'),
      loading: false,
    }
  }

  // Priority 2: something is running right now. send_message is excluded
  // from the named-tool derivation (it isn't rendered in the timeline
  // either — the chat bubble is its visible form); if it's the only thing
  // running, the reasoning fallback below reports "thinking" instead.
  const running = live.filter(a =>
    a.itemType === 'action' &&
    a.status === 'running' &&
    normalizeActionName(a.name) !== 'send_message',
  )
  if (running.length > 0) {
    const names = running.map(a => a.name)
    const message = i18n.t('nav:agentStatus.running', {
      count: names.length,
      names: formatList(names),
    })
    return {
      state: 'working' as AgentState,
      message,
      loading: true,
    }
  }
  if (live.some(a => a.status === 'running')) {
    // A reasoning block is streaming — the agent is thinking.
    return {
      state: 'thinking' as AgentState,
      message: i18n.t('nav:agentStatus.thinking'),
      loading: true,
    }
  }

  // Priority 3: the last message is from the user and the agent hasn't
  // visibly acted since — it's still preparing a response. This covers
  // the gap right after a send, before the first action item arrives.
  if (lastMessage && lastMessage.style === 'user') {
    // ChatMessage.timestamp is epoch seconds; ActionItem times are ms.
    // Some item was created or completed since ⇔ the newest such time is.
    const agentActedSince = activity.latestAt >= lastMessage.timestamp * 1000
    if (!agentActedSince) {
      return {
        state: 'working' as AgentState,
        message: i18n.t('nav:agentStatus.working'),
        loading: true,
      }
    }
  }

  // Default: Idle state
  return {
    state: 'idle' as AgentState,
    message: i18n.t('nav:agentStatus.idle'),
    loading: false,
  }
}

/** Full status object — used by global consumers (dashboard header, mascot). */
export function useDerivedAgentStatus(
  options: DerivedStatusOptions
): AgentStatus {
  const { activity, lastMessage, connected } = options

  return useMemo(
    () => deriveAgentStatus(activity, lastMessage, connected),
    [activity, lastMessage, connected],
  )
}

// NOTE: the chat's typing indicator is NOT derived here — it is run-scoped
// and driven by the backend's session_busy events
// (agentSlice.runStateBySession), so it stays steady across turn boundaries.
