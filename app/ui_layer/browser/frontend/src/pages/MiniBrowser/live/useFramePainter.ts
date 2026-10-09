import { useCallback, useEffect, useRef, useState, type MutableRefObject, type RefObject } from 'react'
import type { MiniBrowserFrame } from '../../../types'
import { useLatest } from '../useLatest'
import { onLiveMessage } from '../useMiniBrowserSocket'

const isImageDataUrl = (value: unknown): value is string =>
  typeof value === 'string' && /^data:image\/(?:jpeg|png|webp);base64,/.test(value)

/** A `mini_browser_frame` payload, or null when malformed. Only inline image
 *  data is accepted: a remote URL would make the app fetch arbitrary hosts. */
export function parseFrame(data: unknown): MiniBrowserFrame | null {
  if (typeof data !== 'object' || data === null) return null
  const d = data as Record<string, unknown>
  if (typeof d.tabId !== 'string' || !isImageDataUrl(d.image)) return null
  return {
    tabId: d.tabId,
    image: d.image,
    width: typeof d.width === 'number' && d.width > 0 ? d.width : 0,
    height: typeof d.height === 'number' && d.height > 0 ? d.height : 0,
    seq: typeof d.seq === 'number' ? d.seq : 0,
  }
}

export interface FramePainter {
  /** A frame of the viewed tab is on screen. */
  hasFrame: boolean
  /** The frame on screen (its CSS-px size maps wheel and touch deltas). */
  shownFrameRef: MutableRefObject<MiniBrowserFrame | null>
  /** Wire to the <img>'s onLoad. */
  onFrameLoad(): void
}

/**
 * Paints screencast frames into `imgRef` without React: frames are read off
 * the socket, the newest per tab is kept, and the viewed tab's is painted in
 * one requestAnimationFrame. React state changes only when a frame first
 * appears or disappears — never per frame.
 */
export function useFramePainter(
  imgRef: RefObject<HTMLImageElement>,
  tabId: string | null,
  tabIdsKey: string,
): FramePainter {
  const [hasFrame, setHasFrame] = useState(false)
  // Newest frame per tab, so switching back to a tab shows it at once.
  const framesRef = useRef(new Map<string, MiniBrowserFrame>())
  const shownFrameRef = useRef<MiniBrowserFrame | null>(null)
  const rafRef = useRef(0)
  const tabIdRef = useLatest(tabId)

  const paint = useCallback(() => {
    rafRef.current = 0
    const img = imgRef.current
    if (!img) return
    const id = tabIdRef.current
    const frame = id ? framesRef.current.get(id) : undefined
    if (!frame) {
      if (shownFrameRef.current) {
        shownFrameRef.current = null
        img.removeAttribute('src')
      }
      setHasFrame(false)
      return
    }
    if (shownFrameRef.current === frame) return
    shownFrameRef.current = frame
    img.src = frame.image
  }, [imgRef, tabIdRef])

  const schedulePaint = useCallback(() => {
    if (!rafRef.current) rafRef.current = requestAnimationFrame(paint)
  }, [paint])

  useEffect(() => {
    const off = onLiveMessage('mini_browser_frame', (data) => {
      const frame = parseFrame(data)
      if (!frame) return
      framesRef.current.set(frame.tabId, frame)
      if (frame.tabId === tabIdRef.current) schedulePaint()
    })
    return () => {
      off()
      cancelAnimationFrame(rafRef.current)
      rafRef.current = 0
    }
  }, [schedulePaint, tabIdRef])

  // The viewed tab changed: show its newest frame (or none yet).
  useEffect(() => {
    shownFrameRef.current = null
    schedulePaint()
  }, [tabId, schedulePaint])

  // Forget frames of closed tabs.
  useEffect(() => {
    const open = new Set(tabIdsKey ? tabIdsKey.split('\n') : [])
    for (const id of Array.from(framesRef.current.keys())) {
      if (!open.has(id)) framesRef.current.delete(id)
    }
  }, [tabIdsKey])

  const onFrameLoad = useCallback(() => {
    if (shownFrameRef.current) setHasFrame(true)
  }, [])

  return { hasFrame, shownFrameRef, onFrameLoad }
}
