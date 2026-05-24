import { useRef, useState } from 'react'
import { ChevronUp, ChevronDown } from 'lucide-react'
import { CraftBotMascot } from './CraftBotMascot'
import { SpeechBubble } from './SpeechBubble'
import { useMascotState } from './useMascotState'
import { useMascotNarration } from './useMascotNarration'
import { useStageMeasure } from './useStageMeasure'
import { useMascotBehavior } from './useMascotBehavior'
import { computeMaxAmplitude } from './mascotEngine'
import styles from './Mascot.module.css'

interface Props {
  /** Optional pixel size for the mascot SVG. Defaults to 120. */
  mascotSize?: number
  /** Whether the panel starts collapsed (mascot hidden, status only). */
  defaultCollapsed?: boolean
}

export function MascotDisplay({
  mascotSize = 120,
  defaultCollapsed = false,
}: Props) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  const {
    state,
    completedCount,
    successTaskCount,
    abortedTaskCount,
    resetIdleTimer,
  } = useMascotState()
  const { bubble } = useMascotNarration({ mascotState: state })

  // Sleeping states (idle = 30-min idle, stopped/error = external).
  // Only 'idle' is recoverable by clicking; the others stay sleeping.
  const isSleeping = state === 'idle' || state === 'stopped' || state === 'error'
  const canBeWoken = state === 'idle'

  const effectiveSize = collapsed ? 48 : mascotSize

  // ── Stage measurement → wander amplitude ───────────────────────────
  const stageRef = useRef<HTMLDivElement>(null)
  const stageContentWidth = useStageMeasure(stageRef)
  const maxAmplitude = computeMaxAmplitude(stageContentWidth, effectiveSize)

  // ── Behavior FSM ───────────────────────────────────────────────────
  // The chat-bubble narration replaces the old action-card pin, so the
  // mascot is free to wander any time the panel is open + the agent is
  // not sleeping. Clicks are likewise allowed any time it's not
  // collapsed (sleeping mascots accept clicks so the user can wake them).
  const { wanderRef, facing, reaction, bubbleSide, handleClick } = useMascotBehavior({
    isActive: !isSleeping && !collapsed,
    isClickable: !collapsed,
    isAsleep: canBeWoken,
    maxAmplitude,
    onWakeFromSleep: resetIdleTimer,
    successTaskCount,
    abortedTaskCount,
  })

  return (
    <div className={styles.display}>
      <div
        ref={stageRef}
        className={`${styles.stage} ${collapsed ? styles.stageCompact : ''}`.trim()}
      >
        <div
          className={`${styles.mascotLayer} ${styles.mascotCenter}`}
          style={{ width: effectiveSize, height: effectiveSize }}
        >
          <div
            ref={wanderRef}
            className={styles.wander}
            onClick={handleClick}
            role="button"
            tabIndex={0}
            aria-label="Pet the mascot"
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                handleClick()
              }
            }}
          >
            <CraftBotMascot
              state={state}
              size={effectiveSize}
              completedCount={completedCount}
              facing={facing}
              reaction={reaction}
            />
            {!collapsed && <SpeechBubble content={bubble} side={bubbleSide} />}
          </div>
        </div>
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
