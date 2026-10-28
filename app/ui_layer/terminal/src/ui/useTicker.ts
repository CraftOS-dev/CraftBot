import { useEffect, useState } from 'react'

/** Re-render every `ms` while `active` (spinners, elapsed timers). Returns the tick count. */
export function useTicker(ms: number, active = true): number {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setTick(t => t + 1), ms)
    return () => clearInterval(timer)
  }, [ms, active])
  return tick
}
