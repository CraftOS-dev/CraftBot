import type {
  SocketEnvelope,
  OutboundEnvelope,
  RawMessageHandler,
  TypedMessageHandler,
  LifecycleHandler,
  OutboxExpiredHandler,
  ReconnectScheduledHandler,
  LivenessHandler,
  SocketClientOptions,
} from './types'

// Transport-only wrapper around the browser WebSocket.
//
// Responsibilities:
//   - Manage one connection. Reconnect with capped exponential backoff for as
//     long as the page is open (it never gives up: a backend restart or update
//     can take minutes), and immediately when the browser comes back online or
//     the tab becomes visible again.
//   - Buffer outbound payloads while the socket isn't OPEN; drain on reconnect.
//     Buffered payloads expire after `outboxTtlMs`, so an action clicked long
//     ago (e.g. a delete) is never replayed; expiries are reported to
//     subscribers, which tell the user and undo optimistic UI.
//   - Detect a busy backend: while connected, ping a quiet connection and
//     report "busy" when neither a pong nor any other frame arrives in time
//     (the backend's event loop is blocked). Any inbound frame clears it.
//   - Multiplex inbound messages to subscribers (raw + per-type).
//   - Emit open/close/reconnect/liveness lifecycle events.
//
// Non-responsibilities: it doesn't know about specific message types,
// redux, react, or business logic. Consumers translate the envelope into
// their own state shape.

interface QueuedPayload {
  payload: string
  queuedAt: number
}

// How often queued payloads are checked for expiry while any are waiting.
const OUTBOX_SWEEP_MS = 5000
// How often liveness is evaluated while connected.
const LIVENESS_TICK_MS = 1000

export class SocketClient {
  private readonly url: string
  private readonly initialBackoffMs: number
  private readonly maxBackoffMs: number
  private readonly outboxTtlMs: number
  private readonly livenessIntervalMs: number
  private readonly livenessTimeoutMs: number
  private readonly getProtocols?: () => Promise<string[]>

  private ws: WebSocket | null = null
  private connecting = false
  private connectedFlag = false
  private reconnectAttempt = 0
  private reconnectTimer: number | null = null
  private outbox: QueuedPayload[] = []
  private outboxSweepTimer: number | null = null

  private livenessTimer: number | null = null
  private lastInboundAt = 0
  private lastPingAt = 0
  private pingSentAt: number | null = null
  private backendBusy = false

  private rawHandlers = new Set<RawMessageHandler>()
  private typedHandlers = new Map<string, Set<TypedMessageHandler>>()
  private openHandlers = new Set<LifecycleHandler>()
  private closeHandlers = new Set<LifecycleHandler>()
  private reconnectHandlers = new Set<ReconnectScheduledHandler>()
  private outboxExpiredHandlers = new Set<OutboxExpiredHandler>()
  private livenessHandlers = new Set<LivenessHandler>()

  constructor(opts: SocketClientOptions) {
    this.url = opts.url
    this.initialBackoffMs = opts.initialBackoffMs ?? 500
    this.maxBackoffMs = opts.maxBackoffMs ?? 30000
    this.outboxTtlMs = opts.outboxTtlMs ?? 60000
    this.livenessIntervalMs = opts.livenessIntervalMs ?? 5000
    this.livenessTimeoutMs = opts.livenessTimeoutMs ?? 3000
    this.getProtocols = opts.getProtocols

    if (typeof window !== 'undefined') {
      window.addEventListener('online', () => this.reconnectNow())
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') this.reconnectNow()
      })
    }
  }

  get isConnected(): boolean {
    return this.connectedFlag
  }

  get reconnectAttempts(): number {
    return this.reconnectAttempt
  }

  get isBackendBusy(): boolean {
    return this.backendBusy
  }

  connect(): void {
    if (this.connecting || this.ws?.readyState === WebSocket.OPEN) return
    this.connecting = true

    if (this.ws) {
      try { this.ws.close() } catch { /* already closed */ }
      this.ws = null
    }

    if (!this.getProtocols) {
      this.open([])
      return
    }
    this.getProtocols().then(
      protocols => this.open(protocols),
      err => {
        // Backend down or restarting: retry with the usual backoff.
        console.warn('[SocketClient] could not get session token:', err)
        this.connecting = false
        this.scheduleReconnect()
      },
    )
  }

  private open(protocols: string[]): void {
    const attemptId = newClientId()
    const url = `${this.url}${this.url.includes('?') ? '&' : '?'}attempt=${attemptId}`

    let ws: WebSocket
    try {
      ws = new WebSocket(url, protocols)
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
      this.startLiveness()

      // Drain outbox first so consumer-side on-open sends happen in order.
      // Anything that waited past its TTL is dropped (and reported) instead.
      this.expireStaleOutbox()
      if (this.outbox.length > 0) {
        const pending = this.outbox
        this.outbox = []
        for (const queued of pending) this.rawSend(queued.payload, queued.queuedAt)
      }

      this.openHandlers.forEach(h => safeCall(h))
    }

    ws.onmessage = (event) => {
      this.lastInboundAt = Date.now()
      this.pingSentAt = null
      if (this.backendBusy) this.setBackendBusy(false)

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
      this.stopLiveness()
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
    this.enqueue(payload)
  }

  // Internal: send or requeue, keeping the payload's original queue time.
  private rawSend(payload: string, queuedAt = Date.now()): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      try { this.ws.send(payload); return } catch { /* fall through to requeue */ }
    }
    this.enqueue(payload, queuedAt)
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

  onReconnectScheduled(handler: ReconnectScheduledHandler): () => void {
    this.reconnectHandlers.add(handler)
    return () => { this.reconnectHandlers.delete(handler) }
  }

  onOutboxExpired(handler: OutboxExpiredHandler): () => void {
    this.outboxExpiredHandlers.add(handler)
    return () => { this.outboxExpiredHandlers.delete(handler) }
  }

  onLivenessChange(handler: LivenessHandler): () => void {
    this.livenessHandlers.add(handler)
    return () => { this.livenessHandlers.delete(handler) }
  }

  // Skip the backoff wait and try now: the browser is back online, or the
  // tab became visible (background tabs get their timers throttled).
  private reconnectNow(): void {
    if (this.connectedFlag || this.connecting) return
    if (this.reconnectTimer != null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.reconnectAttempt = 0
    this.connect()
  }

  private scheduleReconnect(): void {
    const attempt = this.reconnectAttempt
    const delay = attempt === 0
      ? this.initialBackoffMs
      : Math.min(this.initialBackoffMs * Math.pow(1.5, attempt - 1) * 2, this.maxBackoffMs)
    this.reconnectAttempt += 1
    if (this.reconnectTimer != null) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
    const scheduled = this.reconnectAttempt
    this.reconnectHandlers.forEach(h => safeCall(() => h(scheduled, delay)))
  }

  private enqueue(payload: string, queuedAt = Date.now()): void {
    this.outbox.push({ payload, queuedAt })
    if (this.outboxSweepTimer == null && typeof window !== 'undefined') {
      this.outboxSweepTimer = window.setInterval(() => this.expireStaleOutbox(), OUTBOX_SWEEP_MS)
    }
  }

  private expireStaleOutbox(): void {
    const cutoff = Date.now() - this.outboxTtlMs
    const expired = this.outbox.filter(queued => queued.queuedAt < cutoff)
    if (expired.length > 0) {
      this.outbox = this.outbox.filter(queued => queued.queuedAt >= cutoff)
      const envelopes = expired.map(queued => parseOutbound(queued.payload))
      this.outboxExpiredHandlers.forEach(h => safeCall(() => h(envelopes)))
    }
    if (this.outbox.length === 0 && this.outboxSweepTimer != null) {
      clearInterval(this.outboxSweepTimer)
      this.outboxSweepTimer = null
    }
  }

  private startLiveness(): void {
    this.stopLiveness()
    if (typeof window === 'undefined') return
    const now = Date.now()
    this.lastInboundAt = now
    this.lastPingAt = now
    this.livenessTimer = window.setInterval(() => this.checkLiveness(), LIVENESS_TICK_MS)
  }

  private stopLiveness(): void {
    if (this.livenessTimer != null) {
      clearInterval(this.livenessTimer)
      this.livenessTimer = null
    }
    this.pingSentAt = null
    if (this.backendBusy) this.setBackendBusy(false)
  }

  private checkLiveness(): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return
    const now = Date.now()
    if (this.pingSentAt === null) {
      // Only ping a quiet connection; traffic already proves liveness.
      const quietFor = now - Math.max(this.lastInboundAt, this.lastPingAt)
      if (quietFor >= this.livenessIntervalMs) {
        this.pingSentAt = now
        this.lastPingAt = now
        try { this.ws.send(JSON.stringify({ type: 'ping' })) } catch { /* close will follow */ }
      }
      return
    }
    if (!this.backendBusy && now - this.pingSentAt > this.livenessTimeoutMs) {
      this.setBackendBusy(true)
    }
  }

  private setBackendBusy(busy: boolean): void {
    this.backendBusy = busy
    this.livenessHandlers.forEach(h => safeCall(() => h(busy)))
  }
}

const newClientId = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `cid-${Date.now()}-${Math.random().toString(36).slice(2)}`

function parseOutbound(payload: string): OutboundEnvelope {
  try {
    const parsed: unknown = JSON.parse(payload)
    if (parsed && typeof parsed === 'object') return parsed as OutboundEnvelope
  } catch { /* not JSON — report it without a type */ }
  return {}
}

function safeCall(fn: () => void): void {
  try { fn() } catch (err) { console.error('[SocketClient] handler threw:', err) }
}
