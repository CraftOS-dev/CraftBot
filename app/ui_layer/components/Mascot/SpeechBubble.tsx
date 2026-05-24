import { useEffect, useState } from 'react'
import type { NarrationContent } from './useMascotNarration'
import styles from './Mascot.module.css'

interface Props {
  /** What to render inside the bubble. null hides the bubble entirely
   *  (no DOM presence so the layout is clean when nothing's playing). */
  content: NarrationContent | null
  /** Which side of the mascot to anchor to. Driven by useMascotBehavior
   *  so the bubble sits opposite the mascot's drift direction and stays
   *  visible when the mascot wanders near a stage edge. */
  side?: 'left' | 'right'
}

/** Floating speech bubble anchored above the mascot. Lives inside the
 *  `.wander` wrapper so it follows the mascot's hop translation; the
 *  bubble's own scale/transform-origin keeps it readable even while the
 *  body squashes on landing.
 *
 *  Content swaps fade in/out via a small keyed re-mount: when the kind
 *  or primary text changes, the old node fades out and a fresh one fades
 *  in, so consecutive narration phases read as discrete "speech beats"
 *  instead of one bubble whose text silently changes. */
export function SpeechBubble({ content, side = 'right' }: Props) {
  // Keep the last non-null content around for one fade-out cycle so the
  // bubble doesn't pop out instantly when narration ends — but in
  // practice the FSM nearly always replaces with the next bubble anyway.
  const [render, setRender] = useState<NarrationContent | null>(content)

  useEffect(() => {
    if (content) setRender(content)
    else {
      // Defer null clearing slightly so the final bubble fades rather
      // than disappearing on the same frame the FSM clears it.
      const id = window.setTimeout(() => setRender(null), 180)
      return () => window.clearTimeout(id)
    }
  }, [content])

  if (!render) return null

  // Build the displayed text per kind. Some kinds have a label/body
  // structure (running / result), others are single-line.
  let label: string | null = null
  let body: string
  switch (render.kind) {
    case 'running':
      label = `Running ${render.actionName}`
      body = render.params ? `with ${render.params}` : ''
      break
    case 'result':
      label = `${render.actionName} →`
      body = render.result
      break
    case 'message':
      label = null
      body = render.text
      break
    case 'thinking':
      label = null
      body = 'Thinking…'
      break
    case 'waiting':
      label = null
      body = 'Waiting for your reply…'
      break
  }

  // The key drives the swap animation — when content kind or primary
  // body changes, React unmounts the old node and mounts a new one
  // (each running a fresh fade-in).
  const swapKey = `${render.kind}:${label ?? ''}:${body.slice(0, 32)}`

  const sideClass = side === 'left' ? styles.bubbleSideLeft : styles.bubbleSideRight

  return (
    <div
      key={swapKey}
      className={`${styles.speechBubble} ${sideClass} ${styles[`bubble_${render.kind}`] ?? ''}`}
      role="status"
      aria-live="polite"
    >
      {label && <div className={styles.speechBubbleLabel}>{label}</div>}
      <div className={styles.speechBubbleBody}>{body}</div>
    </div>
  )
}
