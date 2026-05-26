import { useState, useEffect, useRef } from 'react'
import {
  Check,
  X,
  Loader2,
} from 'lucide-react'
import { Button, Badge } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  setProvider as setModelProvider,
  setCurrentLlmModel,
  setCurrentVlmModel,
  setSlowModeEnabled,
  setOllamaModels,
} from '../../store/slices/modelSettingsSlice'
import {
  selectModelProviders,
  selectModelProvider,
  selectApiKeys,
  selectBaseUrls,
  selectCurrentLlmModel as selectCurrentLlmModelSel,
  selectCurrentVlmModel as selectCurrentVlmModelSel,
  selectSlowModeEnabled,
  selectOllamaModels,
  selectOllamaAvailable,
  selectModelHasLoadedProviders,
  selectModelHasLoadedSettings,
  selectModelHasLoadedSlowMode,
} from '../../store/selectors/modelSettings'
import { getOllamaInstallPercent } from '../../utils/ollamaInstall'
import {
  OpenRouterModelPicker,
  OpenRouterCreditsBanner,
  useOpenRouterCatalog,
} from './OpenRouterModelPicker'

// Types
interface ProviderInfo {
  id: string
  name: string
  requires_api_key: boolean
  api_key_env?: string
  base_url_env?: string
  llm_model: string | null
  vlm_model: string | null
  has_vlm: boolean
  supports_catalog?: boolean
}

interface ApiKeyStatus {
  has_key: boolean
  masked_key: string
}

interface TestResult {
  success: boolean
  message: string
  error?: string
  models?: string[]
}

interface SuggestedModel {
  name: string
  label: string
  size: string
  recommended: boolean
}

export function ModelSettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const { showToast } = useToast()
  const dispatch = useAppDispatch()
  const hasInitialized = useRef(false)

  // Slice-backed (modelSettingsSlice) — cached across tab remounts.
  const providers = useAppSelector(selectModelProviders)
  const provider = useAppSelector(selectModelProvider)
  const apiKeys = useAppSelector(selectApiKeys)
  const baseUrls = useAppSelector(selectBaseUrls)
  const currentLlmModel = useAppSelector(selectCurrentLlmModelSel)
  const currentVlmModel = useAppSelector(selectCurrentVlmModelSel)
  const slowModeEnabled = useAppSelector(selectSlowModeEnabled)
  const ollamaModels = useAppSelector(selectOllamaModels)
  const ollamaAvailable = useAppSelector(selectOllamaAvailable)
  const hasLoadedProviders = useAppSelector(selectModelHasLoadedProviders)
  const hasLoadedSettings = useAppSelector(selectModelHasLoadedSettings)
  const hasLoadedSlowMode = useAppSelector(selectModelHasLoadedSlowMode)
  const isLoading = !hasLoadedProviders
  const isLoadingSlowMode = !hasLoadedSlowMode

  // Local setters (write-through to slice for any code that used to call setX directly).
  const setProvider = (p: string) => dispatch(setModelProvider(p))

  // Form state (transient — local).
  const [newApiKey, setNewApiKey] = useState('')
  const [newBaseUrl, setNewBaseUrl] = useState('')
  const [newLlmModel, setNewLlmModel] = useState('')
  const [newVlmModel, setNewVlmModel] = useState('')

  // UI state (transient — local).
  const [isSaving, setIsSaving] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [testBeforeSave, setTestBeforeSave] = useState(false)

  // Ollama list loading flag (transient). Models + availability are slice-backed.
  const [ollamaModelsLoading, setOllamaModelsLoading] = useState(false)

  // Ollama auto-install state
  const [ollamaInstallPhase, setOllamaInstallPhase] = useState<'idle' | 'installing' | 'error'>('idle')
  const [ollamaInstallLog, setOllamaInstallLog] = useState<string[]>([])
  const [ollamaInstallError, setOllamaInstallError] = useState('')

  // Ollama model download state
  const [pullPhase, setPullPhase] = useState<'idle' | 'selecting' | 'pulling'>('idle')
  const [suggestedModels, setSuggestedModels] = useState<SuggestedModel[]>([])
  const [selectedPullModel, setSelectedPullModel] = useState('')
  const [modelSearch, setModelSearch] = useState('')
  const [pullBytes, setPullBytes] = useState<{ completed: number; total: number; percent: number } | null>(null)
  const [pullStatus, setPullStatus] = useState('')

  // OpenRouter catalog — fetched once on first OpenRouter selection,
  // shared between the LLM and VLM pickers below.
  const orCatalog = useOpenRouterCatalog(
    send,
    onMessage,
    isConnected,
    provider === 'openrouter',
    newBaseUrl || baseUrls['openrouter'] || undefined,
  )

  const fmtBytes = (n: number) => {
    if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(1)} GB`
    if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(0)} MB`
    return `${(n / 1024).toFixed(0)} KB`
  }

  // Side-effect message handlers (toasts, loading flag flips, follow-up
  // sends). Slice-owned state is updated by modelSettingsSlice via the
  // registry — those duplicate paths are removed here.
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      onMessage('model_settings_get', () => {
        if (!hasInitialized.current) {
          setNewLlmModel('')
          setNewVlmModel('')
          hasInitialized.current = true
        }
      }),
      onMessage('model_settings_update', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        setIsSaving(false)
        if (d.success) {
          setNewApiKey('')
          setNewBaseUrl('')
          setNewLlmModel('')
          setNewVlmModel('')
          setHasChanges(false)
          showToast('success', 'Settings saved')
        } else {
          showToast('error', d.error || 'Failed to save')
        }
      }),
      onMessage('model_connection_test', (data: unknown) => {
        const d = data as { success: boolean; message: string; error?: string; models?: string[] }
        setIsTesting(false)
        setTestResult({
          success: d.success,
          message: d.message,
          error: d.error,
          models: d.models,
        })

        if (testBeforeSave && d.success) {
          setTestBeforeSave(false)
          setIsSaving(true)
          send('model_settings_update', {
            llmProvider: provider,
            vlmProvider: provider,
            llmModel: newLlmModel || currentLlmModel || undefined,
            vlmModel: newVlmModel || currentVlmModel || undefined,
            apiKey: newApiKey || undefined,
            providerForKey: newApiKey ? provider : undefined,
            baseUrl: newBaseUrl || undefined,
            providerForUrl: newBaseUrl ? provider : undefined,
          })
        } else if (testBeforeSave && !d.success) {
          setTestBeforeSave(false)
        }
      }),
      onMessage('ollama_models_get', (data: unknown) => {
        const d = data as { success: boolean; models: string[] }
        setOllamaModelsLoading(false)
        if (d.success && d.models && d.models.length > 0) {
          // Auto-select first available model if current selection isn't installed
          setNewLlmModel(prev => {
            const effective = prev || currentLlmModel
            if (!d.models.includes(effective)) {
              setHasChanges(true)
              return d.models[0]
            }
            return prev
          })
          setNewVlmModel(prev => {
            const effective = prev || currentVlmModel
            if (!d.models.includes(effective)) {
              setHasChanges(true)
              return d.models[0]
            }
            return prev
          })
        }
      }),
      onMessage('local_llm_suggested_models', (data: unknown) => {
        const d = data as { models: SuggestedModel[] }
        setSuggestedModels(d.models || [])
        const rec = d.models?.find(m => m.recommended)
        if (rec) setSelectedPullModel(rec.name)
      }),
      onMessage('local_llm_pull_progress', (data: unknown) => {
        const d = data as { message: string; total: number; completed: number; percent: number }
        setPullStatus(d.message || '')
        if (d.total > 0) setPullBytes({ completed: d.completed, total: d.total, percent: d.percent })
      }),
      onMessage('local_llm_pull_model', (data: unknown) => {
        const d = data as { success: boolean; model?: string; error?: string }
        if (d.success) {
          setPullPhase('idle')
          setPullBytes(null)
          setPullStatus('')
          const pulledModel = d.model || selectedPullModel
          // Refresh model list in UI
          setOllamaModelsLoading(true)
          send('ollama_models_get', { baseUrl: newBaseUrl || baseUrls['remote'] || undefined })
          // Auto-switch to remote provider with the pulled model and save immediately
          // so chat/tasks start using the local model without requiring manual save
          dispatch(setModelProvider('remote'))
          setNewLlmModel(pulledModel)
          setIsSaving(true)
          send('model_settings_update', {
            llmProvider: 'remote',
            vlmProvider: 'remote',
            llmModel: pulledModel,
            vlmModel: pulledModel,
            ...(newBaseUrl ? { baseUrl: newBaseUrl, providerForUrl: 'remote' } : {}),
          })
          showToast('success', `Model ${pulledModel} downloaded — switching to local model`)
        } else {
          setPullPhase('idle')
          showToast('error', d.error || 'Model download failed')
        }
      }),
      onMessage('slow_mode_set', (data: unknown) => {
        const d = data as { success: boolean; enabled: boolean; error?: string }
        if (d.success) {
          showToast('success', `Slow mode ${d.enabled ? 'enabled' : 'disabled'}`)
        } else {
          showToast('error', d.error || 'Failed to update slow mode')
        }
      }),
      onMessage('local_llm_install_progress', (data: unknown) => {
        const d = data as { message: string }
        if (d.message) setOllamaInstallLog(prev => [...prev, d.message])
      }),
      onMessage('local_llm_install', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        if (d.success) {
          setOllamaInstallPhase('idle')
          setOllamaInstallLog([])
          // Re-check if Ollama is now reachable
          setOllamaModelsLoading(true)
          send('ollama_models_get', { baseUrl: newBaseUrl || baseUrls['remote'] || undefined })
        } else {
          setOllamaInstallPhase('error')
          setOllamaInstallError(d.error || 'Installation failed')
        }
      }),
    ]

    return () => cleanups.forEach(cleanup => cleanup())
  }, [isConnected, onMessage, send, dispatch, testBeforeSave, provider, newApiKey, newBaseUrl, baseUrls, selectedPullModel, currentLlmModel, currentVlmModel, showToast])

  // Load initial data only once when connected, cached across remounts.
  useEffect(() => {
    if (!isConnected) return
    if (!hasLoadedProviders) send('model_providers_get')
    if (!hasLoadedSettings) send('model_settings_get')
    if (!hasLoadedSlowMode) send('slow_mode_get')
  }, [isConnected, send, hasLoadedProviders, hasLoadedSettings, hasLoadedSlowMode])

  // Fetch Ollama models whenever the active provider is 'remote'
  useEffect(() => {
    if (!isConnected || provider !== 'remote') return
    setOllamaModelsLoading(true)
    send('ollama_models_get', { baseUrl: baseUrls['remote'] || undefined })
  }, [provider, isConnected, send, baseUrls])

  const currentProvider = providers.find(p => p.id === provider)
  const hasKey = apiKeys[provider]?.has_key || newApiKey.length > 0
  const needsKey = currentProvider?.requires_api_key && !hasKey

  // Update models when provider changes — only before settings have loaded (fallback to
  // registry defaults for the initial render).  After hasInitialized is true, provider
  // changes are handled explicitly in handleProviderChange so we don't race against
  // the model_settings_get response overwriting the saved model.
  useEffect(() => {
    if (hasInitialized.current) return
    const selectedProvider = providers.find(p => p.id === provider)
    if (selectedProvider && !newLlmModel && !currentLlmModel) {
      dispatch(setCurrentLlmModel(selectedProvider.llm_model || ''))
    }
    if (selectedProvider && !newVlmModel && !currentVlmModel) {
      dispatch(setCurrentVlmModel(selectedProvider.vlm_model || ''))
    }
  }, [provider, providers, newLlmModel, newVlmModel, currentLlmModel, currentVlmModel, dispatch])

  const handleProviderChange = (newProvider: string) => {
    setProvider(newProvider)
    setNewApiKey('')
    setNewBaseUrl('')
    setNewLlmModel('')
    setNewVlmModel('')
    setHasChanges(true)
    // Reset Ollama install state when switching providers
    setOllamaInstallPhase('idle')
    setOllamaInstallLog([])
    setOllamaInstallError('')
    // Immediately set model to registry default for new provider so the field
    // shows a sensible value before the user types anything.
    const selectedProvider = providers.find(p => p.id === newProvider)
    dispatch(setCurrentLlmModel(selectedProvider?.llm_model || ''))
    dispatch(setCurrentVlmModel(selectedProvider?.vlm_model || ''))
  }

  const handleTestConnection = () => {
    setIsTesting(true)
    // Send the user's actual model so the test exercises it; otherwise a
    // typo passes the test (auth-only) and only fails at first real call.
    send('model_connection_test', {
      provider,
      apiKey: newApiKey || undefined,
      baseUrl: newBaseUrl || baseUrls[provider],
      model: newLlmModel || currentLlmModel || undefined,
    })
  }

  const handleSave = () => {
    const isChangingApiKey = newApiKey.length > 0
    const isChangingBaseUrl = newBaseUrl.length > 0

    if (isChangingApiKey || isChangingBaseUrl) {
      setTestBeforeSave(true)
      setIsTesting(true)
      send('model_connection_test', {
        provider,
        apiKey: newApiKey || undefined,
        baseUrl: newBaseUrl || baseUrls[provider],
        model: newLlmModel || currentLlmModel || undefined,
      })
    } else {
      setIsSaving(true)
      send('model_settings_update', {
        llmProvider: provider,
        vlmProvider: provider,
        llmModel: newLlmModel || currentLlmModel || undefined,
        vlmModel: newVlmModel || currentVlmModel || undefined,
      })
    }
  }

  const handleDownloadModelClick = () => {
    setPullPhase('selecting')
    setPullBytes(null)
    setPullStatus('')
    setModelSearch('')
    if (suggestedModels.length === 0) {
      send('local_llm_suggested_models')
    }
  }

  const handleStartPull = () => {
    if (!selectedPullModel) return
    setPullPhase('pulling')
    send('local_llm_pull_model', { model: selectedPullModel, baseUrl: newBaseUrl || baseUrls['remote'] || undefined })
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>Model Configuration</h3>
        <p>Configure AI provider and API key</p>
      </div>

      {isLoading ? (
        <div className={styles.loadingState}>
          <Loader2 size={20} className={styles.spinning} />
          <span>Loading...</span>
        </div>
      ) : (
        <div className={styles.settingsForm}>
          {/* Provider Selection */}
          <div className={styles.formGroup}>
            <label>Provider</label>
            <select value={provider} onChange={(e) => handleProviderChange(e.target.value)}>
              {providers.map(p => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>

          {/* Model Configuration */}
          {currentProvider && (
            <>
              {provider === 'openrouter' && currentProvider.supports_catalog ? (
                <OpenRouterModelPicker
                  models={orCatalog.models}
                  loading={orCatalog.loading}
                  error={orCatalog.error}
                  onRefresh={orCatalog.refresh}
                  label="LLM Model"
                  value={newLlmModel || currentLlmModel || ''}
                  onChange={(v) => { setNewLlmModel(v); setHasChanges(true) }}
                />
              ) : (
                <div className={styles.formGroup}>
                  <label>LLM Model</label>
                  {provider === 'remote' && ollamaModels.length > 0 ? (
                    <select
                      value={newLlmModel || currentLlmModel || ''}
                      onChange={(e) => { setNewLlmModel(e.target.value); setHasChanges(true) }}
                    >
                      {ollamaModels.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={newLlmModel || currentLlmModel || ''}
                      onChange={(e) => { setNewLlmModel(e.target.value); setHasChanges(true) }}
                      placeholder={
                        provider === 'remote' && ollamaModelsLoading
                          ? 'Loading models...'
                          : currentLlmModel || 'Enter LLM model name...'
                      }
                    />
                  )}
                </div>
              )}

              {/* Download new Ollama model / Install Ollama */}
              {provider === 'remote' && (
                <div className={styles.ollamaDownloadSection}>
                  {/* Ollama not detected — show install flow */}
                  {!ollamaModelsLoading && ollamaAvailable === false && (
                    <div className={styles.ollamaInstallBanner}>
                      {/* idle: prompt to install */}
                      {ollamaInstallPhase === 'idle' && (
                        <>
                          <div className={styles.ollamaInstallText}>
                            <strong>Ollama not detected</strong>
                            <span>Install Ollama to run AI models locally — no cloud needed.</span>
                          </div>
                          <div className={styles.ollamaInstallActions}>
                            <button
                              className={styles.installOllamaBtn}
                              onClick={() => {
                                setOllamaInstallPhase('installing')
                                setOllamaInstallLog([])
                                send('local_llm_install')
                              }}
                            >
                              Install Ollama
                            </button>
                            <button
                              className={styles.retryOllamaBtn}
                              onClick={() => {
                                setOllamaModelsLoading(true)
                                dispatch(setOllamaModels({ models: [], available: false }))
                                send('ollama_models_get', { baseUrl: newBaseUrl || baseUrls['remote'] || undefined })
                              }}
                            >
                              Retry
                            </button>
                          </div>
                        </>
                      )}

                      {/* installing: progress bar + live log */}
                      {ollamaInstallPhase === 'installing' && (() => {
                        const pct = getOllamaInstallPercent(ollamaInstallLog)
                        return (
                          <div className={styles.ollamaInstallProgress}>
                            <div className={styles.ollamaInstallProgressHeader}>
                              <Loader2 size={14} className={styles.spinning} />
                              <strong>Installing Ollama…</strong>
                              <span className={styles.ollamaInstallPct}>{pct}%</span>
                            </div>
                            <div className={styles.ollamaInstallProgressBar}>
                              <div className={styles.ollamaInstallProgressFill} style={{ width: `${pct}%` }} />
                            </div>
                            <div className={styles.ollamaInstallLog}>
                              {ollamaInstallLog.length === 0
                                ? <span className={styles.ollamaInstallLogLine}>Starting…</span>
                                : ollamaInstallLog.map((line, i) => (
                                    <span key={i} className={styles.ollamaInstallLogLine}>{line}</span>
                                  ))
                              }
                            </div>
                          </div>
                        )
                      })()}

                      {/* error: show message + back button */}
                      {ollamaInstallPhase === 'error' && (
                        <>
                          <div className={styles.ollamaInstallText}>
                            <strong>Installation failed</strong>
                            <span>{ollamaInstallError}</span>
                          </div>
                          <button
                            className={styles.retryOllamaBtn}
                            onClick={() => {
                              setOllamaInstallPhase('idle')
                              setOllamaInstallError('')
                            }}
                          >
                            Back
                          </button>
                        </>
                      )}
                    </div>
                  )}

                  {/* Model download — only shown when Ollama is running */}
                  {ollamaAvailable === true && pullPhase === 'idle' && (
                    <button className={styles.downloadModelBtn} onClick={handleDownloadModelClick}>
                      + Download New Model
                    </button>
                  )}

                  {pullPhase === 'selecting' && (
                    <div className={styles.pullModelPanel}>
                      <div className={styles.pullPanelHeader}>
                        <span>Select model to download</span>
                        <button onClick={() => setPullPhase('idle')}>&#x2715;</button>
                      </div>
                      <input
                        className={styles.pullModelSearch}
                        placeholder="Search models..."
                        value={modelSearch}
                        onChange={e => setModelSearch(e.target.value)}
                      />
                      <div className={styles.pullModelList}>
                        {suggestedModels
                          .filter(m =>
                            m.name.toLowerCase().includes(modelSearch.toLowerCase()) ||
                            m.label.toLowerCase().includes(modelSearch.toLowerCase())
                          )
                          .map(m => (
                            <label
                              key={m.name}
                              className={`${styles.pullModelItem} ${selectedPullModel === m.name ? styles.pullModelItemSelected : ''}`}
                            >
                              <input
                                type="radio"
                                checked={selectedPullModel === m.name}
                                onChange={() => setSelectedPullModel(m.name)}
                              />
                              <span className={styles.pullModelName}>{m.label}</span>
                              <span className={styles.pullModelSize}>{m.size}</span>
                              {m.recommended && <span className={styles.pullModelBadge}>Recommended</span>}
                            </label>
                          ))}
                      </div>
                      <div className={styles.pullPanelFooter}>
                        <button
                          className={styles.pullStartBtn}
                          onClick={handleStartPull}
                          disabled={!selectedPullModel}
                        >
                          Download
                        </button>
                      </div>
                    </div>
                  )}

                  {pullPhase === 'pulling' && (
                    <div className={styles.pullProgressPanel}>
                      <span>Downloading {selectedPullModel}...</span>
                      {pullBytes && pullBytes.total > 0 ? (
                        <>
                          <div className={styles.pullProgressBar}>
                            <div className={styles.pullProgressFill} style={{ width: `${pullBytes.percent}%` }} />
                          </div>
                          <div className={styles.pullProgressInfo}>
                            <span>{fmtBytes(pullBytes.completed)} / {fmtBytes(pullBytes.total)}</span>
                            <span>{pullBytes.percent}%</span>
                          </div>
                        </>
                      ) : (
                        <div className={styles.pullProgressBar}>
                          <div className={styles.pullProgressFill} style={{ width: '0%' }} />
                        </div>
                      )}
                      <p className={styles.pullStatusText}>{pullStatus || 'Starting...'}</p>
                    </div>
                  )}
                </div>
              )}

              {currentProvider.has_vlm && (
                provider === 'openrouter' && currentProvider.supports_catalog ? (
                  <OpenRouterModelPicker
                    models={orCatalog.models}
                    loading={orCatalog.loading}
                    error={orCatalog.error}
                    onRefresh={orCatalog.refresh}
                    label="VLM Model"
                    requireVision
                    value={newVlmModel || currentVlmModel || ''}
                    onChange={(v) => { setNewVlmModel(v); setHasChanges(true) }}
                  />
                ) : (
                <div className={styles.formGroup}>
                  <label>VLM Model</label>
                  {(() => {
                    const visionKeywords = ['llava', 'vision', 'moondream', 'bakllava']
                    const visionModels = ollamaModels.filter(m =>
                      visionKeywords.some(kw => m.toLowerCase().includes(kw))
                    )
                    const vlmOptions = provider === 'remote' && ollamaModels.length > 0
                      ? (visionModels.length > 0 ? visionModels : ollamaModels)
                      : []
                    return vlmOptions.length > 0 ? (
                      <select
                        value={newVlmModel || currentVlmModel || ''}
                        onChange={(e) => { setNewVlmModel(e.target.value); setHasChanges(true) }}
                      >
                        {vlmOptions.map(m => <option key={m} value={m}>{m}</option>)}
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={newVlmModel || currentVlmModel || ''}
                        onChange={(e) => { setNewVlmModel(e.target.value); setHasChanges(true) }}
                        placeholder={
                          provider === 'remote' && ollamaModelsLoading
                            ? 'Loading models...'
                            : currentVlmModel || 'Enter VLM model name...'
                        }
                      />
                    )
                  })()}
                </div>
                )
              )}
            </>
          )}

          {/* API Key */}
          {currentProvider?.requires_api_key && (
            <div className={styles.formGroup}>
              <label>
                API Key
                {apiKeys[provider]?.has_key ? (
                  <Badge variant="success" style={{ marginLeft: 8 }}>Configured</Badge>
                ) : (
                  <Badge variant="warning" style={{ marginLeft: 8 }}>Required</Badge>
                )}
              </label>
              {apiKeys[provider]?.has_key && (
                <div className={styles.maskedKey}>{apiKeys[provider].masked_key}</div>
              )}
              <input
                type="password"
                value={newApiKey}
                onChange={(e) => { setNewApiKey(e.target.value); setHasChanges(true) }}
                placeholder={apiKeys[provider]?.has_key ? 'Enter new key to replace...' : 'Enter API key...'}
              />
              {(['moonshot', 'minimax'] as string[]).includes(provider) && (
                <p style={{ fontSize: '0.78rem', color: 'var(--text-muted, #888)', marginTop: 6, lineHeight: 1.4 }}>
                  {apiKeys['openrouter']?.has_key
                    ? 'OpenRouter is configured and will be used automatically if the direct API is unavailable in your region.'
                    : 'This provider may be geo-restricted. If the direct API fails, configure OpenRouter as a fallback — it will be used automatically.'}
                </p>
              )}
            </div>
          )}

          {/* OpenRouter credits */}
          {provider === 'openrouter' && currentProvider?.supports_catalog && (
            <OpenRouterCreditsBanner
              send={send}
              onMessage={onMessage}
              isConnected={isConnected}
              hasApiKey={!!apiKeys[provider]?.has_key}
            />
          )}

          {/* Base URL */}
          {currentProvider?.base_url_env && (
            <div className={styles.formGroup}>
              <label>Server URL</label>
              <input
                type="text"
                value={newBaseUrl || baseUrls[provider] || ''}
                onChange={(e) => { setNewBaseUrl(e.target.value); setHasChanges(true) }}
                placeholder={provider === 'remote' ? 'http://localhost:11434' : 'Enter base URL...'}
              />
            </div>
          )}

          {/* Actions */}
          <div className={styles.sectionFooter} style={{ borderTop: 'none', paddingTop: 0 }}>
            <Button
              variant="secondary"
              onClick={handleTestConnection}
              disabled={isTesting || (provider !== 'remote' && !apiKeys[provider]?.has_key)}
              title={provider !== 'remote' && !apiKeys[provider]?.has_key ? 'API key required for testing' : ''}
            >
              {isTesting ? (
                <>
                  <Loader2 size={14} className={styles.spinning} />
                  Testing...
                </>
              ) : (
                'Test Connection'
              )}
            </Button>
            <Button
              variant="primary"
              onClick={handleSave}
              disabled={isSaving || isTesting || !hasChanges}
            >
              {isSaving ? (
                <>
                  <Loader2 size={14} className={styles.spinning} />
                  Saving...
                </>
              ) : isTesting && testBeforeSave ? (
                <>
                  <Loader2 size={14} className={styles.spinning} />
                  Testing Connection...
                </>
              ) : (
                'Save'
              )}
            </Button>
          </div>

          {/* Slow Mode */}
          <hr style={{ border: 'none', borderTop: '1px solid var(--border-primary)', margin: 'var(--space-4) 0' }} />
          <div className={styles.toggleGroup}>
            <div className={styles.toggleInfo}>
              <span className={styles.toggleLabel}>Slow Mode</span>
              <span className={styles.toggleDesc}>
                Limits token usage to stay within API rate limits.
                Enable this if you experience rate limiting errors from your provider.
              </span>
            </div>
            <input
              type="checkbox"
              className={styles.toggle}
              checked={slowModeEnabled}
              onChange={(e) => {
                dispatch(setSlowModeEnabled(e.target.checked))
                send('slow_mode_set', { enabled: e.target.checked })
              }}
              disabled={isLoadingSlowMode}
            />
          </div>
        </div>
      )}

      {/* Connection Test Result Modal */}
      {testResult && (
        <div className={styles.modalOverlay} onClick={() => { setTestResult(null); setTestBeforeSave(false) }}>
          <div className={styles.testResultModal} onClick={e => e.stopPropagation()}>
            <div className={`${styles.testResultIcon} ${testResult.success ? styles.success : styles.error}`}>
              {testResult.success ? <Check size={32} /> : <X size={32} />}
            </div>
            <h3 className={styles.testResultTitle}>
              {testResult.success ? (
                testBeforeSave ? 'Connection and Configuration Successful' : 'Connection Successful'
              ) : (
                'Connection Failed'
              )}
            </h3>
            <p className={styles.testResultMessage}>
              {testResult.success ? (
                testBeforeSave ? (
                  <span style={{ textAlign: 'center', display: 'block' }}>
                    <span>{testResult.message}</span>
                    <span style={{ marginTop: 12, fontWeight: 600, color: '#10b981', display: 'block' }}>
                      &#x2713; Configuration saved successfully
                    </span>
                  </span>
                ) : (
                  <span style={{ textAlign: 'center', display: 'block' }}>
                    <span>{testResult.message}</span>
                    {testResult.models && testResult.models.length > 0 && (
                      <span style={{ marginTop: 10, display: 'block', fontSize: '0.85em', color: 'var(--text-secondary)' }}>
                        {testResult.models.map(m => (
                          <span key={m} style={{
                            display: 'inline-block',
                            background: 'var(--bg-tertiary)',
                            borderRadius: 4,
                            padding: '2px 8px',
                            margin: '3px 3px 0 0',
                            fontFamily: 'monospace',
                          }}>{m}</span>
                        ))}
                      </span>
                    )}
                  </span>
                )
              ) : (
                <span style={{ textAlign: 'center', display: 'block' }}>
                  <span>{testResult.error || testResult.message}</span>
                  {(['moonshot', 'minimax'] as string[]).includes(provider) && (
                    <span style={{ marginTop: 12, display: 'block', fontSize: '0.82rem', color: 'var(--text-muted, #888)', lineHeight: 1.5 }}>
                      This provider may be geo-restricted in your region.
                      {apiKeys['openrouter']?.has_key
                        ? ' OpenRouter is already configured and will be used as a fallback automatically.'
                        : ' Configure OpenRouter in Settings → select "OpenRouter" provider — it will be used as a fallback automatically.'}
                    </span>
                  )}
                </span>
              )}
            </p>
            <Button variant="secondary" onClick={() => { setTestResult(null); setTestBeforeSave(false) }}>
              Close
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
