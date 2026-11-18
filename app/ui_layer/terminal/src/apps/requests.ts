/**
 * An app's requests to your AI agent, and the person's consent to them, as
 * the browser shows them while an app is open (FrameworkRequestFeedback):
 * `task_status` read every 5 seconds while the app runs, and `consent` to
 * allow or not. A review opens on its own when requests are waiting and this
 * set was not decided yet; closing it without a choice counts as "do not
 * allow", unless that choice cannot be saved (then it just closes).
 */
import { useEffect, useRef, useState } from 'react'
import { useAppSelector } from '../state/hooks'
import { errorText, frameworkRequest } from './framework'

export interface RequestStatus {
  permissionRequired: boolean
  needsReview: boolean
  changed?: boolean
  revision?: string
  reviewId?: string
  requests?: string[]
  error?: string
  retryNeeded?: boolean
}

export interface AppRequests {
  status: RequestStatus | null
  /** The review is showing. */
  open: boolean
  busy: boolean
  error: string
  /** The last choice saved, for one line of feedback. */
  saved: 'allowed' | 'declined' | null
  choose(allow: boolean): void
  close(): void
  review(): void
}

export function useAppRequests(path: string | undefined, appId: string | undefined, enabled: boolean): AppRequests {
  const connected = useAppSelector(s => s.connection.connected)
  const [status, setStatus] = useState<RequestStatus | null>(null)
  const [reviewing, setReviewing] = useState(false)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState<'allowed' | 'declined' | null>(null)
  const saving = useRef(false)
  const version = useRef(0)
  const lastChoice = useRef<boolean | null>(null)
  const on = enabled && connected && !!path && !!appId

  useEffect(() => {
    if (!on) return
    let active = true
    let timer: NodeJS.Timeout
    const poll = async () => {
      if (!saving.current) {
        const started = version.current
        try {
          const value = await frameworkRequest<RequestStatus>({ operation: 'task_status', path, appId }, 20_000)
          if (active && !saving.current && started === version.current) {
            setStatus(value)
            if (!value.permissionRequired && !value.error) setReviewing(false)
          }
        } catch {
          // Keep the last known state; a background read never replaces it.
        }
      }
      if (active) timer = setTimeout(poll, 5000)
    }
    timer = setTimeout(poll, 0)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [on, path, appId])

  const choose = (allow: boolean) => {
    if (!on || saving.current || !status) return
    saving.current = true
    version.current++
    lastChoice.current = allow
    setBusy(true)
    setError('')
    frameworkRequest({ operation: 'consent', path, appId, allow, revision: status.revision, reviewId: status.reviewId })
      .then(() => {
        setStatus(value => (value ? { ...value, needsReview: false, permissionRequired: !allow, changed: false, error: undefined } : value))
        setReviewing(false)
        setSaved(allow ? 'allowed' : 'declined')
      })
      .catch(err => setError(errorText(err)))
      .finally(() => {
        saving.current = false
        setBusy(false)
      })
  }

  const close = () => {
    if (!connected || (error && lastChoice.current === false)) {
      setReviewing(false)
      setDismissed(status?.reviewId ?? null)
    } else choose(false)
  }

  const waiting = !!status?.permissionRequired && status.needsReview && status.reviewId !== dismissed
  return {
    status,
    open: (on || !connected) && !!status && (reviewing || waiting),
    busy,
    error,
    saved,
    choose,
    close,
    review: () => {
      setDismissed(null)
      setReviewing(true)
    },
  }
}
