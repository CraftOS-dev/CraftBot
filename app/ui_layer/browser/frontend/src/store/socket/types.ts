// Wire-level shape. All backend messages on this socket follow {type, data}.
export interface SocketEnvelope {
  type: string
  data?: unknown
}

/** Outbound payload shape: `{type, ...fields}`. */
export type OutboundEnvelope = { type?: string } & Record<string, unknown>

export type RawMessageHandler = (msg: SocketEnvelope) => void
export type TypedMessageHandler = (data: unknown) => void
export type LifecycleHandler = () => void
/** Queued payloads that waited longer than `outboxTtlMs` and were dropped. */
export type OutboxExpiredHandler = (expired: OutboundEnvelope[]) => void
/** A reconnect attempt was scheduled (attempt is 1-based). */
export type ReconnectScheduledHandler = (attempt: number, delayMs: number) => void
/** Connected, but the backend stopped (true) or resumed (false) answering pings. */
export type LivenessHandler = (busy: boolean) => void

export interface SocketClientOptions {
  url: string
  initialBackoffMs?: number
  maxBackoffMs?: number
  /** How long a queued outbound payload may wait for a connection. */
  outboxTtlMs?: number
  /** How often to ping an otherwise quiet connection. */
  livenessIntervalMs?: number
  /** How long a ping may go unanswered before the backend counts as busy. */
  livenessTimeoutMs?: number
}
