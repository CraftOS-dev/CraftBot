import { useMemo } from 'react'
import { Lightbulb } from 'lucide-react'
import type { LivingUITodo } from '../../types'
import { useRotatingHint } from '../../hooks'
import { CraftBotMascot } from '@mascot'
import styles from './LivingUIPage.module.css'

interface Props {
  projectName: string
  todos: LivingUITodo[] | undefined
}

const HINTS = [
  'Your Living UI runs its own backend — state survives page reloads.',
  'You can ask CraftBot to modify the Living UI anytime after launch.',
  'Living UIs can use your connected integrations (Gmail, Slack, and more).',
  'The agent builds features one at a time — backend first, then UI.',
  'Export any Living UI as a ZIP to share or back up.',
  'CraftBot can interact with your Living UI via HTTP — ask it to add or read data.',
  'Share your Living UI over LAN or a public Cloudflare tunnel from the project menu.',
  'Typical build time is 15–30 minutes depending on app complexity.',
]

const WORKFLOW_PREFIX = /^\s*(acknowledge|collect|execute|verify|confirm|cleanup)\s*:\s*/i

function cleanLabel(text: string | undefined | null): string {
  if (!text) return ''
  const stripped = text.replace(WORKFLOW_PREFIX, '').trim()
  if (!stripped) return ''
  return stripped.charAt(0).toUpperCase() + stripped.slice(1)
}

interface ProgressView {
  total: number
  completed: number
  progress: number
  currentLabel: string
  stepLabel: string
  indeterminate: boolean
}

function deriveProgressView(todos: LivingUITodo[] | undefined): ProgressView {
  const list = todos ?? []
  const total = list.length
  if (total === 0) {
    return {
      total: 0,
      completed: 0,
      progress: 0,
      currentLabel: 'Planning tasks…',
      stepLabel: 'Planning',
      indeterminate: true,
    }
  }

  const completed = list.filter(t => t.status === 'completed').length
  const inProgress = list.find(t => t.status === 'in_progress') ?? null
  const currentIdx = inProgress ? list.findIndex(t => t.id === inProgress.id) : completed

  return {
    total,
    completed,
    progress: (completed / total) * 100,
    currentLabel:
      cleanLabel(inProgress?.active_form) ||
      cleanLabel(inProgress?.content) ||
      'Thinking about the next step…',
    stepLabel: `Step ${Math.min(currentIdx + 1, total)} of ${total}`,
    indeterminate: false,
  }
}

export function CreationProgress({ projectName, todos }: Props) {
  const hint = useRotatingHint(HINTS)
  const view = useMemo(() => deriveProgressView(todos), [todos])

  return (
    <div className={styles.creationProgress}>
      <CraftBotMascot
        state="creating"
        progress={view.progress}
        completedCount={view.completed}
      />
      <p className={styles.creationTitle}>Creating {projectName}</p>

      <div className={styles.progressMeta}>
        <span className={styles.phaseLabel}>{view.stepLabel}</span>
      </div>

      <div className={styles.progressBar}>
        <div
          className={`${styles.progressFill} ${view.indeterminate ? styles.indeterminate : ''}`}
          style={view.indeterminate ? undefined : { width: `${view.progress}%` }}
        />
      </div>

      <p className={styles.progressMessage}>{view.currentLabel}</p>

      <div className={styles.hintsBox}>
        <Lightbulb size={16} className={styles.hintIcon} />
        <p className={styles.rotatingHint} style={{ opacity: hint.visible ? 1 : 0 }}>
          {hint.text}
        </p>
      </div>
    </div>
  )
}
