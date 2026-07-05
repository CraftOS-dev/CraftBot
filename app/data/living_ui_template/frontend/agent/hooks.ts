/**
 * Agent-awareness React hooks
 *
 * These hooks connect React components to the agent observation layer
 * (UICapture → POST /api/ui-snapshot). See STANDARDS.md §5 for usage rules.
 */

import { useEffect, useRef } from 'react'
import { uiCapture } from '../services/UICapture'

/**
 * Register a component's state for agent visibility.
 *
 * The state is included in the componentState section of UI snapshots
 * the agent reads via GET /api/ui-snapshot. Keep payloads small (<10KB)
 * and meaningful — summarize, don't dump raw data.
 *
 * @example
 * useAgentAware('TodoList', {
 *   itemCount: items.length,
 *   completedCount: items.filter(i => i.done).length,
 * })
 */
export function useAgentAware(name: string, state: Record<string, unknown>): void {
  // Serialize so the effect only re-fires on real state changes,
  // not on every render with a fresh object literal.
  const serialized = JSON.stringify(state)

  useEffect(() => {
    uiCapture.updateComponent(name, JSON.parse(serialized) as Record<string, unknown>)
  }, [name, serialized])

  useEffect(() => {
    return () => uiCapture.unregisterComponent(name)
  }, [name])
}

export interface AgentCommand {
  type: string
  payload?: unknown
}

/**
 * Handle commands pushed to the app from the CraftBot host frame.
 *
 * Commands arrive as postMessage events of shape
 * `{ type: 'craftbot-agent-command', command: { type, payload } }`.
 * If no host is present (app opened standalone), no commands ever
 * arrive and the app degrades gracefully.
 */
export function useAgentCommand(handler: (command: AgentCommand) => void): void {
  const handlerRef = useRef(handler)
  handlerRef.current = handler

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; command?: AgentCommand } | null
      if (data && typeof data === 'object' && data.type === 'craftbot-agent-command' && data.command) {
        handlerRef.current(data.command)
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])
}
