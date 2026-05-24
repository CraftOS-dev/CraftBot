import { useRef, useState } from 'react'
import {
  ChevronUp,
  ChevronDown,
  MessageCircle,
  HelpCircle,
} from 'lucide-react'
import { CraftBotMascot } from './CraftBotMascot'
import { useMascotState } from './useMascotState'
import { useDisplayedAction } from './useDisplayedAction'
import { useStageMeasure } from './useStageMeasure'
import { useMascotBehavior } from './useMascotBehavior'
import {
  CARDLESS_ACTIONS,
  MESSAGE_ACTIONS,
  computeMaxAmplitude,
  normalizeActionName,
} from './mascotEngine'
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

export function MascotDisplay({
  mascotSize = 120,
  defaultCollapsed = false,
}: Props) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  const { state, completedCount, resetIdleTimer } = useMascotState()
  const { displayed } = useDisplayedAction()
  const { openFile } = useWebSocket()

  // ── Derive render flags from agent + UI state ─────────────────────
  // Cardless actions (send_message family, task_end) are signaled by
  // overlays + wiggle rather than a renderer card.
  const normalizedName = displayed ? normalizeActionName(displayed.name) : ''
  const isCardlessAction = !!displayed && CARDLESS_ACTIONS.has(normalizedName)
  const hasCard = !!displayed && !isCardlessAction
  const isMessageAction = !!displayed && MESSAGE_ACTIONS.has(normalizedName)

  // Bubble overlay: chat-circle when sending a message, question-circle
  // when waiting for user input. Mutually exclusive.
  let bubble: 'chat' | 'wait' | null = null
  if (isMessageAction) bubble = 'chat'
  else if (state === 'waiting') bubble = 'wait'

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
  // isActive controls whether the wander loop runs. isClickable filters
  // out clicks while pinned/collapsed (sleeping IS clickable so the user
  // can wake the mascot).
  const { wanderRef, facing, isReacting, handleClick } = useMascotBehavior({
    isActive: !hasCard && !isSleeping && !collapsed,
    isClickable: !hasCard && !collapsed,
    isAsleep: canBeWoken,
    maxAmplitude,
    onWakeFromSleep: resetIdleTimer,
  })

  // ── Action renderer resolution ────────────────────────────────────
  const Renderer = hasCard && displayed ? getActionRenderer(displayed.name) : null
  const io = hasCard && displayed ? parseIO(displayed) : null

  return (
    <div className={styles.display}>
      <div
        ref={stageRef}
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
              reacting={isReacting}
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
