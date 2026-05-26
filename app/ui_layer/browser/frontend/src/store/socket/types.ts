// Wire-level shape. All backend messages on this socket follow {type, data}.
export interface SocketEnvelope {
  type: string
  data?: unknown
}

export type RawMessageHandler = (msg: SocketEnvelope) => void
export type TypedMessageHandler = (data: unknown) => void
export type LifecycleHandler = () => void

export interface SocketClientOptions {
  url: string
  maxReconnectAttempts?: number
  initialBackoffMs?: number
  maxBackoffMs?: number
}
