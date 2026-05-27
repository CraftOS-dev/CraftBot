import { useEffect, useState, type ReactNode } from 'react'
import { Ban, Check, Loader2, MessageCircle, X } from 'lucide-react'
import type { MascotActionStatus, NarrationContent } from './useMascotNarration'
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

/** Floating speech bubble beside the mascot. Renders one of four
 *  content shapes:
 *
 *  - `action`   — formatted by an action-specific formatter from
 *                 mascotFormatters.ts. Two-line: icon + label + body.
 *  - `message`  — plain user-facing message text (send_message family).
 *  - `thinking` — between-actions placeholder while a task is still active.
 *  - `waiting`  — agent is paused on a user reply (mascot-state override). */
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

  const sideClass = side === 'left' ? styles.bubbleSideLeft : styles.bubbleSideRight
  // Re-mount key — when the bubble's visible content meaningfully
  // changes, React unmounts the old node and mounts a new one (fresh
  // fade-in). For action bubbles, the key includes the status icon so
  // running→completed feels like a beat change.
  const swapKey = bubbleSwapKey(render)

  return (
    <div
      key={swapKey}
      className={`${styles.speechBubble} ${sideClass} ${styles[`bubble_${render.kind}`] ?? ''}`}
      role="status"
      aria-live="polite"
    >
      {renderContent(render)}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Per-kind rendering
// ─────────────────────────────────────────────────────────────────────

function renderContent(content: NarrationContent): ReactNode {
  switch (content.kind) {
    case 'action': {
      const { status, label, body, bodyMono } = content.format
      return (
        <>
          <div className={styles.speechBubbleLabel}>
            <StatusIcon status={status} />
            <span>{label}</span>
          </div>
          {body && (
            <div
              className={`${styles.speechBubbleBody} ${bodyMono ? styles.speechBubbleBodyMono : ''}`}
            >
              {body}
            </div>
          )}
        </>
      )
    }
    case 'message':
      // No status icon — the message text is its own UI element. Body
      // takes the full bubble; label slot is unused.
      return <div className={styles.speechBubbleBody}>{content.text}</div>
    case 'thinking':
      // Spinner + italic "Thinking…" — the dots are appended by the CSS
      // dot-cycle animation on the inner span. Span wrapper is what
      // lets the dots sit flush against the text (no flex-gap between).
      return (
        <div className={styles.speechBubbleBody}>
          <Loader2 className={styles.speechBubbleIconSpin} size={13} />
          <span>Thinking</span>
        </div>
      )
    case 'waiting':
      // MessageCircle is the SAME icon the Tasks panel's StatusIndicator
      // shows for waiting tasks — keeps the visual language consistent
      // across the two surfaces. Icon is forced to blue via
      // .bubbleWaitingIcon; the text is white via the parent class.
      return (
        <div className={styles.speechBubbleBody}>
          <MessageCircle className={styles.bubbleWaitingIcon} size={13} />
          <span>Waiting for your reply…</span>
        </div>
      )
  }
}

/** Status icon for the 'action' bubble kind. Same accent color across
 *  every status — only the GLYPH differentiates (user wanted icon
 *  hierarchy, not color hierarchy). Loader2 is CSS-animated to spin
 *  while running. */
function StatusIcon({ status }: { status: MascotActionStatus }) {
  switch (status) {
    case 'running':
      return <Loader2 className={styles.speechBubbleIconSpin} size={13} />
    case 'completed':
      return <Check size={13} />
    case 'error':
      return <X size={13} />
    case 'cancelled':
      return <Ban size={13} />
  }
}

/** Build the React `key` used to remount the bubble on meaningful
 *  content change — change in kind, status, or primary text triggers
 *  the fade-in animation so each new "beat" reads as a fresh utterance. */
function bubbleSwapKey(content: NarrationContent): string {
  switch (content.kind) {
    case 'action':
      return `action:${content.format.status}:${content.format.label}:${content.format.body ?? ''}`
    case 'message':
      return `message:${content.text.slice(0, 32)}`
    case 'thinking':
      return 'thinking'
    case 'waiting':
      return 'waiting'
  }
}
