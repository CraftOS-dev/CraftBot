import { useLayoutEffect, useRef, useState } from 'react'
import { acquireIframe, frameUrl, subscribeFrameHost } from './frameHost'
import type { AgentAppProject } from '../../types'

/** Bind a persistent frame to a React surface without moving its DOM node. */
export function useAgentAppFrame(project: AgentAppProject, active: boolean, moving: boolean, blocked: boolean) {
  const placeholder = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'timeout' | 'unavailable'>('loading')
  const [retry, setRetry] = useState(0)
  const [hostVersion, setHostVersion] = useState(0)
  const leaseRef = useRef<ReturnType<typeof acquireIframe>>(null)
  const refresh = useRef<() => void>(() => {})
  useLayoutEffect(() => subscribeFrameHost(() => {
    if (!leaseRef.current) setHostVersion(value => value + 1)
  }), [])
  const view = useRef({ active, moving, blocked, ready: status === 'ready' })
  view.current = { active, moving, blocked, ready: status === 'ready' }

  useLayoutEffect(() => {
    const element = placeholder.current
    if (!active || project.status !== 'running' || !project.url || !element) return
    const base = frameUrl(project.url)
    let lease: ReturnType<typeof acquireIframe>
    try {
      const url = new URL(base)
      if (project.readyAt) url.searchParams.set('v', String(project.readyAt))
      if (retry) url.searchParams.set('viewRetry', String(retry))
      lease = acquireIframe(project.id, url.toString())
    } catch { setStatus('unavailable'); return }
    if (!lease) { setStatus('unavailable'); return }
    leaseRef.current = lease
    lease.frame.title = project.name
    let disposed = false
    let raf = 0
    let transitioning = 0
    const ancestors: HTMLElement[] = []
    for (let node: HTMLElement | null = element; node; node = node.parentElement) ancestors.push(node)
    const update = () => {
      raf = 0
      if (disposed) return
      const rect = element.getBoundingClientRect()
      let visible = view.current.active && view.current.ready && rect.width > 0 && rect.height > 0
      let top = Math.max(0, rect.top), left = Math.max(0, rect.left)
      let right = Math.min(innerWidth, rect.right), bottom = Math.min(innerHeight, rect.bottom)
      for (const parent of ancestors) {
        const style = getComputedStyle(parent)
        if (parent.hidden || parent.inert || parent.getAttribute('aria-hidden') === 'true' || style.visibility === 'hidden' || style.display === 'none') visible = false
        const box = parent.getBoundingClientRect()
        if (/(hidden|clip|auto|scroll)/.test(style.overflowX)) { left = Math.max(left, box.left); right = Math.min(right, box.right) }
        if (/(hidden|clip|auto|scroll)/.test(style.overflowY)) { top = Math.max(top, box.top); bottom = Math.min(bottom, box.bottom) }
      }
      visible = visible && right > left && bottom > top
      lease.frame.style.clipPath = `inset(${Math.max(0, top - rect.top)}px ${Math.max(0, rect.right - right)}px ${Math.max(0, rect.bottom - bottom)}px ${Math.max(0, left - rect.left)}px)`
      lease.update(rect, visible, !view.current.blocked && !view.current.moving)
      if (view.current.moving || transitioning > 0) raf = requestAnimationFrame(update)
    }
    const schedule = () => { if (!raf && !disposed) raf = requestAnimationFrame(update) }
    refresh.current = schedule
    const onTransition = (event: Event) => { if (ancestors.includes(event.target as HTMLElement)) { transitioning++; schedule() } }
    const onTransitionEnd = (event: Event) => { if (ancestors.includes(event.target as HTMLElement)) { transitioning = Math.max(0, transitioning - 1); schedule() } }
    const resize = new ResizeObserver(schedule)
    const attributes = new MutationObserver(schedule)
    ancestors.forEach(node => {
      resize.observe(node)
      attributes.observe(node, { attributes: true, attributeFilter: ['class', 'style', 'aria-hidden', 'inert', 'hidden'] })
    })
    window.addEventListener('resize', schedule)
    window.addEventListener('scroll', schedule, true)
    document.addEventListener('transitionrun', onTransition, true)
    document.addEventListener('transitionend', onTransitionEnd, true)
    document.addEventListener('transitioncancel', onTransitionEnd, true)
    const onLoad = () => { lease.frame.dataset.loadedSrc = lease.frame.dataset.requestedSrc; setStatus('ready') }
    lease.frame.addEventListener('load', onLoad)
    setStatus(lease.frame.dataset.loadedSrc === lease.frame.dataset.requestedSrc ? 'ready' : 'loading')
    const timeout = window.setTimeout(() => {
      if (lease.frame.dataset.loadedSrc !== lease.frame.dataset.requestedSrc) setStatus('timeout')
    }, 20_000)
    update()
    return () => {
      disposed = true
      refresh.current = () => {}
      cancelAnimationFrame(raf)
      clearTimeout(timeout)
      resize.disconnect()
      attributes.disconnect()
      window.removeEventListener('resize', schedule)
      window.removeEventListener('scroll', schedule, true)
      document.removeEventListener('transitionrun', onTransition, true)
      document.removeEventListener('transitionend', onTransitionEnd, true)
      document.removeEventListener('transitioncancel', onTransitionEnd, true)
      lease.frame.removeEventListener('load', onLoad)
      lease.release()
      leaseRef.current = null
    }
    // Ownership changes wake only a surface that failed to acquire. Successful
    // leases must not release/reacquire in response to their own release event.
  }, [project.id, project.status, project.url, project.readyAt, active, retry, hostVersion])

  useLayoutEffect(() => {
    refresh.current()
  }, [active, blocked, moving, status])

  return { placeholder, status, retry: () => setRetry(value => value + 1) }
}
