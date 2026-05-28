import { SocketClient } from './SocketClient'
import { getWsUrl } from '../../utils/connection'

// Module-level singleton. Created lazily so tests / SSR-ish environments
// don't pay for a WebSocket at import time. The middleware calls connect()
// during store bootstrap; legacy consumers (WebSocketContext,
// useSettingsWebSocket) only subscribe.
let instance: SocketClient | null = null

export function getSocketClient(): SocketClient {
  if (!instance) {
    instance = new SocketClient({ url: getWsUrl() })
  }
  return instance
}
