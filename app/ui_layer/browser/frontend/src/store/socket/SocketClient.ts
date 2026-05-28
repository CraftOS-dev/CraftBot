import type {
  SocketEnvelope,
  RawMessageHandler,
  TypedMessageHandler,
  LifecycleHandler,
  SocketClientOptions,
} from './types'

// Transport-only wrapper around the browser WebSocket.
//
// Responsibilities:
//   - Manage one connection with exponential-backoff reconnect.
//   - Buffer outbound payloads while the socket isn't OPEN; drain on reconnect.
//   - Multiplex inbound messages to subscribers (raw + per-type).
//   - Emit open/close lifecycle events.
//
// Non-responsibilities: it doesn't know about specific message types,
// redux, react, or business logic. Consumers translate the envelope into
// their own state shape.
export class SocketClient {
  private readonly url: string
  private readonly maxReconnectAttempts: number
  private readonly initialBackoffMs: number
  private readonly maxBackoffMs: number

  private ws: WebSocket | null = null
  private connecting = false
  private connectedFlag = false
  private giveUp = false
  private reconnectAttempt = 0
  private reconnectTimer: number | null = null
  private outbox: string[] = []

  private rawHandlers = new Set<RawMessageHandler>()
  private typedHandlers = new Map<string, Set<TypedMessageHandler>>()
  private openHandlers = new Set<LifecycleHandler>()
  private closeHandlers = new Set<LifecycleHandler>()

  constructor(opts: SocketClientOptions) {
    this.url = opts.url
    this.maxReconnectAttempts = opts.maxReconnectAttempts ?? 10
    this.initialBackoffMs = opts.initialBackoffMs ?? 500
    this.maxBackoffMs = opts.maxBackoffMs ?? 30000
  }

  get isConnected(): boolean {
    return this.connectedFlag
  }

  get reconnectAttempts(): number {
    return this.reconnectAttempt
  }

  connect(): void {
    if (this.connecting || this.ws?.readyState === WebSocket.OPEN) return
    if (this.giveUp) return
    this.connecting = true

    if (this.ws) {
      try { this.ws.close() } catch { /* already closed */ }
      this.ws = null
    }

    const attemptId = newClientId()
    const url = `${this.url}${this.url.includes('?') ? '&' : '?'}attempt=${attemptId}`

    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch (err) {
      console.error('[SocketClient] failed to construct WebSocket:', err)
      this.connecting = false
      this.scheduleReconnect()
      return
    }
    this.ws = ws

    ws.onopen = () => {
      console.log('[SocketClient] connected')
      this.connecting = false
      this.connectedFlag = true
      this.reconnectAttempt = 0

      // Drain outbox first so consumer-side on-open sends happen in order.
      if (this.outbox.length > 0) {
        const pending = this.outbox
        this.outbox = []
        for (const payload of pending) this.rawSend(payload)
      }

      this.openHandlers.forEach(h => safeCall(h))
    }

    ws.onmessage = (event) => {
      let msg: SocketEnvelope
      try {
        msg = JSON.parse(event.data)
      } catch (err) {
        console.error('[SocketClient] parse failed:', err, 'raw:', event.data)
        return
      }
      this.rawHandlers.forEach(h => safeCall(() => h(msg)))
      const typed = this.typedHandlers.get(msg.type)
      if (typed) typed.forEach(h => safeCall(() => h(msg.data)))
    }

    ws.onclose = (event) => {
      console.log(`[SocketClient] disconnected code=${event.code} clean=${event.wasClean}`)
      this.connecting = false
      this.connectedFlag = false
      this.closeHandlers.forEach(h => safeCall(h))
      this.scheduleReconnect()
    }

    ws.onerror = (err) => {
      // Browser error events are opaque; onclose fires after with the real
      // code/reason, so we just log and let onclose drive reconnect.
      console.error('[SocketClient] error:', err)
    }
  }

  // Public: send a message. Queues if the socket isn't OPEN.
  send(type: string, data: Record<string, unknown> = {}): void {
    this.sendRaw({ type, ...data })
  }

  // Public: send a pre-shaped envelope. Used by consumers (like the main
  // context) that need to send `{type, ...payload}` with non-data keys.
  sendRaw(envelope: Record<string, unknown>): void {
    const payload = JSON.stringify(envelope)
    if (this.ws?.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(payload)
        return
      } catch (err) {
        console.warn('[SocketClient] send threw, queuing payload:', err)
      }
    }
    this.outbox.push(payload)
  }

  // Internal: send without queueing (used by drainOutbox).
  private rawSend(payload: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      try { this.ws.send(payload); return } catch { /* fall through to requeue */ }
    }
    this.outbox.push(payload)
  }

  // Migration shim: legacy callers pass a pre-serialized JSON string. Delete
  // once all call sites are converted to sendRaw(envelope) / send(type, data).
  sendString(payload: string): void {
    this.rawSend(payload)
  }

  // Subscribe to every inbound message. Returns an unsubscribe fn.
  onAnyMessage(handler: RawMessageHandler): () => void {
    this.rawHandlers.add(handler)
    return () => { this.rawHandlers.delete(handler) }
  }

  // Subscribe to a specific message type. Handler receives `msg.data`.
  onMessage(type: string, handler: TypedMessageHandler): () => void {
    let set = this.typedHandlers.get(type)
    if (!set) {
      set = new Set()
      this.typedHandlers.set(type, set)
    }
    set.add(handler)
    return () => {
      const s = this.typedHandlers.get(type)
      if (!s) return
      s.delete(handler)
      if (s.size === 0) this.typedHandlers.delete(type)
    }
  }

  onOpen(handler: LifecycleHandler): () => void {
    this.openHandlers.add(handler)
    return () => { this.openHandlers.delete(handler) }
  }

  onClose(handler: LifecycleHandler): () => void {
    this.closeHandlers.add(handler)
    return () => { this.closeHandlers.delete(handler) }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempt >= this.maxReconnectAttempts) {
      this.giveUp = true
      console.error(`[SocketClient] giving up after ${this.maxReconnectAttempts} attempts`)
      return
    }
    const attempt = this.reconnectAttempt
    const delay = attempt === 0
      ? this.initialBackoffMs
      : Math.min(this.initialBackoffMs * Math.pow(1.5, attempt - 1) * 2, this.maxBackoffMs)
    this.reconnectAttempt += 1
    if (this.reconnectTimer != null) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = window.setTimeout(() => this.connect(), delay)
  }
}

const newClientId = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `cid-${Date.now()}-${Math.random().toString(36).slice(2)}`

function safeCall(fn: () => void): void {
  try { fn() } catch (err) { console.error('[SocketClient] handler threw:', err) }
}
