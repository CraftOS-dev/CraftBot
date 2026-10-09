import { useLayoutEffect, useRef, type MutableRefObject } from 'react'

/**
 * A ref that always holds the latest committed `value`. For handlers bound
 * once (native listeners, socket subscriptions, timers) that must read the
 * current props without being re-bound on every render.
 */
export function useLatest<T>(value: T): MutableRefObject<T> {
  const ref = useRef(value)
  useLayoutEffect(() => {
    ref.current = value
  })
  return ref
}
