/**
 * Backend resource names; mirrors `Resource` in app/ui_layer/events/resource_changes.py.
 * `static` is frontend-only: the backend never reports it changed, so its
 * views refresh only after a reconnect.
 */
export type ResourceName =
  | 'agent_apps'
  | 'sessions'
  | 'workspace_files'
  | 'skills'
  | 'mcp_servers'
  | 'integrations'
  | 'proactive'
  | 'scheduler'
  | 'memory'
  | 'agent_files'
  | 'general_settings'
  | 'model_settings'
  | 'static'

type Send = (payload: object) => void

/** One cached view of server data and how to refresh it. */
export interface ResourceDescriptor {
  /** Unique name of this view of the data. */
  key: string
  /** Backend resource whose changes make this view stale. */
  resource: ResourceName
  /** Ask the backend for fresh data. Replies are applied by the slices as usual. */
  request(send: Send): void
  /**
   * 'visible' (default): refetch on change only while a component uses it,
   * otherwise remember it's stale and refetch on next use.
   * 'always': refetch on every change (app-wide data such as the sidebar).
   */
  liveness?: 'visible' | 'always'
  /** The backend pushes this data on every connect, so reconnects needn't ask. */
  pushedOnConnect?: boolean
  /**
   * Refetch every this many ms while a view uses it and the page is visible.
   * Only for state nothing announces (listener health, subscription status).
   */
  pollWhileVisible?: number
}

interface Transport {
  readonly isConnected: boolean
  sendString(payload: string): void
}

/**
 * Keeps cached server data fresh (docs/plans/ui-data-freshness-plan.md, §A4.3).
 *
 * Views subscribe to descriptors; `resource_changed` messages and reconnects
 * invalidate them. Used descriptors refetch at once and unused ones are marked
 * stale. The data itself stays in the existing slices.
 */
export class ResourceSync {
  private readonly users = new Map<string, number>()
  private readonly loaded = new Set<string>()
  private readonly stale = new Set<string>()
  private readonly queued = new Set<string>()
  private readonly polls = new Map<string, ReturnType<typeof setInterval>>()

  constructor(
    private readonly transport: Transport,
    private readonly descriptors: readonly ResourceDescriptor[],
  ) {}

  /** A view started using `descriptor`. Returns the matching unsubscribe. */
  subscribe(descriptor: ResourceDescriptor): () => void {
    const users = (this.users.get(descriptor.key) ?? 0) + 1
    this.users.set(descriptor.key, users)
    if (!this.loaded.has(descriptor.key) || this.stale.has(descriptor.key)) this.refetch(descriptor)
    if (users === 1 && descriptor.pollWhileVisible) {
      this.polls.set(descriptor.key, setInterval(() => {
        const visible = typeof document === 'undefined' || document.visibilityState === 'visible'
        if (visible) this.refetch(descriptor)
      }, descriptor.pollWhileVisible))
    }
    return () => {
      const remaining = (this.users.get(descriptor.key) ?? 1) - 1
      if (remaining > 0) {
        this.users.set(descriptor.key, remaining)
        return
      }
      this.users.delete(descriptor.key)
      const poll = this.polls.get(descriptor.key)
      if (poll !== undefined) {
        clearInterval(poll)
        this.polls.delete(descriptor.key)
      }
    }
  }

  /** Ask for `descriptor` again right now (a user-triggered retry). */
  refresh(descriptor: ResourceDescriptor): void {
    this.refetch(descriptor)
  }

  /** The backend reported a change to `resource`. */
  handleChanged(resource: string): void {
    for (const descriptor of this.descriptors) {
      if (descriptor.resource === resource) this.invalidate(descriptor)
    }
  }

  /** The socket opened: anything may have changed while it was closed. */
  handleOpen(): void {
    for (const descriptor of this.descriptors) {
      if (!descriptor.pushedOnConnect) this.invalidate(descriptor)
    }
  }

  private invalidate(descriptor: ResourceDescriptor): void {
    const used = descriptor.liveness === 'always' || this.users.has(descriptor.key)
    if (used) this.refetch(descriptor)
    else if (this.loaded.has(descriptor.key)) this.stale.add(descriptor.key)
  }

  // Coalesces refetches requested in the same tick into one request.
  private refetch(descriptor: ResourceDescriptor): void {
    if (this.queued.has(descriptor.key)) return
    this.queued.add(descriptor.key)
    queueMicrotask(() => {
      this.queued.delete(descriptor.key)
      if (!this.transport.isConnected) {
        // handleOpen retries it once the connection is back.
        this.stale.add(descriptor.key)
        return
      }
      descriptor.request((payload) => this.transport.sendString(JSON.stringify(payload)))
      this.loaded.add(descriptor.key)
      this.stale.delete(descriptor.key)
    })
  }
}
