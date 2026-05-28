import React, { useEffect, useState, useCallback, useRef } from 'react'
import { getOllamaInstallPercent } from '../../utils/ollamaInstall'
import {
  Check,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  SkipForward,
  // Icons for Integrations and Skills
  Folder,
  Search,
  Github,
  Globe,
  FileText,
  MessageSquare,
  Mail,
  Calendar,
  CheckSquare,
  Gem,
  FlaskConical,
  Pencil,
  ClipboardList,
  Cloud,
  Sheet,
  Download,
  Play,
  Wifi,
  WifiOff,
  RefreshCw,
  Upload,
  Trash2,
  type LucideIcon,
} from 'lucide-react'
import { Button } from '../../components/ui'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { IntegrationsSettings } from '../Settings/IntegrationsSettings'
import type { OnboardingStep, OnboardingStepOption, OnboardingFormField } from '../../types'
import styles from './OnboardingPage.module.css'

// Icon mapping for dynamic rendering
const ICON_MAP: Record<string, LucideIcon> = {
  Folder,
  Search,
  Github,
  Globe,
  FileText,
  MessageSquare,
  Mail,
  Calendar,
  CheckSquare,
  Gem,
  FlaskConical,
  Pencil,
  ClipboardList,
  Cloud,
  Sheet,
}

const STEP_NAMES = ['Provider', 'API Key', 'Agent Name', 'User Profile', 'Skills', 'Integrations']

// ── Ollama local-setup component ─────────────────────────────────────────────

interface OllamaSetupProps {
  defaultUrl: string
  onConnected: (url: string) => void
}

function OllamaSetup({ defaultUrl, onConnected }: OllamaSetupProps) {
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
          <span>Checking if Ollama is running…</span>
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
          <span className={styles.ollamaStatusLabel}>Ollama is not installed</span>
        </div>
        <p className={styles.ollamaHint}>
          Ollama lets you run AI models locally — no cloud needed. We'll install it automatically for you.
        </p>
        <Button variant="primary" onClick={installLocalLLM} icon={<Download size={16} />}>
          Install Ollama
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
          <span className={styles.ollamaStatusLabel}>Installing Ollama…</span>
          <span className={styles.installPct}>{pct}%</span>
        </div>
        <div className={styles.installProgressBar}>
          <div className={styles.installProgressFill} style={{ width: `${pct}%` }} />
        </div>
        <div className={styles.installLog}>
          {installProgress.length === 0 && <span className={styles.installLogLine}>Starting…</span>}
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
          <span className={styles.ollamaStatusLabel}>Ollama is installed but not running</span>
        </div>
        <p className={styles.ollamaHint}>Click below to start the Ollama server.</p>
        <Button variant="primary" onClick={startLocalLLM} icon={<Play size={16} />}>
          Start Ollama
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
          <span className={styles.ollamaStatusLabel}>Starting Ollama…</span>
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
          <span className={styles.ollamaStatusLabel}>Something went wrong</span>
        </div>
        {error && <p className={styles.ollamaHint}>{error}</p>}
        <Button variant="secondary" onClick={checkLocalLLM} icon={<RefreshCw size={16} />}>
          Retry
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
          <span className={styles.ollamaStatusLabel}>Ollama is running — no models yet</span>
        </div>
        <p className={styles.ollamaHint}>Select a model to download so you can start chatting:</p>
        <input
          className={styles.modelSearchInput}
          type="text"
          placeholder="Find model..."
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
              {m.recommended && <span className={styles.modelOptionBadge}>Recommended</span>}
            </label>
          ))}
          {filteredModels.length === 0 && (
            <p className={styles.ollamaHint}>No models match "{modelSearch}"</p>
          )}
        </div>
        <Button variant="primary" onClick={() => pullOllamaModel(selectedModel)} disabled={!selectedModel} icon={<Download size={16} />}>
          Download {selectedModel || 'Model'}
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
    const latestStatus = localLLM.pullProgress[localLLM.pullProgress.length - 1] ?? 'Starting download…'
    return (
      <div className={styles.ollamaBox}>
        <div className={styles.ollamaStatusRow}>
          <div className={styles.spinnerSmall} />
          <span className={styles.ollamaStatusLabel}>Downloading {selectedModel}…</span>
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

  // ── Running — show URL field + test button ──
  const connected = phase === 'connected' && testResult?.success

  return (
    <div className={styles.ollamaBox}>
      <div className={styles.ollamaStatusRow}>
        {connected
          ? <Wifi size={18} className={styles.iconSuccess} />
          : <Wifi size={18} className={styles.iconMuted} />}
        <span className={styles.ollamaStatusLabel}>
          {connected ? 'Connected to Ollama' : 'Ollama is running'}
        </span>
      </div>

      {connected && testResult?.message && (
        <p className={styles.ollamaSuccessMsg}>{testResult.message}</p>
      )}

      {!connected && (
        <>
          <label className={styles.ollamaLabel}>Ollama server URL</label>
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
              Test
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

// ── Main onboarding page ──────────────────────────────────────────────────────

export function OnboardingPage() {
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
    agentProfilePictureUrl,
    agentProfilePictureHasCustom,
    uploadAgentProfilePicture,
    removeAgentProfilePicture,
  } = useWebSocket()

  // Providers that route through OpenRouter — model slug is configurable.
  const OR_PROXIED = ['moonshot', 'minimax']
  const OR_MODEL_DEFAULTS: Record<string, string> = {
    moonshot: 'moonshotai/kimi-k2.5',
    minimax: 'minimax/minimax-01',
  }

  // Local form state
  const [selectedValue, setSelectedValue] = useState<string | string[]>('')
  const [textValue, setTextValue] = useState('')
  const [orModel, setOrModel] = useState('')
  // For proxied providers: 'direct' tries the native API, 'openrouter' routes via OR.
  const [proxiedVia, setProxiedVia] = useState<'direct' | 'openrouter'>('direct')
  // URL submitted from OllamaSetup
  const [ollamaUrl, setOllamaUrl] = useState('http://localhost:11434')
  const [ollamaConnected, setOllamaConnected] = useState(false)
  // Form step state (for user_profile and similar multi-field steps)
  const [formValues, setFormValues] = useState<Record<string, string | string[]>>({})
  // Picture upload state (for image_upload fields)
  const [pictureUploading, setPictureUploading] = useState(false)
  const [pictureError, setPictureError] = useState<string | null>(null)
  const pictureInputRef = useRef<HTMLInputElement | null>(null)

  // Reset picture-upload feedback when transitioning between steps
  useEffect(() => {
    setPictureUploading(false)
    setPictureError(null)
  }, [onboardingStep?.name])

  // Clear uploading spinner once the context reflects the new picture
  useEffect(() => {
    if (pictureUploading) {
      setPictureUploading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentProfilePictureUrl])

  // Safety: clear the spinner after a short timeout even if no ack arrives
  // (e.g., on a failed upload that did not update the context URL).
  useEffect(() => {
    if (!pictureUploading) return
    const t = window.setTimeout(() => setPictureUploading(false), 10000)
    return () => window.clearTimeout(t)
  }, [pictureUploading])

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

      // Form step (e.g., user_profile, agent_name)
      // Preserve existing values when navigating back — only set defaults for missing fields
      if (onboardingStep.form_fields && onboardingStep.form_fields.length > 0) {
        setFormValues(prev => {
          const defaults: Record<string, string | string[]> = {}
          for (const field of onboardingStep.form_fields) {
            defaults[field.name] = prev[field.name] ?? (field.default ?? '')
          }
          return defaults
        })
      } else if (onboardingStep.name === 'skills') {
        setSelectedValue(Array.isArray(onboardingStep.default) ? onboardingStep.default : [])
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

  const handlePictureSelect = useCallback(() => {
    pictureInputRef.current?.click()
  }, [])

  const handlePictureChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>, fieldName: string) => {
      const file = e.target.files?.[0]
      e.target.value = ''
      if (!file) return

      setPictureError(null)
      setPictureUploading(true)

      const reader = new FileReader()
      reader.onload = () => {
        const result = reader.result as string
        const base64 = result.includes(',') ? result.split(',', 2)[1] : result
        // Mark this form field as "has picture" using the file extension
        const ext = (file.name.split('.').pop() || '').toLowerCase()
        setFormValues(prev => ({ ...prev, [fieldName]: ext }))
        uploadAgentProfilePicture(file.name, file.type || 'application/octet-stream', base64)
      }
      reader.onerror = () => {
        setPictureUploading(false)
        setPictureError('Could not read file')
      }
      reader.readAsDataURL(file)
    },
    [uploadAgentProfilePicture]
  )

  const handlePictureRemove = useCallback(
    (fieldName: string) => {
      setPictureError(null)
      setFormValues(prev => ({ ...prev, [fieldName]: '' }))
      removeAgentProfilePicture()
    },
    [removeAgentProfilePicture]
  )

  const handleOptionSelect = useCallback((value: string) => {
    if (!onboardingStep) return
    if (onboardingStep.name === 'skills') {
      setSelectedValue(prev => {
        const arr = Array.isArray(prev) ? prev : []
        return arr.includes(value) ? arr.filter(v => v !== value) : [...arr, value]
      })
    } else {
      setSelectedValue(value)
    }
  }, [onboardingStep])

  const handleSubmit = useCallback(() => {
    if (!onboardingStep) return
    const isOllamaStep = onboardingStep.name === 'api_key' && onboardingStep.provider === 'remote'
    const isProxiedStep = onboardingStep.name === 'api_key' &&
      onboardingStep.provider != null && OR_PROXIED.includes(onboardingStep.provider)

    if (isOllamaStep) {
      submitOnboardingStep(ollamaUrl)
    } else if (isProxiedStep) {
      submitOnboardingStep({ api_key: textValue, via: proxiedVia, or_model: proxiedVia === 'openrouter' ? orModel : '' })
    } else if (onboardingStep.name === 'integrations') {
      // Panel step — the embedded IntegrationsSettings handles its own
      // connect flows. Just advance.
      submitOnboardingStep('')
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

  const isMultiSelect = onboardingStep?.name === 'skills'
  const isIntegrationsStep = onboardingStep?.name === 'integrations'
  const isFormStep = !!(onboardingStep?.form_fields && onboardingStep.form_fields.length > 0)
  const isWideStep = isMultiSelect || isFormStep || isIntegrationsStep
  const isLastStep = onboardingStep ? onboardingStep.index === onboardingStep.total - 1 : false

  const isOllamaStep =
    onboardingStep?.name === 'api_key' && onboardingStep?.provider === 'remote'

  const canSubmit = (() => {
    if (!onboardingStep) return false
    if (onboardingLoading) return false
    if (isOllamaStep) {
      return ollamaConnected || (localLLM.phase === 'connected' && !!localLLM.testResult?.success)
    }
    if (isIntegrationsStep) return true  // Connection is optional — Next always works
    if (isFormStep) return true  // All form fields are optional
    if (onboardingStep.options.length > 0) {
      return isMultiSelect ? true : !!selectedValue
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
              {!connected ? 'Connecting...' : 'Loading...'}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // ── Render step form ──────────────────────────────────────────────────────
  const renderStepForm = () => {
    if (!onboardingStep) return null

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

    // External app integrations — embed the full Settings → Integrations
    // panel so the user can connect any integration in place.
    if (isIntegrationsStep) {
      return (
        <div className={`${styles.formGroup} ${styles.integrationsPanel}`}>
          <IntegrationsSettings hideHeader />
        </div>
      )
    }

    // Agent Identity step — compact side-by-side layout (avatar + name)
    if (
      onboardingStep.name === 'agent_name' &&
      onboardingStep.form_fields &&
      onboardingStep.form_fields.length > 0
    ) {
      const nameField = onboardingStep.form_fields.find(f => f.field_type === 'text')
      const avatarField = onboardingStep.form_fields.find(f => f.field_type === 'image_upload')

      return (
        <div className={styles.formGroup}>
          <div className={styles.identityCard}>
            {avatarField && (
              <div className={styles.identityAvatar}>
                <img
                  src={agentProfilePictureUrl}
                  alt=""
                  className={styles.imageUploadPreview}
                />
                <input
                  ref={pictureInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  onChange={(e) => handlePictureChange(e, avatarField.name)}
                  style={{ display: 'none' }}
                />
              </div>
            )}
            <div className={styles.identityDetails}>
              {nameField && (
                <>
                  <label className={styles.formFieldLabel}>{nameField.label}</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={(formValues[nameField.name] as string) ?? ''}
                    onChange={(e) =>
                      setFormValues((prev) => ({ ...prev, [nameField.name]: e.target.value }))
                    }
                    placeholder={nameField.placeholder || 'Enter a name'}
                  />
                </>
              )}
              {avatarField && (
                <div className={styles.identityAvatarActions}>
                  <Button
                    variant="secondary"
                    onClick={handlePictureSelect}
                    disabled={pictureUploading}
                    icon={<Upload size={14} />}
                  >
                    {pictureUploading ? 'Uploading...' : 'Upload avatar'}
                  </Button>
                  {agentProfilePictureHasCustom && (
                    <Button
                      variant="secondary"
                      onClick={() => handlePictureRemove(avatarField.name)}
                      disabled={pictureUploading}
                      icon={<Trash2 size={14} />}
                    >
                      Remove
                    </Button>
                  )}
                </div>
              )}
              {pictureError && (
                <div className={styles.imageUploadError}>{pictureError}</div>
              )}
            </div>
          </div>
        </div>
      )
    }

    // Form step (multi-field form, e.g., user_profile)
    if (onboardingStep.form_fields && onboardingStep.form_fields.length > 0) {
      return (
        <div className={styles.formGroup}>
          <div className={styles.profileForm}>
            {onboardingStep.form_fields.map((field: OnboardingFormField) => (
              <div key={field.name} className={styles.formField}>
                <label className={styles.formFieldLabel}>{field.label}</label>

                {field.field_type === 'text' && (
                  <input
                    type="text"
                    className={styles.textInput}
                    value={(formValues[field.name] as string) ?? ''}
                    onChange={e => setFormValues(prev => ({ ...prev, [field.name]: e.target.value }))}
                    placeholder={field.placeholder || `Enter ${field.label.toLowerCase()}`}
                  />
                )}

                {field.field_type === 'select' && field.options.length > 20 ? (
                  /* Large option list (e.g., languages) — use native dropdown */
                  <>
                    <select
                      className={styles.formDropdown}
                      value={(formValues[field.name] as string) ?? ''}
                      onChange={e => setFormValues(prev => ({ ...prev, [field.name]: e.target.value }))}
                    >
                      {field.options.map(opt => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}{opt.description && opt.description !== opt.label ? ` (${opt.description})` : ''}
                        </option>
                      ))}
                    </select>
                    {field.placeholder && (
                      <div className={styles.formFieldHint}>{field.placeholder}</div>
                    )}
                  </>
                ) : field.field_type === 'select' ? (() => {
                  const hasDescriptions = field.options.some(o => o.description && o.description !== o.label)
                  if (hasDescriptions) {
                    /* Options with descriptions — vertical stack */
                    return (
                      <div className={styles.formSelectVertical}>
                        {field.options.map(opt => {
                          const isSelected = formValues[field.name] === opt.value
                          return (
                            <div
                              key={opt.value}
                              className={`${styles.formSelectOptionVertical} ${isSelected ? styles.selected : ''}`}
                              onClick={() => setFormValues(prev => ({ ...prev, [field.name]: opt.value }))}
                            >
                              <div className={styles.optionRadio} />
                              <span className={styles.formSelectLabel}>{opt.label}</span>
                              {opt.description && opt.description !== opt.label && (
                                <span className={styles.formSelectDesc}>{opt.description}</span>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )
                  }
                  /* Simple options without descriptions — inline row */
                  return (
                    <div className={styles.formSelectInline}>
                      {field.options.map(opt => {
                        const isSelected = formValues[field.name] === opt.value
                        return (
                          <div
                            key={opt.value}
                            className={`${styles.formSelectOptionInline} ${isSelected ? styles.selected : ''}`}
                            onClick={() => setFormValues(prev => ({ ...prev, [field.name]: opt.value }))}
                          >
                            <div className={styles.optionRadio} />
                            <span className={styles.formSelectLabel}>{opt.label}</span>
                          </div>
                        )
                      })}
                    </div>
                  )
                })() : null}

                {field.field_type === 'image_upload' && (
                  <div className={styles.imageUploadRow}>
                    <img
                      src={agentProfilePictureUrl}
                      alt=""
                      className={styles.imageUploadPreview}
                    />
                    <div className={styles.imageUploadActions}>
                      <input
                        ref={pictureInputRef}
                        type="file"
                        accept="image/png,image/jpeg,image/webp,image/gif"
                        onChange={(e) => handlePictureChange(e, field.name)}
                        style={{ display: 'none' }}
                      />
                      <Button
                        variant="secondary"
                        onClick={handlePictureSelect}
                        disabled={pictureUploading}
                        icon={<Upload size={14} />}
                      >
                        {pictureUploading ? 'Uploading...' : 'Upload'}
                      </Button>
                      {agentProfilePictureHasCustom && (
                        <Button
                          variant="secondary"
                          onClick={() => handlePictureRemove(field.name)}
                          disabled={pictureUploading}
                          icon={<Trash2 size={14} />}
                        >
                          Remove
                        </Button>
                      )}
                    </div>
                    {pictureError && (
                      <div className={styles.imageUploadError}>{pictureError}</div>
                    )}
                  </div>
                )}

                {field.field_type === 'multi_checkbox' && (
                  <div className={styles.formCheckboxGroup}>
                    {field.options.map(opt => {
                      const checked = Array.isArray(formValues[field.name]) &&
                        (formValues[field.name] as string[]).includes(opt.value)
                      return (
                        <div
                          key={opt.value}
                          className={`${styles.formCheckboxItem} ${checked ? styles.selected : ''}`}
                          onClick={() => {
                            setFormValues(prev => {
                              const current = Array.isArray(prev[field.name]) ? (prev[field.name] as string[]) : []
                              const updated = current.includes(opt.value)
                                ? current.filter(v => v !== opt.value)
                                : [...current, opt.value]
                              return { ...prev, [field.name]: updated }
                            })
                          }}
                        >
                          <div className={styles.optionCheckbox}>
                            {checked && <Check size={12} />}
                          </div>
                          <span>{opt.label}</span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )
    }

    // Option-based step
    if (onboardingStep.options.length > 0) {
      return (
        <div className={styles.formGroup}>
          <div className={styles.optionsList}>
            {onboardingStep.options.map((option: OnboardingStepOption) => {
              const isSelected = isMultiSelect
                ? Array.isArray(selectedValue) && selectedValue.includes(option.value)
                : selectedValue === option.value

              return (
                <div
                  key={option.value}
                  className={`${styles.optionItem} ${isSelected ? styles.selected : ''}`}
                  onClick={() => handleOptionSelect(option.value)}
                >
                  <div className={isMultiSelect ? styles.optionCheckbox : styles.optionRadio}>
                    {isMultiSelect && isSelected && <Check size={12} />}
                  </div>
                  <div className={styles.optionContent}>
                    <div className={styles.optionLabel}>
                      {option.icon && ICON_MAP[option.icon] && (
                        <span className={styles.optionIcon}>
                          {React.createElement(ICON_MAP[option.icon], { size: 16 })}
                        </span>
                      )}
                      {option.label}
                      {option.requires_setup && (
                        <span className={styles.setupBadge}>Setup required</span>
                      )}
                    </div>
                    {option.description && (
                      <div className={styles.optionDescription}>{option.description}</div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
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
            placeholder={isViaOR ? 'Enter your OpenRouter API key' : `Enter your ${providerDisplay} API key`}
            autoFocus
            onKeyDown={e => { if (e.key === 'Enter' && canSubmit) handleSubmit() }}
          />
          <div className={styles.inputHint}>Your API key is stored locally.</div>
          {isViaOR && (
            <div style={{ marginTop: 14 }}>
              <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 500, marginBottom: 6 }}>
                Model <span style={{ fontWeight: 400, opacity: 0.6 }}>(optional — leave default or enter any OpenRouter slug)</span>
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
                ← Use direct {providerDisplay} API instead
              </button>
            ) : (
              <button
                type="button"
                onClick={() => { setProxiedVia('openrouter'); setTextValue('') }}
                style={{ background: 'none', border: 'none', color: 'var(--text-primary)', textDecoration: 'underline', cursor: 'pointer', fontSize: '0.82rem', padding: 0 }}
              >
                Having connection issues? Use OpenRouter instead →
              </button>
            )}
          </div>
        </div>
      )
    }

    return (
      <div className={styles.formGroup}>
        <input
          type={isApiKey ? 'password' : 'text'}
          className={`${styles.textInput} ${onboardingError ? styles.error : ''}`}
          value={textValue}
          onChange={e => setTextValue(e.target.value)}
          placeholder={isApiKey ? 'Enter your API key' : 'Enter a name'}
          maxLength={isApiKey ? undefined : 20}
          autoFocus
          onKeyDown={e => { if (e.key === 'Enter' && canSubmit) handleSubmit() }}
        />
        {isApiKey && (
          <div className={styles.inputHint}>Your API key is stored locally.</div>
        )}
      </div>
    )
  }

  return (
    <div className={styles.container}>
      {/* Progress Bar */}
      <div className={styles.progressBar}>
        {STEP_NAMES.map((name, index) => {
          const currentIndex = onboardingStep?.index ?? 0
          const isActive = index === currentIndex
          const isCompleted = index < currentIndex

          return (
            <React.Fragment key={name}>
              <div className={styles.stepIndicator}>
                <div className={`${styles.stepDot} ${isActive ? styles.active : ''} ${isCompleted ? styles.completed : ''}`}>
                  {isCompleted ? <Check size={14} /> : index + 1}
                </div>
                <span className={`${styles.stepLabel} ${isActive ? styles.active : ''}`}>{name}</span>
              </div>
              {index < STEP_NAMES.length - 1 && (
                <div className={`${styles.stepConnector} ${isCompleted ? styles.completed : ''} ${index === currentIndex - 1 ? styles.active : ''}`} />
              )}
            </React.Fragment>
          )
        })}
      </div>

      {/* Main Content */}
      <div className={styles.content}>
        <div className={`${styles.card} ${isWideStep ? styles.wide : ''}`}>
          {onboardingStep && (
            <>
              <h2 className={styles.stepTitle}>
                {(() => {
                  const isProxiedApiKey = onboardingStep.name === 'api_key' && onboardingStep.provider != null && OR_PROXIED.includes(onboardingStep.provider)
                  if (isProxiedApiKey && proxiedVia === 'openrouter') return 'Enter OpenRouter API Key'
                  return onboardingStep.title
                })()}
                {!onboardingStep.required && (
                  <span className={styles.optionalBadge}>Optional</span>
                )}
              </h2>
              <p className={styles.stepDescription}>
                {isOllamaStep ? (() => {
                  switch (localLLM.phase) {
                    case 'not_installed': return "Ollama isn't installed yet — we'll download and install it automatically."
                    case 'installing':    return "Installing Ollama on your machine. This may take a minute…"
                    case 'not_running':   return "Ollama is installed but not running. Click below to start the server."
                    case 'starting':      return "Starting the Ollama server…"
                    case 'running':       return "Ollama is running. Enter the server URL and test the connection."
                    case 'selecting_model': return "Ollama is connected but has no models yet. Pick one to download."
                    case 'pulling_model': return "Downloading your model — this may take a few minutes depending on size."
                    case 'connected': {
                      const n = localLLM.testResult?.models?.length ?? 0
                      return `Connected to Ollama — ${n} model${n === 1 ? '' : 's'} available.`
                    }
                    case 'error':         return localLLM.error ?? "Something went wrong. Check the error below and retry."
                    default:              return "Checking Ollama status…"
                  }
                })() : (() => {
                  const isProxiedApiKey = onboardingStep.name === 'api_key' && onboardingStep.provider != null && OR_PROXIED.includes(onboardingStep.provider)
                  if (isProxiedApiKey && proxiedVia === 'openrouter') {
                    const display = { moonshot: 'Moonshot (Kimi)', minimax: 'MiniMax' }[onboardingStep.provider!] ?? onboardingStep.provider
                    return `${display} models will be accessed via OpenRouter. Enter your OpenRouter API key — the model will be configured automatically. Get a free key at openrouter.ai`
                  }
                  return onboardingStep.description
                })()}
              </p>

              {/* Error Message */}
              {onboardingError && (
                <div className={styles.errorMessage}>
                  <AlertCircle size={16} />
                  {onboardingError}
                </div>
              )}

              {/* Step Form */}
              {renderStepForm()}

              {/* Navigation Buttons */}
              <div className={styles.buttons}>
                <div className={styles.buttonsLeft}>
                  {onboardingStep.index > 0 && (
                    <Button variant="ghost" onClick={handleBack} disabled={onboardingLoading} icon={<ChevronLeft size={16} />}>
                      Back
                    </Button>
                  )}
                </div>
                <div className={styles.buttonsRight}>
                  {!onboardingStep.required && (
                    <Button variant="secondary" onClick={handleSkip} disabled={onboardingLoading} icon={<SkipForward size={16} />}>
                      Skip
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
                      ? (isOllamaStep ? 'Connecting…' : 'Testing API Key…')
                      : isLastStep ? 'Finish' : 'Next'}
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
