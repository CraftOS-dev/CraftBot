import { useMemo } from 'react'
import type { ActionItem, AgentState, AgentStatus, ChatMessage } from '../types'

interface DerivedStatusOptions {
  actions: ActionItem[]
  messages: ChatMessage[]
  connected: boolean
}

/**
 * Derives agent status from the actions array and messages.
 *
 * This is more robust than relying on separate status_update messages because:
 * 1. Single source of truth - actions and messages arrays contain all state
 * 2. Always in sync - computed status can never be stale
 * 3. Shows meaningful info - displays actual task/action names
 */
export function useDerivedAgentStatus(
  options: DerivedStatusOptions
): AgentStatus {
  const { actions, messages, connected } = options

  return useMemo(() => {
    // If not connected, show error state
    if (!connected) {
      return {
        state: 'error' as AgentState,
        message: 'Disconnected',
        loading: false,
      }
    }

    // Find running tasks (top-level items)
    const runningTasks = actions.filter(
      a => a.itemType === 'task' && a.status === 'running'
    )

    // Find waiting tasks
    const waitingTasks = actions.filter(
      a => a.itemType === 'task' && a.status === 'waiting'
    )

    // Priority 1: If any task is waiting for user response
    if (waitingTasks.length > 0) {
      const taskName = waitingTasks[0].name
      return {
        state: 'waiting' as AgentState,
        message: `Agent is waiting response on ${taskName}`,
        loading: false,
      }
    }

    // Priority 2: If there are running tasks, list them
    if (runningTasks.length > 0) {
      const taskNames = runningTasks.map(t => t.name)
      const message = taskNames.length === 1
        ? `Agent is working on ${taskNames[0]}`
        : `Agent is working on ${taskNames.join(', ')}`
      return {
        state: 'working' as AgentState,
        message,
        loading: true,
      }
    }

    // Priority 3: If the last message is from user, agent is processing it
    // (no running tasks yet means agent is still thinking/preparing).
    //
    // Escape hatch: the agent may finish the work without ever posting a
    // chat reply (e.g. the response is the task itself). If any task or
    // action was started or finished after the user's message — and nothing
    // is running any more (checked above) — the message has been handled,
    // so don't report "working" forever.
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
  }, [actions, messages, connected])
}
