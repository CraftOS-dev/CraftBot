import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Play } from 'lucide-react'
import { Button } from '../../components/ui'
import type { MiniBrowserLastFrame } from '../../types'
import styles from './ResumeView.module.css'

interface ResumeViewProps {
  /** Where the browser left off. */
  frame: MiniBrowserLastFrame
  /** 'resuming': the browser is starting (its pages reopen); 'paused': it is
   *  off until the user resumes it. */
  mode: 'resuming' | 'paused'
  onResume(): void
}

// A Resume click shows its spinner until the backend reports a new state;
// this only bounds it if no report ever comes.
const PENDING_TIMEOUT_MS = 20_000

/**
 * The page the browser left off on, dimmed, in place of the live page while
 * the browser starts again or is off, so the panel is never blank.
 */
export function ResumeView({ frame, mode, onResume }: ResumeViewProps) {
  const { t } = useTranslation('minibrowser')
  const [pending, setPending] = useState(false)

  // A new state from the backend settles a pending click.
  useEffect(() => {
    setPending(false)
  }, [mode])

  useEffect(() => {
    if (!pending) return
    const timer = window.setTimeout(() => setPending(false), PENDING_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [pending])

  const resume = () => {
    if (pending) return
    setPending(true)
    onResume()
  }

  return (
    <div
      className={`${styles.view} ${mode === 'paused' ? styles.paused : ''}`}
      onClick={mode === 'paused' ? resume : undefined}
    >
      <img className={styles.picture} src={frame.image} alt="" draggable={false} />
      {mode === 'resuming' ? (
        <div className={styles.notice} role="status">
          <Loader2 size={16} className={styles.spin} />
          <span>{t('status.resuming')}</span>
        </div>
      ) : (
        <div className={styles.card} role="status">
          <strong className={styles.cardTitle}>{t('status.pausedTitle')}</strong>
          <p className={styles.cardBody}>{t('status.pausedBody')}</p>
          <Button
            variant="primary"
            icon={<Play size={16} />}
            loading={pending}
            disabled={pending}
            onClick={event => {
              event.stopPropagation()
              resume()
            }}
          >
            {t('status.resume')}
          </Button>
        </div>
      )}
    </div>
  )
}
