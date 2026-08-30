import { useEffect, useLayoutEffect, useRef, useState, useCallback } from 'react'
import { getOllamaInstallPercent } from '../../utils/ollamaInstall'
import {
  Check,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  SkipForward,
  Download,
  Play,
  Wifi,
  WifiOff,
  RefreshCw,
} from 'lucide-react'
import { Button } from '../../components/ui'
import { useTranslation, Trans } from 'react-i18next'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import { getSocketClient } from '../../store/socket/socketInstance'
import {
  selectSubscriptionOauth,
  selectSubscriptionPending,
  selectSubscriptionPasteback,
} from '../../store/selectors/modelSettings'
import { setSubscriptionPending, clearSubscriptionPasteback } from '../../store/slices/modelSettingsSlice'
import { selectOnboardingFinishing } from '../../store/selectors/onboarding'
import { markComplete } from '../../store/slices/onboardingSlice'
import type { OnboardingStepOption, OnboardingFormField } from '../../types'
import { OnboardingMascot, type OutroPhase } from './OnboardingMascot'
import styles from './OnboardingPage.module.css'

// Clean, sentence-friendly display names for the chosen provider - used to
// personalise the API-key step's prompt. (The api_key prompt is built
// dynamically since it also depends on whether the provider supports
// subscription sign-in.)
const PROVIDER_NAMES: Record<string, string> = {
  openai: 'OpenAI',
  gemini: 'Gemini',
  byteplus: 'BytePlus',
  anthropic: 'Anthropic',
  deepseek: 'DeepSeek',
  minimax: 'MiniMax',
  moonshot: 'Moonshot',
  grok: 'Grok',
  glm: 'Z.ai',
  fugu: 'Sakana',
}

// ── Ollama local-setup component ─────────────────────────────────────────────

interface OllamaSetupProps {
  defaultUrl: string
  onConnected: (url: string) => void
}

function OllamaSetup({ defaultUrl, onConnected }: OllamaSetupProps) {
  const { t } = useTranslation(['onboarding', 'common'])
  const { localLLM, checkLocalLLM, testLocalLLMConnection, installLocalLLM, startLocalLLM, pullOllamaModel } = useWebSocket()
  const [url, setUrl] = useState(defaultUrl)
  const [selectedModel, setSelectedModel] = useState('llama3.2:3b')
  const [modelSearch, setModelSearch] = useState('')

  // Auto-check on mount
  useEffect(() => {
    checkLocalLLM()
  }, [checkLocalLLM])

  // Pre-select the recommended model when the list loads
  useEffect(() => {
    if (localLLM.suggestedModels.length > 0) {
      const rec = localLLM.suggestedModels.find(m => m.recommended)
      if (rec) setSelectedModel(rec.name)
    }
  }, [localLLM.suggestedModels])

  // Notify parent when connected
  useEffect(() => {
    if (localLLM.phase === 'connected' && localLLM.testResult?.success) {
      onConnected(url)
    }
  }, [localLLM.phase, localLLM.testResult, url, onConnected])

  const { phase, installProgress, testResult, error } = localLLM

  const isWorking = phase === 'checking' || phase === 'installing' || phase === 'starting' || phase === 'pulling_model'

  // ── Checking ──
  if (phase === 'idle' || phase === 'checking') {
    return (
      <div className={styles.ollamaBox}>
        <div className={styles.ollamaChecking}>
          <div className={styles.spinner} />
          <span>{t('onboarding:ollama.checking')}</span>
        </div>
      </div>
    )
  }

  // ── Not installed ──
  if (phase === 'not_installed') {
    return (
      <div className={styles.ollamaBox}>
        <div className={styles.ollamaStatusRow}>
          <WifiOff size={18} className={styles.iconError} />
          <span className={styles.ollamaStatusLabel}>{t('onboarding:ollama.notInstalledStatus')}</span>
        </div>
        <p className={styles.ollamaHint}>
          {t('onboarding:ollama.notInstalledHint')}
        </p>
        <Button variant="primary" onClick={installLocalLLM} icon={<Download size={16} />}>
          {t('onboarding:ollama.install')}
        </Button>
      </div>
    )
  }

  // ── Installing ──
  if (phase === 'installing') {
    const pct = getOllamaInstallPercent(installProgress)
    return (
      <div className={styles.ollamaBox}>
        <div className={styles.ollamaStatusRow}>
          <div className={styles.spinnerSmall} />
          <span className={styles.ollamaStatusLabel}>{t('onboarding:ollama.installing')}</span>
          <span className={styles.installPct}>{pct}%</span>
        </div>
        <div className={styles.installProgressBar}>
          <div className={styles.installProgressFill} style={{ width: `${pct}%` }} />
        </div>
        <div className={styles.installLog}>
          {installProgress.length === 0 && <span className={styles.installLogLine}>{t('onboarding:ollama.installStarting')}</span>}
          {installProgress.map((line, i) => (
            <span key={i} className={styles.installLogLine}>{line}</span>
          ))}
        </div>
      </div>
    )
  }

  // ── Installed but not running ──
  if (phase === 'not_running') {
    return (
      <div className={styles.ollamaBox}>
        <div className={styles.ollamaStatusRow}>
          <WifiOff size={18} className={styles.iconWarning} />
          <span className={styles.ollamaStatusLabel}>{t('onboarding:ollama.notRunningStatus')}</span>
        </div>
        <p className={styles.ollamaHint}>{t('onboarding:ollama.notRunningHint')}</p>
        <Button variant="primary" onClick={startLocalLLM} icon={<Play size={16} />}>
          {t('onboarding:ollama.start')}
        </Button>
      </div>
    )
  }

  // ── Starting ──
  if (phase === 'starting') {
    return (
      <div className={styles.ollamaBox}>
        <div className={styles.ollamaStatusRow}>
          <div className={styles.spinnerSmall} />
          <span className={styles.ollamaStatusLabel}>{t('onboarding:ollama.starting')}</span>
        </div>
      </div>
    )
  }

  // ── Error ──
  if (phase === 'error') {
    return (
      <div className={styles.ollamaBox}>
        <div className={styles.ollamaStatusRow}>
          <AlertCircle size={18} className={styles.iconError} />
          <span className={styles.ollamaStatusLabel}>{t('common:status.somethingWentWrong')}</span>
        </div>
        {error && <p className={styles.ollamaHint}>{error}</p>}
        <Button variant="secondary" onClick={checkLocalLLM} icon={<RefreshCw size={16} />}>
          {t('common:actions.retry')}
        </Button>
      </div>
    )
  }

  // ── Select model ──
  if (phase === 'selecting_model') {
    const allModels = localLLM.suggestedModels.length > 0 ? localLLM.suggestedModels : []
    const filteredModels = allModels.filter(m =>
      m.name.toLowerCase().includes(modelSearch.toLowerCase()) ||
      m.label.toLowerCase().includes(modelSearch.toLowerCase())
    )
    return (
      <div className={styles.ollamaBox}>
        <div className={styles.ollamaStatusRow}>
          <Wifi size={18} className={styles.iconMuted} />
          <span className={styles.ollamaStatusLabel}>{t('onboarding:ollama.runningNoModels')}</span>
        </div>
        <p className={styles.ollamaHint}>{t('onboarding:ollama.selectModelHint')}</p>
        <input
          className={styles.modelSearchInput}
          type="text"
          placeholder={t('onboarding:ollama.findModel')}
          value={modelSearch}
          onChange={e => setModelSearch(e.target.value)}
        />
        <div className={styles.modelList}>
          {filteredModels.map(m => (
            <label key={m.name} className={`${styles.modelOption} ${selectedModel === m.name ? styles.modelOptionSelected : ''}`}>
              <input
                type="radio"
                name="ollama_model"
                value={m.name}
                checked={selectedModel === m.name}
                onChange={() => setSelectedModel(m.name)}
              />
              <span className={styles.modelOptionName}>{m.label}</span>
              <span className={styles.modelOptionSize}>{m.size}</span>
              {m.recommended && <span className={styles.modelOptionBadge}>{t('onboarding:ollama.recommended')}</span>}
            </label>
          ))}
          {filteredModels.length === 0 && (
            <p className={styles.ollamaHint}>{t('onboarding:ollama.noModelMatch', { query: modelSearch })}</p>
          )}
        </div>
        <Button variant="primary" onClick={() => pullOllamaModel(selectedModel)} disabled={!selectedModel} icon={<Download size={16} />}>
          {t('onboarding:ollama.download', { model: selectedModel || t('onboarding:ollama.modelFallback') })}
        </Button>
      </div>
    )
  }

  // ── Pulling model ──
  if (phase === 'pulling_model') {
    const bytes = localLLM.pullBytes
    const fmtBytes = (n: number) => {
      if (n >= 1073741824) return `${(n / 1073741824).toFixed(1)} GB`
      if (n >= 1048576) return `${(n / 1048576).toFixed(0)} MB`
      return `${(n / 1024).toFixed(0)} KB`
    }
    const latestStatus = localLLM.pullProgress[localLLM.pullProgress.length - 1] ?? t('onboarding:ollama.downloadStarting')
    return (
      <div className={styles.ollamaBox}>
        <div className={styles.ollamaStatusRow}>
          <div className={styles.spinnerSmall} />
          <span className={styles.ollamaStatusLabel}>{t('onboarding:ollama.downloading', { model: selectedModel })}</span>
        </div>
        {bytes && bytes.total > 0 ? (
          <>
            <div className={styles.downloadProgressBar}>
              <div className={styles.downloadProgressFill} style={{ width: `${bytes.percent}%` }} />
            </div>
            <div className={styles.downloadProgressInfo}>
              <span>{fmtBytes(bytes.completed)} / {fmtBytes(bytes.total)}</span>
              <span>{bytes.percent}%</span>
            </div>
          </>
        ) : (
          <div className={styles.downloadProgressBar}>
            <div className={styles.downloadProgressFill} style={{ width: '0%' }} />
          </div>
        )}
        <p className={styles.downloadStatus}>{latestStatus}</p>
      </div>
    )
  }

  // ── Running - show URL field + test button ──
  const connected = phase === 'connected' && testResult?.success

  return (
    <div className={styles.ollamaBox}>
      <div className={styles.ollamaStatusRow}>
        {connected
          ? <Wifi size={18} className={styles.iconSuccess} />
          : <Wifi size={18} className={styles.iconMuted} />}
        <span className={styles.ollamaStatusLabel}>
          {connected ? t('onboarding:ollama.connected') : t('onboarding:ollama.running')}
        </span>
      </div>

      {connected && testResult?.message && (
        <p className={styles.ollamaSuccessMsg}>{testResult.message}</p>
      )}

      {!connected && (
        <>
          <label className={styles.ollamaLabel}>{t('onboarding:ollama.serverUrl')}</label>
          <div className={styles.ollamaInputRow}>
            <input
              className={styles.ollamaInput}
              type="text"
              value={url}
              onChange={e => setUrl(e.target.value)}
              placeholder="http://localhost:11434"
              disabled={isWorking}
            />
            <Button
              variant="secondary"
              onClick={() => testLocalLLMConnection(url)}
              disabled={!url || isWorking}
              icon={<Wifi size={15} />}
            >
              {t('onboarding:ollama.test')}
            </Button>
          </div>
          {testResult && !testResult.success && (
            <p className={styles.ollamaError}>{testResult.error}</p>
          )}
        </>
      )}
    </div>
  )
}

// ── iOS-style wheel picker (provider selection) ──────────────────────────────

// A short, scrollbar-free wheel like the iPhone date picker. It does NOT use
// native scrolling (which overshoots and fights scroll-snap). Instead it keeps
// a continuous offset, translates the list with it, and runs a single eased
// rAF loop toward a target - so motion stays fluid - then settles onto the
// nearest item once input goes idle.
const WHEEL_ITEM_H = 44
const WHEEL_VISIBLE = 5
const WHEEL_EASE = 0.2        // per-frame approach fraction (higher = snappier)
const WHEEL_WHEEL_SPEED = 0.5 // wheel px → offset px (one notch ≈ one item)

interface ProviderWheelProps {
  options: OnboardingStepOption[]
  value: string
  onChange: (value: string) => void
}

function ProviderWheel({ options, value, onChange }: ProviderWheelProps) {
  const boxRef = useRef<HTMLDivElement | null>(null)
  const listRef = useRef<HTMLDivElement | null>(null)
  // Latest props without re-subscribing listeners / re-running the loop.
  const valueRef = useRef(value)
  const onChangeRef = useRef(onChange)
  const optsRef = useRef(options)
  valueRef.current = value
  onChangeRef.current = onChange
  optsRef.current = options

  const height = WHEEL_VISIBLE * WHEEL_ITEM_H
  const centerPad = ((WHEEL_VISIBLE - 1) / 2) * WHEEL_ITEM_H

  const curRef = useRef(0)     // animated offset in px (0 → first item centred)
  const targetRef = useRef(0)  // offset we're easing toward
  const rafRef = useRef<number | null>(null)
  const idleRef = useRef<number | null>(null)

  const maxOffset = () => (optsRef.current.length - 1) * WHEEL_ITEM_H
  const clampOffset = (v: number) => Math.min(maxOffset(), Math.max(0, v))

  // Paint the current frame: translate the list, fade/scale items by their
  // distance from centre, and report the centred item as the selection.
  const paint = () => {
    const list = listRef.current
    if (!list) return
    list.style.transform = `translate3d(0, ${centerPad - curRef.current}px, 0)`
    const children = list.children
    for (let i = 0; i < children.length; i++) {
      const dist = Math.abs(i * WHEEL_ITEM_H - curRef.current) / WHEEL_ITEM_H
      const el = children[i] as HTMLElement
      el.style.opacity = String(Math.max(0.18, 1 - dist * 0.32))
      el.style.transform = `scale(${Math.max(0.82, 1 - dist * 0.06)})`
    }
    const idx = Math.min(
      optsRef.current.length - 1,
      Math.max(0, Math.round(curRef.current / WHEEL_ITEM_H)),
    )
    const v = optsRef.current[idx]?.value
    if (v && v !== valueRef.current) onChangeRef.current(v)
  }

  const tick = () => {
    const diff = targetRef.current - curRef.current
    if (Math.abs(diff) < 0.4) {
      curRef.current = targetRef.current
      paint()
      rafRef.current = null
      return
    }
    curRef.current += diff * WHEEL_EASE
    paint()
    rafRef.current = requestAnimationFrame(tick)
  }

  const animate = () => {
    if (rafRef.current == null) rafRef.current = requestAnimationFrame(tick)
  }

  // Once the wheel goes quiet, settle the target onto the nearest item.
  const settleSoon = () => {
    if (idleRef.current != null) window.clearTimeout(idleRef.current)
    idleRef.current = window.setTimeout(() => {
      targetRef.current = clampOffset(Math.round(targetRef.current / WHEEL_ITEM_H) * WHEEL_ITEM_H)
      animate()
    }, 80)
  }

  const goToIndex = (i: number) => {
    targetRef.current = clampOffset(i * WHEEL_ITEM_H)
    animate()
  }

  // Position at the current value when the option set loads.
  useLayoutEffect(() => {
    let i = options.findIndex(o => o.value === valueRef.current)
    if (i < 0) i = Math.max(0, options.findIndex(o => o.default))
    curRef.current = i * WHEEL_ITEM_H
    targetRef.current = curRef.current
    paint()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options])

  // Accumulate wheel delta into the target; the rAF loop eases toward it.
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      let dy = e.deltaY
      if (e.deltaMode === 1) dy *= 16           // lines → px
      else if (e.deltaMode === 2) dy *= height  // pages → px
      targetRef.current = clampOffset(targetRef.current + dy * WHEEL_WHEEL_SPEED)
      animate()
      settleSoon()
    }
    box.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      box.removeEventListener('wheel', onWheel)
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
      if (idleRef.current != null) window.clearTimeout(idleRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div ref={boxRef} className={styles.wheel} style={{ height }}>
      <div className={styles.wheelSelection} style={{ height: WHEEL_ITEM_H }} />
      <div ref={listRef} className={styles.wheelList}>
        {options.map((option, i) => (
          <div
            key={option.value}
            className={styles.wheelItem}
            style={{ height: WHEEL_ITEM_H }}
            onClick={() => goToIndex(i)}
          >
            {option.label}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main onboarding page ──────────────────────────────────────────────────────

export function OnboardingPage() {
  const { t } = useTranslation(['onboarding', 'common'])
  const {
    connected,
    onboardingStep,
    onboardingError,
    onboardingLoading,
    requestOnboardingStep,
    submitOnboardingStep,
    skipOnboardingStep,
    goBackOnboardingStep,
    localLLM,
  } = useWebSocket()

  // Providers that route through OpenRouter - model slug is configurable.
  const OR_PROXIED = ['moonshot', 'minimax']
  const OR_MODEL_DEFAULTS: Record<string, string> = {
    moonshot: 'moonshotai/kimi-k2.5',
    minimax: 'minimax/minimax-01',
  }

  // Subscription OAuth (ChatGPT Plus/Pro, SuperGrok). The connect/status
  // handlers are provider-agnostic and shared with the Settings model panel -
  // we reuse the same WebSocket messages and redux state here so signing in
  // during onboarding behaves identically. Responses flow into redux via the
  // globally-registered modelSettings handlers.
  const dispatch = useAppDispatch()
  const socket = getSocketClient()
  const subscriptionOauth = useAppSelector(selectSubscriptionOauth)
  const subscriptionPending = useAppSelector(selectSubscriptionPending)
  const subscriptionPasteback = useAppSelector(selectSubscriptionPasteback)
  const [pastebackCode, setPastebackCode] = useState('')
  // When a subscription is connected, the API-key field collapses behind a
  // subtle link so the connected state reads cleanly; the user can still
  // expand it to store a key instead.
  const [showKeyInput, setShowKeyInput] = useState(false)

  // Local form state
  const [selectedValue, setSelectedValue] = useState<string>('')
  const [textValue, setTextValue] = useState('')
  const [orModel, setOrModel] = useState('')
  // For proxied providers: 'direct' tries the native API, 'openrouter' routes via OR.
  const [proxiedVia, setProxiedVia] = useState<'direct' | 'openrouter'>('direct')
  // URL submitted from OllamaSetup
  const [ollamaUrl, setOllamaUrl] = useState('http://localhost:11434')
  const [ollamaConnected, setOllamaConnected] = useState(false)
  // Form step state (for the name steps)
  const [formValues, setFormValues] = useState<Record<string, string>>({})

  // ── Finishing outro ────────────────────────────────────────────────
  // When onboarding completes the slice sets `finishing` (instead of swapping
  // to the app immediately). We play the sequence here, in place, using the
  // existing mascot: show the "all set" line -> fade everything but the mascot
  // -> slide the mascot to centre -> crouch + launch it off-screen -> reveal
  // the main app (which fades in via a one-shot flag read by App).
  const finishing = useAppSelector(selectOnboardingFinishing)
  const [outroPhase, setOutroPhase] = useState<OutroPhase>('idle')

  useEffect(() => {
    if (!finishing) return
    const MESSAGE_HOLD = 1600
    const FADE_MS = 450
    const CENTER_MS = 560
    const JUMP_MS = 840
    const timers: number[] = []
    setOutroPhase('message')
    timers.push(window.setTimeout(() => setOutroPhase('fade'), MESSAGE_HOLD))
    timers.push(window.setTimeout(() => setOutroPhase('center'), MESSAGE_HOLD + FADE_MS))
    timers.push(window.setTimeout(() => setOutroPhase('jump'), MESSAGE_HOLD + FADE_MS + CENTER_MS))
    timers.push(window.setTimeout(() => {
      // Ask App to fade the main interface in, then swap to it.
      try { sessionStorage.setItem('cb_onboarded_fade', '1') } catch { /* ignore */ }
      dispatch(markComplete())
    }, MESSAGE_HOLD + FADE_MS + CENTER_MS + JUMP_MS))
    return () => timers.forEach(t => window.clearTimeout(t))
  }, [finishing, dispatch])

  // Show the farewell line as soon as finishing starts (avoids a one-frame
  // flash of the last step before the outro effect flips the phase).
  const isFinishing = !!finishing
  // Everything except the mascot fades away from the 'fade' phase onward.
  const outroFading = outroPhase === 'fade' || outroPhase === 'center' || outroPhase === 'jump'

  // Request first step when connected
  useEffect(() => {
    if (connected && !onboardingStep && !onboardingLoading) {
      requestOnboardingStep()
    }
  }, [connected, onboardingStep, onboardingLoading, requestOnboardingStep])

  // Reset local state when step changes
  useEffect(() => {
    if (onboardingStep) {
      setOllamaConnected(false)

      // Form step (user_profile / agent_name).
      // Preserve existing values when navigating back - only set defaults for missing fields.
      if (onboardingStep.form_fields && onboardingStep.form_fields.length > 0) {
        const formFields = onboardingStep.form_fields
        setFormValues(prev => {
          const defaults: Record<string, string> = {}
          for (const field of formFields) {
            defaults[field.name] = prev[field.name] ?? (typeof field.default === 'string' ? field.default : '')
          }
          return defaults
        })
      } else if (onboardingStep.options.length > 0) {
        const defaultOption = onboardingStep.options.find(opt => opt.default)
        setSelectedValue(defaultOption?.value || onboardingStep.options[0]?.value || '')
      } else {
        setSelectedValue('')
        setTextValue(typeof onboardingStep.default === 'string' ? onboardingStep.default : '')
        // Reset proxied-provider mode and pre-fill OR model default
        if (onboardingStep.name === 'api_key' && onboardingStep.provider && OR_PROXIED.includes(onboardingStep.provider)) {
          setProxiedVia('direct')
          setOrModel(OR_MODEL_DEFAULTS[onboardingStep.provider] || '')
        }
      }
    }
  }, [onboardingStep])

  // Keep ollamaUrl in sync with step default
  useEffect(() => {
    if (onboardingStep?.name === 'api_key' && onboardingStep.provider === 'remote') {
      const def = typeof onboardingStep.default === 'string' ? onboardingStep.default : 'http://localhost:11434'
      setOllamaUrl(def)
    }
  }, [onboardingStep])

  const handleOllamaConnected = useCallback((url: string) => {
    setOllamaUrl(url)
    setOllamaConnected(true)
  }, [])

  const isFormStep = !!(onboardingStep?.form_fields && onboardingStep.form_fields.length > 0)

  const handleSubmit = useCallback(() => {
    if (!onboardingStep) return
    const isOllamaStep = onboardingStep.name === 'api_key' && onboardingStep.provider === 'remote'
    const isProxiedStep = onboardingStep.name === 'api_key' &&
      onboardingStep.provider != null && OR_PROXIED.includes(onboardingStep.provider)

    if (isOllamaStep) {
      submitOnboardingStep(ollamaUrl)
    } else if (isProxiedStep) {
      submitOnboardingStep({ api_key: textValue, via: proxiedVia, or_model: proxiedVia === 'openrouter' ? orModel : '' })
    } else if (onboardingStep.form_fields && onboardingStep.form_fields.length > 0) {
      submitOnboardingStep(formValues)
    } else if (onboardingStep.options.length > 0) {
      submitOnboardingStep(selectedValue)
    } else {
      submitOnboardingStep(textValue)
    }
  }, [onboardingStep, selectedValue, textValue, orModel, proxiedVia, ollamaUrl, formValues, submitOnboardingStep])

  const handleSkip = useCallback(() => skipOnboardingStep(), [skipOnboardingStep])

  // Ctrl+S to skip optional steps
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        if (onboardingStep && !onboardingStep.required) {
          e.preventDefault()
          skipOnboardingStep()
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onboardingStep, skipOnboardingStep])

  const handleBack = useCallback(() => goBackOnboardingStep(), [goBackOnboardingStep])

  const isLastStep = onboardingStep ? onboardingStep.index === onboardingStep.total - 1 : false

  const isOllamaStep =
    onboardingStep?.name === 'api_key' && onboardingStep?.provider === 'remote'

  // ── Subscription OAuth derived state (api_key step only) ──
  const apiKeyProvider =
    onboardingStep?.name === 'api_key' ? (onboardingStep.provider ?? '') : ''
  const supportsSub = !!onboardingStep?.supports_subscription_oauth && !!apiKeyProvider
  const subStatus = apiKeyProvider ? subscriptionOauth[apiKeyProvider] : undefined
  const isSubConnected = !!subStatus?.connected
  const isSubPending = apiKeyProvider ? !!subscriptionPending[apiKeyProvider] : false
  const subPasteback = apiKeyProvider ? subscriptionPasteback[apiKeyProvider] : undefined

  // Refresh the live subscription status whenever we land on a sub-capable
  // api_key step, and clear any stale paste-back code entry.
  useEffect(() => {
    if (supportsSub && apiKeyProvider) {
      socket.send('model_subscription_status', { provider: apiKeyProvider })
      setPastebackCode('')
      setShowKeyInput(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supportsSub, apiKeyProvider])

  const handleSubscriptionConnect = useCallback(() => {
    if (!apiKeyProvider) return
    dispatch(setSubscriptionPending({ provider: apiKeyProvider, pending: true }))
    // OpenAI uses a loopback callback (auto-redirect); xAI/Grok's flow ends on
    // a "copy this code" page, so it goes through the paste-back flow. Mirrors
    // the decision in the Settings model panel.
    const useLoopback = apiKeyProvider === 'openai'
    socket.send(
      useLoopback ? 'model_subscription_connect' : 'model_subscription_prepare',
      { provider: apiKeyProvider },
    )
  }, [apiKeyProvider, dispatch, socket])

  const canSubmit = (() => {
    if (!onboardingStep) return false
    if (onboardingLoading) return false
    if (onboardingStep.name === 'intro') return true  // Welcome screen - just advance
    if (isOllamaStep) {
      return ollamaConnected || (localLLM.phase === 'connected' && !!localLLM.testResult?.success)
    }
    if (isFormStep) return true  // Name steps are optional
    // A connected subscription authorizes the provider without an API key.
    if (isSubConnected) return true
    if (onboardingStep.options.length > 0) {
      return !!selectedValue
    }
    return onboardingStep.required ? textValue.trim().length > 0 : true
  })()

  // Loading
  if (!connected || (!onboardingStep && onboardingLoading)) {
    return (
      <div className={styles.container}>
        <div className={styles.content}>
          <div className={styles.loading}>
            <div className={styles.spinner} />
            <div className={styles.loadingText}>
              {!connected ? t('common:status.connecting') : t('common:status.loading')}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // ── Render step form ──────────────────────────────────────────────────────
  const renderStepForm = () => {
    if (!onboardingStep) return null

    // Intro/welcome step - message only, no input.
    if (onboardingStep.name === 'intro') return null

    // Ollama local setup
    if (isOllamaStep) {
      return (
        <div className={styles.formGroup}>
          <OllamaSetup
            defaultUrl={ollamaUrl}
            onConnected={handleOllamaConnected}
          />
        </div>
      )
    }

    // Form step (the name steps - a single text field each)
    if (onboardingStep.form_fields && onboardingStep.form_fields.length > 0) {
      return (
        <div className={styles.formGroup}>
          <div className={styles.profileForm}>
            {onboardingStep.form_fields.map((field: OnboardingFormField) => (
              <div key={field.name} className={styles.formField}>
                {field.field_type === 'text' && (
                  <input
                    type="text"
                    className={styles.textInput}
                    aria-label={field.label}
                    value={formValues[field.name] ?? ''}
                    onChange={e => setFormValues(prev => ({ ...prev, [field.name]: e.target.value }))}
                    placeholder={field.placeholder || t('onboarding:form.enterField', { field: field.label.toLowerCase() })}
                    maxLength={20}
                    autoFocus
                    onKeyDown={e => { if (e.key === 'Enter' && canSubmit) handleSubmit() }}
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      )
    }

    // Option-based step: the provider list, shown as an iOS-style wheel picker.
    if (onboardingStep.options.length > 0) {
      return (
        <div className={styles.formGroup}>
          <ProviderWheel
            options={onboardingStep.options}
            value={selectedValue}
            onChange={setSelectedValue}
          />
        </div>
      )
    }

    // Text input step
    const isApiKey = onboardingStep.name === 'api_key'
    const isProxied = isApiKey && onboardingStep.provider != null && OR_PROXIED.includes(onboardingStep.provider)

    if (isProxied) {
      const providerDisplay = { moonshot: 'Moonshot', minimax: 'MiniMax' }[onboardingStep.provider!] ?? onboardingStep.provider
      const isViaOR = proxiedVia === 'openrouter'
      return (
        <div className={styles.formGroup}>
          <input
            type="password"
            className={`${styles.textInput} ${onboardingError ? styles.error : ''}`}
            value={textValue}
            onChange={e => setTextValue(e.target.value)}
            placeholder={isViaOR ? t('onboarding:proxied.orKey') : t('onboarding:proxied.directKey', { provider: providerDisplay })}
            autoFocus
            onKeyDown={e => { if (e.key === 'Enter' && canSubmit) handleSubmit() }}
          />
          <div className={styles.inputHint}>{t('onboarding:apiKey.storedLocally')}</div>
          {isViaOR && (
            <div style={{ marginTop: 14 }}>
              <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 500, marginBottom: 6 }}>
                <Trans
                  ns="onboarding"
                  i18nKey="proxied.modelLabel"
                  components={{ 1: <span style={{ fontWeight: 400, opacity: 0.6 }} /> }}
                />
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={orModel}
                onChange={e => setOrModel(e.target.value)}
                placeholder={OR_MODEL_DEFAULTS[onboardingStep.provider!] ?? 'e.g. moonshotai/kimi-k2.5'}
              />
            </div>
          )}
          <div style={{ marginTop: 12 }}>
            {isViaOR ? (
              <button
                type="button"
                onClick={() => { setProxiedVia('direct'); setTextValue('') }}
                style={{ background: 'none', border: 'none', color: 'var(--text-primary)', textDecoration: 'underline', cursor: 'pointer', fontSize: '0.82rem', padding: 0 }}
              >
                {t('onboarding:proxied.useDirect', { provider: providerDisplay })}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => { setProxiedVia('openrouter'); setTextValue('') }}
                style={{ background: 'none', border: 'none', color: 'var(--text-primary)', textDecoration: 'underline', cursor: 'pointer', fontSize: '0.82rem', padding: 0 }}
              >
                {t('onboarding:proxied.useOpenRouter')}
              </button>
            )}
          </div>
        </div>
      )
    }

    // Shared API-key input + hint (used by plain-key providers and the
    // collapsible fallback under a connected subscription).
    const identityLine = [subStatus?.email, subStatus?.plan].filter(Boolean).join(' · ')
    const keyInputBlock = (
      <>
        <input
          type={isApiKey ? 'password' : 'text'}
          className={`${styles.textInput} ${onboardingError ? styles.error : ''}`}
          value={textValue}
          onChange={e => setTextValue(e.target.value)}
          placeholder={isApiKey ? (isSubConnected ? t('onboarding:apiKey.optional') : t('onboarding:apiKey.enter')) : t('onboarding:form.enterName')}
          autoFocus={!supportsSub}
          onKeyDown={e => { if (e.key === 'Enter' && canSubmit) handleSubmit() }}
        />
        {isApiKey && (
          <div className={styles.inputHint}>{t('onboarding:apiKey.storedLocally')}</div>
        )}
      </>
    )

    const dividerRow = (label: string) => (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '18px 0 14px' }}>
        <div style={{ flex: 1, height: 1, background: 'var(--border-color, #333)' }} />
        <span style={{ fontSize: '0.75rem', letterSpacing: '0.04em', textTransform: 'uppercase', opacity: 0.5 }}>{label}</span>
        <div style={{ flex: 1, height: 1, background: 'var(--border-color, #333)' }} />
      </div>
    )

    // Non-subscription providers keep the plain input.
    if (!(isApiKey && supportsSub)) {
      return <div className={styles.formGroup}>{keyInputBlock}</div>
    }

    return (
      <div className={styles.formGroup}>
        {isSubConnected ? (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
              padding: '14px 16px',
              border: '1px solid var(--border-color, #333)',
              borderRadius: 10,
              background: 'var(--bg-elevated, rgba(255,255,255,0.03))',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 28,
                  height: 28,
                  borderRadius: '50%',
                  background: 'var(--success-bg, rgba(63,185,80,0.15))',
                  color: 'var(--success, #3fb950)',
                  flexShrink: 0,
                }}
              >
                <Check size={16} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>{t('common:status.connected')}</span>
                {identityLine && (
                  <span
                    style={{
                      fontSize: '0.8rem',
                      opacity: 0.6,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    title={identityLine}
                  >
                    {identityLine}
                  </span>
                )}
              </div>
            </div>
            <Button
              variant="ghost"
              disabled={isSubPending}
              onClick={() => {
                dispatch(setSubscriptionPending({ provider: apiKeyProvider, pending: true }))
                socket.send('model_subscription_disconnect', { provider: apiKeyProvider })
              }}
              style={{ flexShrink: 0 }}
            >
              {isSubPending ? t('onboarding:sub.working') : t('common:actions.disconnect')}
            </Button>
          </div>
        ) : subPasteback?.awaiting ? (
          <div>
            <input
              type="text"
              className={styles.textInput}
              placeholder={t('onboarding:sub.pastePlaceholder')}
              value={pastebackCode}
              onChange={e => setPastebackCode(e.target.value)}
              disabled={isSubPending}
              autoFocus
            />
            <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <Button
                variant="primary"
                disabled={isSubPending || !pastebackCode.trim()}
                onClick={() => {
                  dispatch(setSubscriptionPending({ provider: apiKeyProvider, pending: true }))
                  socket.send('model_subscription_complete', {
                    provider: apiKeyProvider,
                    code: pastebackCode.trim(),
                    attemptId: subPasteback?.attemptId,
                  })
                }}
              >
                {isSubPending ? t('onboarding:sub.submitting') : t('onboarding:sub.submitCode')}
              </Button>
              <Button
                variant="secondary"
                disabled={isSubPending}
                onClick={() => {
                  dispatch(clearSubscriptionPasteback(apiKeyProvider))
                  setPastebackCode('')
                }}
              >
                {t('common:actions.cancel')}
              </Button>
              {subPasteback?.authUrl && (
                <a href={subPasteback.authUrl} target="_blank" rel="noreferrer" style={{ fontSize: '0.82rem', textDecoration: 'underline' }}>
                  {t('onboarding:sub.reopen')}
                </a>
              )}
            </div>
            {subPasteback?.errorMessage && (
              <div style={{ color: 'var(--error, #e5484d)', fontSize: '0.82rem', marginTop: 8 }}>{subPasteback.errorMessage}</div>
            )}
          </div>
        ) : (
          <Button
            variant="primary"
            fullWidth
            disabled={isSubPending}
            onClick={handleSubscriptionConnect}
          >
            {isSubPending ? t('onboarding:sub.openingBrowser') : (onboardingStep.subscription_label || t('onboarding:sub.signInWith', { provider: apiKeyProvider }))}
          </Button>
        )}

        {/* API-key fallback. Collapsed behind a link once connected so the
            connected card stands alone; always shown otherwise. */}
        {isSubConnected && !showKeyInput ? (
          <div style={{ textAlign: 'center', marginTop: 14 }}>
            <button
              type="button"
              onClick={() => setShowKeyInput(true)}
              style={{ background: 'none', border: 'none', color: 'var(--text-secondary, #999)', textDecoration: 'underline', cursor: 'pointer', fontSize: '0.82rem', padding: 0 }}
            >
              {t('onboarding:sub.useKeyInstead')}
            </button>
          </div>
        ) : (
          <>
            {dividerRow(t('onboarding:apiKey.orEnterKey'))}
            {keyInputBlock}
          </>
        )}
      </div>
    )
  }

  return (
    <div className={styles.container}>
      {/* Main Content */}
      <div className={styles.content}>
        {onboardingStep && (
          <div className={styles.wizard}>
            <div className={styles.topRow}>
              <OnboardingMascot stepIndex={onboardingStep.index} outroPhase={outroPhase} />
              {/* Keyed by step so the content remounts and replays the
                  fade-in each time the step changes. */}
              <div
                key={onboardingStep.index}
                className={`${styles.card} ${outroFading ? styles.outroFade : ''}`}
              >
              {isFinishing ? (
                <div className={styles.doneMessage}>
                  <Trans
                    ns="onboarding"
                    i18nKey="done.message"
                    components={{ 1: <strong /> }}
                    values={{ name: finishing?.agentName }}
                  />
                </div>
              ) : (
                <>
              {onboardingStep.name === 'intro' ? (
                <div className={styles.introMessage}>
                  <p>
                    <Trans
                      ns="onboarding"
                      i18nKey="intro.greeting"
                      components={{ 1: <strong />, 2: <br /> }}
                    />
                  </p>
                  <p className={styles.introKicker}>
                    {t('onboarding:intro.kicker')}
                  </p>
                </div>
              ) : (
                <h2 className={styles.stepPrompt}>
                  {isOllamaStep ? (() => {
                    switch (localLLM.phase) {
                      case 'not_installed': return t('onboarding:ollamaPrompt.notInstalled')
                      case 'installing':    return t('onboarding:ollamaPrompt.installing')
                      case 'not_running':   return t('onboarding:ollamaPrompt.notRunning')
                      case 'starting':      return t('onboarding:ollamaPrompt.starting')
                      case 'running':       return t('onboarding:ollamaPrompt.running')
                      case 'selecting_model': return t('onboarding:ollamaPrompt.selectingModel')
                      case 'pulling_model': return t('onboarding:ollamaPrompt.pullingModel')
                      case 'connected': {
                        const n = localLLM.testResult?.models?.length ?? 0
                        return t('onboarding:ollamaPrompt.connected', { count: n })
                      }
                      case 'error':         return localLLM.error ?? t('onboarding:ollamaPrompt.errorFallback')
                      default:              return t('onboarding:ollamaPrompt.checking')
                    }
                  })() : (() => {
                    const isProxiedApiKey = onboardingStep.name === 'api_key' && onboardingStep.provider != null && OR_PROXIED.includes(onboardingStep.provider)
                    if (isProxiedApiKey && proxiedVia === 'openrouter') return t('onboarding:apiKeyPrompt.openrouter')
                    if (onboardingStep.name === 'api_key') {
                      const name = PROVIDER_NAMES[apiKeyProvider] ?? t('onboarding:apiKeyPrompt.providerFallback')
                      return supportsSub
                        ? t('onboarding:apiKeyPrompt.withSub', { provider: name })
                        : t('onboarding:apiKeyPrompt.plain', { provider: name })
                    }
                    if (onboardingStep.name === 'provider') return t('onboarding:stepPrompt.provider')
                    if (onboardingStep.name === 'user_profile') return t('onboarding:stepPrompt.userProfile')
                    if (onboardingStep.name === 'agent_name') return t('onboarding:stepPrompt.agentName')
                    return onboardingStep.title
                  })()}
                </h2>
              )}

              {/* Error Message */}
              {onboardingError && (
                <div className={styles.errorMessage}>
                  <AlertCircle size={16} />
                  {onboardingError}
                </div>
              )}

              {/* Step Form */}
              {renderStepForm()}
                </>
              )}
              </div>
            </div>

            {/* Navigation row - spans under the mascot + form: dots on the
                left (below the mascot), Back + Next on the right. The dots and
                buttons fade out the moment finishing starts. */}
            <div className={`${styles.buttons} ${isFinishing ? styles.outroFade : ''}`}>
              <div className={styles.dots}>
                  {Array.from({ length: onboardingStep.total }).map((_, i) => (
                    <span
                      key={i}
                      className={`${styles.dot} ${i === onboardingStep.index ? styles.dotActive : ''}`}
                    />
                  ))}
                </div>
                <div className={styles.buttonsRight}>
                  {onboardingStep.index > 0 && (
                    <Button
                      variant="ghost"
                      onClick={handleBack}
                      disabled={onboardingLoading}
                      icon={<ChevronLeft size={18} />}
                      aria-label={t('common:actions.back')}
                    />
                  )}
                  {!onboardingStep.required && (
                    <Button variant="secondary" onClick={handleSkip} disabled={onboardingLoading} icon={<SkipForward size={16} />}>
                      {t('common:actions.skip')}
                    </Button>
                  )}
                  <Button
                    variant="primary"
                    onClick={handleSubmit}
                    disabled={!canSubmit}
                    loading={onboardingLoading}
                    icon={<ChevronRight size={16} />}
                    iconPosition="right"
                  >
                    {onboardingLoading && onboardingStep?.name === 'api_key'
                      ? (isOllamaStep ? t('common:status.connecting') : t('onboarding:nav.testingApiKey'))
                      : onboardingStep.name === 'intro' ? t('onboarding:nav.getStarted')
                      : isLastStep ? t('onboarding:nav.finish') : t('common:actions.next')}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
  )
}
