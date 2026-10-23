import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertCircle,
  Download,
  Eye,
  Globe,
  Hand,
  KeyRound,
  Loader2,
  MessageSquare,
  Power,
  RotateCw,
} from 'lucide-react'
import { Button } from '../../components/ui'
import type { MiniBrowserError } from '../../types'
import { useErrorText } from './useErrorText'
import styles from './StatusPanel.module.css'

export type PanelState = 'connecting' | 'stopped' | 'starting' | 'installing' | 'error'

interface StatusPanelProps {
  state: PanelState
  error: MiniBrowserError | null
  installLines: string[]
  onStart(): void
  onInstall(): void
  /** Put the cursor in the address bar. */
  onOpenSite(): void
  /** Drop an example prompt into this chat's composer. */
  onExample(prompt: string): void
}

// A Start/Install click shows its spinner until the backend reports a new
// state; this only bounds it if no report ever comes.
const PENDING_TIMEOUT_MS = 20_000

const INSTALL_CODES = new Set(['MINI_BROWSER_CHROMIUM_MISSING', 'MINI_BROWSER_PLAYWRIGHT_MISSING'])

/** Everything shown in place of the page while the browser isn't ready. */
export function StatusPanel({
  state,
  error,
  installLines,
  onStart,
  onInstall,
  onOpenSite,
  onExample,
}: StatusPanelProps) {
  const { t } = useTranslation(['minibrowser', 'common'])
  const errorText = useErrorText()
  const [pending, setPending] = useState<'start' | 'install' | null>(null)
  const logRef = useRef<HTMLPreElement>(null)

  // Any new report from the backend settles a pending click.
  useEffect(() => {
    setPending(null)
  }, [state, error])

  useEffect(() => {
    if (!pending) return
    const timer = window.setTimeout(() => setPending(null), PENDING_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [pending])

  // Follow the install log as it grows.
  useEffect(() => {
    const log = logRef.current
    if (log) log.scrollTop = log.scrollHeight
  }, [installLines])

  const start = () => {
    setPending('start')
    onStart()
  }
  const install = () => {
    setPending('install')
    onInstall()
  }

  const log = installLines.length > 0 && (
    <pre ref={logRef} className={styles.log} aria-label={t('minibrowser:status.installLog')} tabIndex={0}>
      {installLines.join('\n')}
    </pre>
  )

  if (state === 'connecting' || state === 'starting') {
    return (
      <div className={styles.panel} role="status">
        <div className={styles.inner}>
          <Loader2 size={28} className={styles.spin} />
          <p className={styles.lead}>
            {state === 'connecting' ? t('minibrowser:status.connecting') : t('minibrowser:status.starting')}
          </p>
        </div>
      </div>
    )
  }

  if (state === 'installing') {
    return (
      <div className={styles.panel} role="status">
        <div className={styles.inner}>
          <Loader2 size={28} className={styles.spin} />
          <p className={styles.lead}>{t('minibrowser:status.installing')}</p>
          <p className={styles.hint}>{t('minibrowser:status.installingHint')}</p>
          {log}
        </div>
      </div>
    )
  }

  if (state === 'error') {
    const text = error ? errorText(error) : null
    const code = error?.code ?? ''
    const installFailed = code === 'MINI_BROWSER_INSTALL_FAILED'
    const canInstall = INSTALL_CODES.has(code) || installFailed
    return (
      <div className={styles.panel} role="alert">
        <div className={styles.inner}>
          <div className={`${styles.badge} ${styles.badgeError}`}>
            <AlertCircle size={26} />
          </div>
          <h2 className={styles.title}>{text?.title || t('minibrowser:status.errorTitle')}</h2>
          {text?.message && <p className={styles.body}>{text.message}</p>}
          {code === 'MINI_BROWSER_PROFILE_IN_USE' && (
            <p className={styles.hint}>{t('minibrowser:status.profileInUseHint')}</p>
          )}
          {text?.detail && <p className={styles.detail}>{text.detail}</p>}
          {installFailed && log}
          <div className={styles.actions}>
            {canInstall && (
              <Button
                variant="primary"
                icon={<Download size={16} />}
                loading={pending === 'install'}
                disabled={pending !== null}
                onClick={install}
              >
                {installFailed ? t('minibrowser:status.installAgain') : t('minibrowser:status.install')}
              </Button>
            )}
            {/* A deleted chat's browser never comes back: nothing to retry. */}
            {code !== 'MINI_BROWSER_SESSION_GONE' && (
              <Button
                variant={canInstall ? 'secondary' : 'primary'}
                icon={<RotateCw size={16} />}
                loading={pending === 'start'}
                disabled={pending !== null}
                onClick={start}
              >
                {t('minibrowser:status.retry')}
              </Button>
            )}
          </div>
        </div>
      </div>
    )
  }

  // Stopped: the friendly first screen.
  return (
    <StartPage
      onOpenSite={onOpenSite}
      onExample={onExample}
      start={{ pending: pending === 'start', disabled: pending !== null, onStart: start }}
    />
  )
}

interface StartPageProps {
  /** Put the cursor in the address bar. */
  onOpenSite(): void
  /** Drop an example prompt into this chat's composer. */
  onExample(prompt: string): void
  /** The browser is off: a Start button leads (its spinner while pending). */
  start?: { pending: boolean; disabled: boolean; onStart(): void }
}

/** What this chat's browser is, and what to try: in place of a browser that
 *  is off, and over a blank tab (a new chat's first tab). */
export function StartPage({ onOpenSite, onExample, start }: StartPageProps) {
  const { t } = useTranslation('minibrowser')
  const examples = [
    t('status.examples.compare'),
    t('status.examples.news'),
    t('status.examples.research'),
  ]
  return (
    <div className={styles.panel}>
      <div className={styles.inner}>
        <div className={styles.badge}>
          <Globe size={26} />
        </div>
        <h2 className={styles.title}>{t('status.stoppedTitle')}</h2>
        <p className={styles.body}>{t('status.stoppedBody')}</p>
        <div className={styles.actions}>
          {start && (
            <Button
              variant="primary"
              icon={<Power size={16} />}
              loading={start.pending}
              disabled={start.disabled}
              onClick={start.onStart}
            >
              {t('status.start')}
            </Button>
          )}
          <Button variant={start ? 'secondary' : 'primary'} icon={<Globe size={16} />} onClick={onOpenSite}>
            {t('status.openSite')}
          </Button>
        </div>

        <div className={styles.examples}>
          <span className={styles.examplesLabel}>{t('status.tryAsking')}</span>
          <div className={styles.chips}>
            {examples.map(example => (
              <button
                key={example}
                type="button"
                className={styles.chip}
                onClick={() => onExample(example)}
                title={example}
              >
                <MessageSquare size={13} />
                <span>{example}</span>
              </button>
            ))}
          </div>
        </div>

        <ul className={styles.features}>
          <li>
            <Eye size={16} />
            <div>
              <strong>{t('status.featureWatchTitle')}</strong>
              <span>{t('status.featureWatchBody')}</span>
            </div>
          </li>
          <li>
            <Hand size={16} />
            <div>
              <strong>{t('status.featureControlTitle')}</strong>
              <span>{t('status.featureControlBody')}</span>
            </div>
          </li>
          <li>
            <KeyRound size={16} />
            <div>
              <strong>{t('status.featureLoginsTitle')}</strong>
              <span>{t('status.featureLoginsBody')}</span>
            </div>
          </li>
        </ul>
      </div>
    </div>
  )
}
