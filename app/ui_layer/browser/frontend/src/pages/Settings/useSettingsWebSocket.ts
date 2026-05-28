import { useState, useEffect, useCallback, useRef } from 'react'
import { getSocketClient } from '../../store/socket/socketInstance'

// Compatibility shim over the shared SocketClient. Preserves the original
// (send, onMessage, isConnected) API so the settings tabs don't have to
// migrate yet, but routes all traffic through the unified connection.
//
// Once a given settings tab moves to redux selectors (phase 6), it stops
// using this hook and the entire file can be deleted.
export function useSettingsWebSocket() {
  const client = getSocketClient()
  const [isConnected, setIsConnected] = useState(client.isConnected)
  const unsubscribesRef = useRef<Array<() => void>>([])

  useEffect(() => {
    const unsubOpen = client.onOpen(() => setIsConnected(true))
    const unsubClose = client.onClose(() => setIsConnected(false))
    return () => {
      unsubOpen()
      unsubClose()
      // Clean up any per-type subscriptions registered via onMessage().
      unsubscribesRef.current.forEach(fn => fn())
      unsubscribesRef.current = []
    }
  }, [client])

  const send = useCallback((type: string, data: Record<string, unknown> = {}) => {
    client.send(type, data)
  }, [client])

  const onMessage = useCallback((type: string, handler: (data: unknown) => void) => {
    const unsub = client.onMessage(type, handler)
    unsubscribesRef.current.push(unsub)
    return () => {
      unsub()
      unsubscribesRef.current = unsubscribesRef.current.filter(fn => fn !== unsub)
    }
  }, [client])

  return { send, onMessage, isConnected }
}
