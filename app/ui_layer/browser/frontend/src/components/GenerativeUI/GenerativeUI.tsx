import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Check, MoreHorizontal, RotateCcw, RefreshCw, Pause, Play, Loader2, AlertCircle } from 'lucide-react'
import type { GenerativeUIArtifact } from '../../types'
import { usePersistedState } from '../../hooks'
import { UI_STATE } from '../../store/uiState'
import { BRIDGE_CHANNEL, buildDocument, readHostTheme, validState } from './runtime'
import styles from './GenerativeUI.module.css'

/** One revision of an output, in the options menu. */
export interface OutputVersion { key: string; label: string; current: boolean }

interface Props {
  artifact: GenerativeUIArtifact
  sessionId: string
  /** Where the preview's controls (reload, options) go: the output tab
   *  strip's right end. Nothing shows until it exists. */
  controlsTarget: HTMLElement | null
  /** The output's revisions (the options menu lists them from two on). */
  versions: OutputVersion[]
  onSelectVersion(key: string): void
}

/** One output running in its sandbox, with its reload and options controls
 *  in the tab strip above it. */
export function GenerativeUI({ artifact, sessionId, controlsTarget, versions, onSelectVersion }: Props) {
  const { t } = useTranslation('chat')
  const timeoutText = useRef('')
  timeoutText.current = t('generativeUI.timeout')
  const [state, saveState] = usePersistedState(UI_STATE.chat.artifactState(JSON.stringify([sessionId, artifact.id])))
  const stateRef = useRef(state)
  stateRef.current = state
  const frame = useRef<HTMLIFrameElement>(null)
  const options = useRef<HTMLDetailsElement>(null)
  const [attempt, setAttempt] = useState(0)
  const [paused, setPaused] = useState(false)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)
  useLayoutEffect(() => {
    if (confirmReset) options.current?.querySelector('button')?.focus()
  }, [confirmReset])
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (options.current?.open && !options.current.contains(event.target as Node)) options.current.open = false
    }
    const dismissFromPreview = () => {
      if (document.activeElement === frame.current && options.current) options.current.open = false
    }
    document.addEventListener('pointerdown', dismiss)
    window.addEventListener('blur', dismissFromPreview)
    return () => { document.removeEventListener('pointerdown', dismiss); window.removeEventListener('blur', dismissFromPreview) }
  }, [])
  // Saved state intentionally does not rebuild the document on every interaction.
  const runtime = useMemo(() => {
    const token = crypto.randomUUID().replace(/-/g, '')
    return { token, html: buildDocument(artifact, stateRef.current, token, window.location.origin) }
  }, [artifact, attempt, sessionId])

  // Register before the frame's first queued messages can arrive. Translation
  // changes must not restart readiness tracking for an already loaded frame.
  useLayoutEffect(() => {
    if (paused) return
    setStatus('loading')
    setError('')
    const timer = window.setTimeout(() => {
      setStatus(current => current === 'loading' ? 'error' : current)
      setError(current => current || timeoutText.current)
    }, 10_000)
    const receive = (event: MessageEvent) => {
      const data = event.data
      // srcdoc sandbox frames have origin "null". Check the exact live Window,
      // per-mount token and message schema instead of trusting that origin.
      if (event.source !== frame.current?.contentWindow || !data || data.channel !== BRIDGE_CHANNEL || data.token !== runtime.token) return
      switch (data.type) {
        case 'ready':
          window.clearTimeout(timer)
          setStatus(current => current === 'error' ? current : 'ready')
          break
        case 'state':
          if (validState(data.state)) saveState(data.state)
          break
        case 'error':
          window.clearTimeout(timer)
          if (typeof data.message === 'string') { setError(data.message.slice(0, 1000)); setStatus('error') }
          break
      }
    }
    window.addEventListener('message', receive)
    const syncTheme = () => frame.current?.contentWindow?.postMessage({ channel: BRIDGE_CHANNEL, token: runtime.token, type: 'theme', theme: readHostTheme() }, '*')
    const observer = new MutationObserver(syncTheme)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { observer.disconnect(); window.clearTimeout(timer); window.removeEventListener('message', receive) }
  }, [runtime, paused, saveState])

  const restart = (reset = false) => {
    if (options.current?.open) { options.current.open = false; options.current.querySelector('summary')?.focus() }
    setConfirmReset(false)
    if (reset) { stateRef.current = {}; saveState({}) }
    setPaused(false)
    setAttempt(value => value + 1)
  }
  const preview = (
    <div className={styles.canvas}><div className={styles.preview}>
      {paused ? <div className={styles.paused}>
        <span className={styles.statusIcon}><Pause size={22} /></span>
        <h3>{t('generativeUI.pausedTitle')}</h3><p>{t('generativeUI.paused')}</p>
        <button type="button" className={styles.resume} onClick={() => restart()}><Play size={15} />{t('generativeUI.resume')}</button>
      </div> : <>
        {status === 'loading' && <div className={styles.loading} role="status"><Loader2 size={22} /><span>{t('generativeUI.loading')}</span></div>}
        {status === 'error' && <div className={styles.error} role="alert">
          <AlertCircle size={18} /><div><strong>{t('generativeUI.error')}</strong><details><summary>{t('generativeUI.errorDetails')}</summary><p>{error}</p></details></div>
          <button type="button" onClick={() => restart()}>{t('generativeUI.tryAgain')}</button>
        </div>}
        <iframe key={runtime.token} ref={frame} title={artifact.title} srcDoc={runtime.html} sandbox="allow-scripts allow-forms"
          onLoad={() => frame.current?.contentWindow?.postMessage({ channel: BRIDGE_CHANNEL, token: runtime.token, type: 'initialize', theme: readHostTheme() }, '*')}
          referrerPolicy="no-referrer" allow="camera 'none'; microphone 'none'; geolocation 'none'; clipboard-read 'none'; clipboard-write 'none'"
          className={`${styles.frame} ${status === 'ready' ? styles.frameReady : ''}`} />
      </>}
    </div></div>
  )
  const closeMenu = () => {
    if (options.current) options.current.open = false
  }
  const controls = <div className={styles.controls}>
      <button type="button" onClick={() => restart()} aria-label={t('generativeUI.retry')} title={t('generativeUI.retry')}><RefreshCw size={15} /></button>
      <details ref={options} className={styles.menu} onToggle={() => { if (!options.current?.open) setConfirmReset(false) }} onKeyDown={event => { if (event.key === 'Escape' && options.current) { event.preventDefault(); event.stopPropagation(); options.current.open = false; options.current.querySelector('summary')?.focus() } }}>
        <summary aria-label={t('generativeUI.options')} title={t('generativeUI.options')}><MoreHorizontal size={18} /></summary>
        <div className={styles.menuItems}>
          {confirmReset ? <div className={styles.resetConfirmation}>
            <strong>{t('generativeUI.resetTitle')}</strong><p>{t('generativeUI.resetDescription')}</p>
            <div><button type="button" onClick={() => { setConfirmReset(false); options.current?.querySelector('summary')?.focus() }}>{t('generativeUI.cancel')}</button><button type="button" className={styles.destructive} onClick={() => restart(true)}>{t('generativeUI.confirmReset')}</button></div>
          </div> : <>
            {!paused && <button type="button" onClick={() => { closeMenu(); setPaused(true) }}><Pause size={15} />{t('generativeUI.pause')}</button>}
            <button type="button" onClick={() => setConfirmReset(true)}><RotateCcw size={15} />{t('generativeUI.reset')}</button>
            {versions.length > 1 && <div className={styles.versions} role="group" aria-label={t('generativeUI.versions')}>
              <span className={styles.versionsLabel}>{t('generativeUI.versions')}</span>
              {versions.map(version => <button key={version.key} type="button" aria-pressed={version.current} onClick={() => { closeMenu(); if (!version.current) onSelectVersion(version.key) }}>
                <span className={styles.versionCheck}>{version.current && <Check size={14} />}</span>{version.label}
              </button>)}
            </div>}
          </>}
        </div>
      </details>
    </div>
  return <div className={styles.artifact}>
    {controlsTarget && createPortal(controls, controlsTarget)}
    {preview}
  </div>
}
