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
  /** The chat is ready, so example prompts can be offered. */
  chatAvailable: boolean
  onStart(): void
  onInstall(): void
  /** Put the cursor in the address bar. */
  onOpenSite(): void
  /** Drop an example prompt into the chat composer. */
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
  chatAvailable,
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
            <Button
              variant={canInstall ? 'secondary' : 'primary'}
              icon={<RotateCw size={16} />}
              loading={pending === 'start'}
              disabled={pending !== null}
              onClick={start}
            >
              {t('minibrowser:status.retry')}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // Stopped: the friendly first screen.
  const examples = [
    t('minibrowser:status.examples.compare'),
    t('minibrowser:status.examples.news'),
    t('minibrowser:status.examples.research'),
  ]
  return (
    <div className={styles.panel}>
      <div className={styles.inner}>
        <div className={styles.badge}>
          <Globe size={26} />
        </div>
        <h2 className={styles.title}>{t('minibrowser:status.stoppedTitle')}</h2>
        <p className={styles.body}>{t('minibrowser:status.stoppedBody')}</p>
        <div className={styles.actions}>
          <Button
            variant="primary"
            icon={<Power size={16} />}
            loading={pending === 'start'}
            disabled={pending !== null}
            onClick={start}
          >
            {t('minibrowser:status.start')}
          </Button>
          <Button variant="secondary" icon={<Globe size={16} />} onClick={onOpenSite}>
            {t('minibrowser:status.openSite')}
          </Button>
        </div>

        {chatAvailable && (
          <div className={styles.examples}>
            <span className={styles.examplesLabel}>{t('minibrowser:status.tryAsking')}</span>
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
        )}

        <ul className={styles.features}>
          <li>
            <Eye size={16} />
            <div>
              <strong>{t('minibrowser:status.featureWatchTitle')}</strong>
              <span>{t('minibrowser:status.featureWatchBody')}</span>
            </div>
          </li>
          <li>
            <Hand size={16} />
            <div>
              <strong>{t('minibrowser:status.featureControlTitle')}</strong>
              <span>{t('minibrowser:status.featureControlBody')}</span>
            </div>
          </li>
          <li>
            <KeyRound size={16} />
            <div>
              <strong>{t('minibrowser:status.featureLoginsTitle')}</strong>
              <span>{t('minibrowser:status.featureLoginsBody')}</span>
            </div>
          </li>
        </ul>
      </div>
    </div>
  )
}
