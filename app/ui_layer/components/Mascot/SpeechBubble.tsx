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

/** Speech bubble visual. Floats beside the mascot (side chosen
 *  dynamically by useMascotBehavior) and follows the wander wrapper's
 *  hop translation.
 *
 *  Content swaps fade in/out via a small keyed re-mount: when the kind
 *  or primary text changes, the old node fades out and a fresh one fades
 *  in, so consecutive narration phases read as discrete "speech beats"
 *  instead of one bubble whose text silently changes. */
export function SpeechBubble({ content, side = 'right' }: Props) {
  // Keep the last non-null content around for one fade-out cycle so the
  // bubble doesn't pop out instantly when narration ends. In practice
  // the FSM nearly always replaces with the next bubble anyway.
  const [render, setRender] = useState<NarrationContent | null>(content)

  useEffect(() => {
    if (content) setRender(content)
    else {
      const id = window.setTimeout(() => setRender(null), 180)
      return () => window.clearTimeout(id)
    }
  }, [content])

  if (!render) return null

  const { label, body } = bubbleText(render)
  const sideClass = side === 'left' ? styles.bubbleSideLeft : styles.bubbleSideRight
  // Re-mount key — when content kind or primary text changes, React
  // unmounts the old node and mounts a new one (fresh fade-in).
  const swapKey = `${render.kind}:${label ?? ''}:${body.slice(0, 32)}`

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

/** Map a NarrationContent variant to the displayed `{label, body}` pair.
 *  Pure function — pulled out so the component stays focused on the
 *  React lifecycle + DOM, and the per-kind text shaping has a single
 *  obvious home. */
function bubbleText(content: NarrationContent): { label: string | null; body: string } {
  switch (content.kind) {
    case 'running':
      return {
        label: `Running ${content.actionName}`,
        body: content.params ? `with ${content.params}` : '',
      }
    case 'result':
      return {
        label: `${content.actionName} →`,
        body: content.result,
      }
    case 'message':
      return { label: null, body: content.text }
    case 'thinking':
      return { label: null, body: 'Thinking…' }
    case 'waiting':
      return { label: null, body: 'Waiting for your reply…' }
  }
}
