import { useEffect, useRef, useState } from 'react'
import {
  ChevronUp,
  ChevronDown,
  MessageCircle,
  HelpCircle,
} from 'lucide-react'
import { CraftBotMascot } from './CraftBotMascot'
import { useMascotState } from './useMascotState'
import { useDisplayedAction } from './useDisplayedAction'
import { useWebSocket } from '../../browser/frontend/src/contexts/WebSocketContext'
import {
  getActionRenderer,
  parseIO,
} from '../../browser/frontend/src/pages/Tasks/actionRenderers/renderers'
import styles from './Mascot.module.css'

interface Props {
  /** Optional pixel size for the mascot SVG. Defaults to 120. */
  mascotSize?: number
  /** Whether the panel starts collapsed (mascot hidden, status only). */
  defaultCollapsed?: boolean
}

// Action names that don't get a renderer card. send_message family is
// handled by the chat bubble overlay (the message already lives in the
// chat panel below); task_end is signaled by the celebrating wiggle that
// fires when completedCount rises.
const CARDLESS_ACTIONS: ReadonlySet<string> = new Set([
  'send_message',
  'send_message_with_attachment',
  'task_end',
])

const MESSAGE_ACTIONS: ReadonlySet<string> = new Set([
  'send_message',
  'send_message_with_attachment',
])

// Action names sometimes arrive with spaces or hyphens (skill metadata)
// instead of snake_case. Normalize before matching against our sets — same
// transform getActionRenderer uses for its registry lookup.
function normalizeActionName(name: string): string {
  return name.toLowerCase().replace(/[\s-]+/g, '_')
}

// Each "step" of the wander = one hop. The mascot crouches, springs up,
// arcs to the new spot, and squash-lands. WANDER_STEP_MS is the cadence
// between hops; HOP_DURATION_MS is how long a single hop takes (must be
// strictly shorter so the breathing/idle animation gets some screen-time
// between bounces — otherwise the character looks frantic).
const WANDER_STEP_MS = 1500
const WANDER_AMPLITUDE_PX = 20
const HOP_DURATION_MS = 850
const SETTLE_DURATION_MS = 400

export function MascotDisplay({
  mascotSize = 120,
  defaultCollapsed = false,
}: Props) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  const { state, completedCount } = useMascotState()
  const { displayed } = useDisplayedAction()
  const { openFile } = useWebSocket()

  // Split "displayed action" into the two visual paths:
  //   - hasCard: the real Tasks-page renderer sits on the right inside a
  //     compact wrapper, mascot pins to the left
  //   - cardless: special action (send_message family / task_end) — no
  //     card, mascot stays centered, a bubble or wiggle does the talking
  const normalizedName = displayed ? normalizeActionName(displayed.name) : ''
  const isCardlessAction = !!displayed && CARDLESS_ACTIONS.has(normalizedName)
  const hasCard = !!displayed && !isCardlessAction
  const isMessageAction = !!displayed && MESSAGE_ACTIONS.has(normalizedName)

  // Bubble overlay decision. Chat bubble wins when sending a message
  // (more specific signal). Otherwise the waiting state gets its own
  // question-mark bubble so the user notices a reply gate independently
  // of the mascot's body pose.
  let bubble: 'chat' | 'wait' | null = null
  if (isMessageAction) bubble = 'chat'
  else if (state === 'waiting') bubble = 'wait'

  const isSleeping = state === 'idle' || state === 'stopped' || state === 'error'
  const shouldWander = !hasCard && !isSleeping && !collapsed

  // Wander direction. The mascot translates to ±WANDER_AMPLITUDE_PX based
  // on this state, and faces the same way. Both flip together every
  // WANDER_STEP_MS — guaranteeing facing matches direction of travel.
  const [walkDir, setWalkDir] = useState<'left' | 'right'>('right')
  useEffect(() => {
    if (!shouldWander) return
    const id = window.setInterval(() => {
      setWalkDir(d => (d === 'left' ? 'right' : 'left'))
    }, WANDER_STEP_MS)
    return () => window.clearInterval(id)
  }, [shouldWander])

  // Pinned-left mode: the mascot looks at the renderer card → face right.
  // Wandering or otherwise free: facing is the current walk direction.
  const facing: 'left' | 'right' = hasCard ? 'right' : walkDir

  // The hop animation runs on this element via the Web Animations API.
  // CSS transitions can only ease between two values, but a Luxo-Jr-style
  // hop needs a multi-stop keyframe sequence (crouch → push off → arc →
  // squash on landing → settle), so we drive it imperatively.
  const wanderRef = useRef<HTMLDivElement>(null)
  // Where the previous hop ended. Subsequent hops start from here, so the
  // motion is continuous instead of snapping back to the origin each time.
  const lastTargetRef = useRef<number>(0)
  const currentAnimRef = useRef<Animation | null>(null)

  useEffect(() => {
    const el = wanderRef.current
    if (!el) return

    const target = shouldWander
      ? (walkDir === 'right' ? WANDER_AMPLITUDE_PX : -WANDER_AMPLITUDE_PX)
      : 0
    const start = lastTargetRef.current
    if (start === target) return

    // If a previous hop is still mid-flight (rare, but happens when the
    // user toggles state quickly), commit its current visual state to the
    // inline style before canceling so we don't snap to the keyframe-0
    // baseline of the new animation. commitStyles can throw in some
    // browsers when the element is detached — ignore those failures.
    if (currentAnimRef.current) {
      try { currentAnimRef.current.commitStyles() } catch { /* noop */ }
      currentAnimRef.current.cancel()
    }

    const distance = target - start
    const mid = start + distance / 2
    const isHop = shouldWander

    // For a hop: 8-keyframe arc with squash-and-stretch. For the
    // return-to-center (shouldWander turning off), just a quick ease back.
    const keyframes: Keyframe[] = isHop
      ? [
          { transform: `translate(${start}px, 0) scale(1, 1)`, offset: 0 },
          // Crouch — wider + shorter, slight dip into the floor.
          { transform: `translate(${start}px, 4px) scale(1.15, 0.85)`, offset: 0.18 },
          // Push off — body stretches up as it leaves the ground.
          { transform: `translate(${start + distance * 0.25}px, -12px) scale(0.92, 1.10)`, offset: 0.35 },
          // Peak — apex of the arc.
          { transform: `translate(${mid}px, -18px) scale(0.94, 1.06)`, offset: 0.5 },
          // Descent — still stretched, approaching landing spot.
          { transform: `translate(${start + distance * 0.75}px, -12px) scale(0.95, 1.06)`, offset: 0.65 },
          // Landing — heaviest squash, absorbs the impact.
          { transform: `translate(${target}px, 4px) scale(1.18, 0.82)`, offset: 0.80 },
          // Recovery — half-squash on the way back to neutral.
          { transform: `translate(${target}px, 2px) scale(1.05, 0.96)`, offset: 0.90 },
          // Settle — back to rest at the new spot.
          { transform: `translate(${target}px, 0) scale(1, 1)`, offset: 1 },
        ]
      : [
          { transform: `translate(${start}px, 0) scale(1, 1)` },
          { transform: `translate(0, 0) scale(1, 1)` },
        ]

    currentAnimRef.current = el.animate(keyframes, {
      duration: isHop ? HOP_DURATION_MS : SETTLE_DURATION_MS,
      easing: 'ease-in-out',
      fill: 'forwards',
    })
    lastTargetRef.current = target
  }, [walkDir, shouldWander])

  // Resolve the renderer for the displayed action. Reuses the Tasks-page
  // registry directly — same getActionRenderer + parseIO contract — and
  // wraps it in a compact, scrollable square card so it fits the slot.
  const Renderer = hasCard && displayed ? getActionRenderer(displayed.name) : null
  const io = hasCard && displayed ? parseIO(displayed) : null

  const effectiveSize = collapsed ? 48 : mascotSize

  return (
    <div className={styles.display}>
      <div
        className={`
          ${styles.stage}
          ${hasCard ? styles.stageWithAction : ''}
          ${collapsed ? styles.stageCompact : ''}
        `.trim()}
      >
        <div
          className={`${styles.mascotLayer} ${hasCard ? styles.mascotLeft : styles.mascotCenter}`}
          style={{ width: effectiveSize, height: effectiveSize }}
        >
          <div ref={wanderRef} className={styles.wander}>
            <CraftBotMascot
              state={state}
              size={effectiveSize}
              completedCount={completedCount}
              facing={facing}
            />
          </div>
          {bubble && !collapsed && (
            <div
              className={`${styles.bubble} ${bubble === 'chat' ? styles.bubbleChat : styles.bubbleWait}`}
              aria-hidden="true"
            >
              {bubble === 'chat' ? <MessageCircle size={16} /> : <HelpCircle size={16} />}
            </div>
          )}
        </div>

        {hasCard && !collapsed && displayed && (
          <div key={displayed.id} className={styles.rendererLayer}>
            <div className={styles.compactRenderer}>
              {Renderer && io ? (
                <Renderer
                  item={displayed}
                  inputObj={io.inputObj}
                  outputObj={io.outputObj}
                  onOpenFile={openFile}
                />
              ) : (
                <div className={styles.compactFallback}>
                  <div className={styles.compactFallbackName}>{displayed.name}</div>
                  <div className={styles.compactFallbackStatus}>
                    {displayed.status === 'running' ? 'Running…' : displayed.status}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className={styles.statusBar}>
        <button
          type="button"
          className={styles.collapseBtn}
          onClick={() => setCollapsed(c => !c)}
          title={collapsed ? 'Show mascot' : 'Hide mascot'}
          aria-label={collapsed ? 'Show mascot' : 'Hide mascot'}
        >
          {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>
      </div>
    </div>
  )
}
