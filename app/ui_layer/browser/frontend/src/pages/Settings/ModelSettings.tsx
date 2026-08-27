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
  setSubscriptionPending,
  clearSubscriptionPasteback,
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
  selectAwsCredentials,
  selectModelHasLoadedProviders,
  selectModelHasLoadedSlowMode,
  selectImageGenProvider,
  selectCurrentImageGenModel,
  selectVideoGenProvider,
  selectCurrentVideoGenModel,
  selectSubscriptionOauth,
  selectSubscriptionPending,
  selectSubscriptionPasteback,
} from '../../store/selectors/modelSettings'
import { getOllamaInstallPercent } from '../../utils/ollamaInstall'
import {
  OpenRouterModelPicker,
  OpenRouterCreditsBanner,
  useOpenRouterCatalog,
} from './OpenRouterModelPicker'

// Types
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
  const awsCredentialsStatus = useAppSelector(selectAwsCredentials)
  const imageGenProvider = useAppSelector(selectImageGenProvider)
  const currentImageGenModel = useAppSelector(selectCurrentImageGenModel)
  const videoGenProvider = useAppSelector(selectVideoGenProvider)
  const currentVideoGenModel = useAppSelector(selectCurrentVideoGenModel)
  const hasLoadedProviders = useAppSelector(selectModelHasLoadedProviders)
  const hasLoadedSlowMode = useAppSelector(selectModelHasLoadedSlowMode)
  const subscriptionOauth = useAppSelector(selectSubscriptionOauth)
  const subscriptionPending = useAppSelector(selectSubscriptionPending)
  const subscriptionPasteback = useAppSelector(selectSubscriptionPasteback)
  // Local state for the textbox value while the user types the pasted code.
  // Keyed by provider so multiple Connect attempts don't bleed values.
  const [pastebackInput, setPastebackInput] = useState<Record<string, string>>({})
  // When subscription is connected, the API-key block collapses under a
  // subtle "Use API key instead" toggle so it's clear only one method is
  // needed. This tracks per-provider user intent to expand it manually.
  const [apiKeyExpandedByUser, setApiKeyExpandedByUser] = useState<Record<string, boolean>>({})
  const isLoading = !hasLoadedProviders
  const isLoadingSlowMode = !hasLoadedSlowMode

  // Local setters (write-through to slice for any code that used to call setX directly).
  const setProvider = (p: string) => dispatch(setModelProvider(p))

  // Form state (transient — local).
  const [newApiKey, setNewApiKey] = useState('')
  const [newBaseUrl, setNewBaseUrl] = useState('')
  const [newLlmModel, setNewLlmModel] = useState('')
  const [newVlmModel, setNewVlmModel] = useState('')

  // Bedrock-specific form state — AWS credentials don't fit the api_key shape
  // (multiple fields). All four are blank until the user fills them in;
  // unchanged values fall through to whatever is already in settings.json.
  const [newAwsAccessKeyId, setNewAwsAccessKeyId] = useState('')
  const [newAwsSecretAccessKey, setNewAwsSecretAccessKey] = useState('')
  const [newAwsSessionToken, setNewAwsSessionToken] = useState('')
  const [newAwsRegion, setNewAwsRegion] = useState('')

  // Image generation form state (transient — local).
  const [newImageGenProvider, setNewImageGenProvider] = useState('')
  const [newImageGenModel, setNewImageGenModel] = useState('')
  const [newImageGenApiKey, setNewImageGenApiKey] = useState('')
  const [imageGenHasChanges, setImageGenHasChanges] = useState(false)
  const [isImageGenSaving, setIsImageGenSaving] = useState(false)

  // Video generation form state (transient — local).
  const [newVideoGenProvider, setNewVideoGenProvider] = useState('')
  const [newVideoGenModel, setNewVideoGenModel] = useState('')
  const [newVideoGenApiKey, setNewVideoGenApiKey] = useState('')
  const [videoGenHasChanges, setVideoGenHasChanges] = useState(false)
  const [isVideoGenSaving, setIsVideoGenSaving] = useState(false)

  // UI state (transient — local).
  const [isSaving, setIsSaving] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [testBeforeSave, setTestBeforeSave] = useState(false)

  // Ollama list loading flag (transient). Models + availability are slice-backed.
  const [ollamaModelsLoading, setOllamaModelsLoading] = useState(false)

  // Generic /v1/models discovery (any provider with has_model_discovery:
  // the new cloud providers + LM Studio/vLLM/llama.cpp). Mirrors the Ollama
  // dropdown but wire-generic. docs/PROVIDER_SETTINGS_UX_FIX.md A2.
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([])
  const [discoveredLoading, setDiscoveredLoading] = useState(false)

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
          setNewVideoGenProvider('')
          setNewVideoGenModel('')
          hasInitialized.current = true
        }
      }),
      onMessage('model_settings_update', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        setIsSaving(false)
        setIsImageGenSaving(false)
        setIsVideoGenSaving(false)
        if (d.success) {
          setNewApiKey('')
          setNewBaseUrl('')
          setNewLlmModel('')
          setNewVlmModel('')
          setNewAwsAccessKeyId('')
          setNewAwsSecretAccessKey('')
          setNewAwsSessionToken('')
          setNewAwsRegion('')
          setHasChanges(false)
          setNewImageGenProvider('')
          setNewImageGenModel('')
          setNewImageGenApiKey('')
          setImageGenHasChanges(false)
          setNewVideoGenProvider('')
          setNewVideoGenModel('')
          setNewVideoGenApiKey('')
          setVideoGenHasChanges(false)
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
          const awsCreds = buildAwsCredentialsPayload()
          send('model_settings_update', {
            llmProvider: provider,
            vlmProvider: provider,
            llmModel: newLlmModel || currentLlmModel || undefined,
            vlmModel: newVlmModel || currentVlmModel || undefined,
            apiKey: newApiKey || undefined,
            providerForKey: newApiKey ? provider : undefined,
            baseUrl: newBaseUrl || undefined,
            providerForUrl: newBaseUrl ? provider : undefined,
            awsCredentials: awsCreds,
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
      onMessage('provider_models_get', (data: unknown) => {
        const d = data as { success: boolean; models?: string[]; provider?: string }
        // Responses are broadcast and can arrive after a provider switch —
        // only accept the list that belongs to the currently selected provider.
        if (d.provider && d.provider !== provider) return
        setDiscoveredLoading(false)
        const models = d.success && d.models ? d.models : []
        setDiscoveredModels(models)
        // If exactly one model is served (vLLM / llama.cpp) or the current
        // selection isn't offered, auto-select the first discovered id so
        // the field reflects what the server actually has.
        if (models.length > 0) {
          setNewLlmModel(prev => {
            const eff = prev || currentLlmModel
            if (!eff || !models.includes(eff)) { setHasChanges(true); return models[0] }
            return prev
          })
        }
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
  }, [isConnected, onMessage, send, dispatch, testBeforeSave, provider, newApiKey, newBaseUrl, baseUrls, selectedPullModel, currentLlmModel, currentVlmModel, showToast, newAwsAccessKeyId, newAwsSecretAccessKey, newAwsSessionToken, newAwsRegion, newLlmModel, newVlmModel])

  // Load initial data when connected. Providers/slow-mode are cached across
  // remounts, but settings are ALWAYS refetched: the page must show what's
  // actually saved. With the old load-once cache, a tab that outlived a
  // backend restart (the socket reconnects without a page reload) kept
  // rendering stale Redux state, so the model field showed the registry
  // default instead of the user's saved model.
  useEffect(() => {
    if (!isConnected) return
    if (!hasLoadedProviders) send('model_providers_get')
    send('model_settings_get')
    if (!hasLoadedSlowMode) send('slow_mode_get')
  }, [isConnected, send, hasLoadedProviders, hasLoadedSlowMode])

  // Fetch Ollama models whenever the active provider is 'remote'
  useEffect(() => {
    if (!isConnected || provider !== 'remote') return
    setOllamaModelsLoading(true)
    send('ollama_models_get', { baseUrl: baseUrls['remote'] || undefined })
  }, [provider, isConnected, send, baseUrls])

  const currentProvider = providers.find(p => p.id === provider)

  // Generic /v1/models discovery: fetch whenever the active provider
  // advertises has_model_discovery (new cloud providers). Ollama keeps its
  // own native path above. Local servers (lmstudio/vllm/llamacpp) are
  // excluded: their model id is always a free-text input, so there is
  // nothing to discover for the field.
  useEffect(() => {
    setDiscoveredModels([])
    if (
      !isConnected ||
      !currentProvider?.has_model_discovery ||
      currentProvider?.local_kind ||
      provider === 'remote'
    ) return
    setDiscoveredLoading(true)
    send('provider_models_get', {
      provider,
      baseUrl: newBaseUrl || baseUrls[provider] || undefined,
      apiKey: newApiKey || undefined,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, isConnected, currentProvider?.has_model_discovery, currentProvider?.local_kind, baseUrls, send])

  // Options for the LLM/VLM dropdowns: Ollama native list, else the
  // live-discovered /v1/models list. We never ship a hardcoded model list —
  // providers we can't enumerate online fall back to a free-text input so the
  // suggestions can't go stale.
  // Local servers (lmstudio/vllm/llamacpp) never get a dropdown: the model
  // id is whatever the user loaded on their server, so it stays a text input.
  const modelOptions: string[] =
    provider === 'remote'
      ? ollamaModels
      : currentProvider?.local_kind
        ? []
        : discoveredModels
  const modelsLoading = provider === 'remote' ? ollamaModelsLoading : discoveredLoading

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
    setNewAwsAccessKeyId('')
    setNewAwsSecretAccessKey('')
    setNewAwsSessionToken('')
    setNewAwsRegion('')
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

  // Bedrock helper: pack the form's AWS credential fields into the shape the
  // backend's update/test endpoints expect. Returns undefined when none of the
  // bedrock fields have been touched, so the existing flow's "credentials
  // changing" detection still works for the non-bedrock branches.
  const buildAwsCredentialsPayload = () => {
    if (provider !== 'bedrock') return undefined
    const hasAny =
      newAwsAccessKeyId.length > 0 ||
      newAwsSecretAccessKey.length > 0 ||
      newAwsSessionToken.length > 0 ||
      newAwsRegion.length > 0
    if (!hasAny) return undefined
    const payload: Record<string, string> = {}
    if (newAwsAccessKeyId) payload.access_key_id = newAwsAccessKeyId
    if (newAwsSecretAccessKey) payload.secret_access_key = newAwsSecretAccessKey
    if (newAwsSessionToken) payload.session_token = newAwsSessionToken
    if (newAwsRegion) payload.region = newAwsRegion
    return payload
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
      awsCredentials: buildAwsCredentialsPayload(),
    })
  }

  const handleSave = () => {
    const isChangingApiKey = newApiKey.length > 0
    const isChangingBaseUrl = newBaseUrl.length > 0
    const awsCreds = buildAwsCredentialsPayload()
    const isChangingAws = awsCreds !== undefined

    if (isChangingApiKey || isChangingBaseUrl || isChangingAws) {
      setTestBeforeSave(true)
      setIsTesting(true)
      send('model_connection_test', {
        provider,
        apiKey: newApiKey || undefined,
        baseUrl: newBaseUrl || baseUrls[provider],
        model: newLlmModel || currentLlmModel || undefined,
        awsCredentials: awsCreds,
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

  const handleImageGenSave = () => {
    setIsImageGenSaving(true)
    const effectiveProvider = newImageGenProvider || imageGenProvider
    send('model_settings_update', {
      imageGenProvider: effectiveProvider,
      imageGenModel: newImageGenModel || currentImageGenModel || undefined,
      ...(newImageGenApiKey ? {
        apiKey: newImageGenApiKey,
        providerForKey: effectiveProvider,
      } : {}),
    })
  }

  const handleVideoGenSave = () => {
    setIsVideoGenSaving(true)
    const effectiveProvider = newVideoGenProvider || videoGenProvider
    send('model_settings_update', {
      videoGenProvider: effectiveProvider,
      videoGenModel: newVideoGenModel || currentVideoGenModel || undefined,
      ...(newVideoGenApiKey ? {
        apiKey: newVideoGenApiKey,
        providerForKey: effectiveProvider,
      } : {}),
    })
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
              {currentProvider.supports_catalog ? (
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
                  {modelOptions.length > 0 ? (
                    <select
                      value={newLlmModel || currentLlmModel || ''}
                      onChange={(e) => { setNewLlmModel(e.target.value); setHasChanges(true) }}
                    >
                      {/* keep the saved value visible even if not in the list */}
                      {(newLlmModel || currentLlmModel) &&
                        !modelOptions.includes(newLlmModel || currentLlmModel) && (
                        <option value={newLlmModel || currentLlmModel}>
                          {newLlmModel || currentLlmModel}
                        </option>
                      )}
                      {modelOptions.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={newLlmModel || currentLlmModel || ''}
                      onChange={(e) => { setNewLlmModel(e.target.value); setHasChanges(true) }}
                      placeholder={
                        modelsLoading
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
                currentProvider.supports_catalog ? (
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
                    // Ollama filters its list to vision-tagged names; other
                    // providers expose opaque ids, so offer the full
                    // discovered/curated list (the profile's vlm_model
                    // default is pre-selected).
                    const visionKeywords = ['llava', 'vision', 'moondream', 'bakllava', 'vl']
                    const vlmOptions = provider === 'remote'
                      ? (() => {
                          const vm = ollamaModels.filter(m =>
                            visionKeywords.some(kw => m.toLowerCase().includes(kw)))
                          return vm.length > 0 ? vm : ollamaModels
                        })()
                      : modelOptions
                    return vlmOptions.length > 0 ? (
                      <select
                        value={newVlmModel || currentVlmModel || ''}
                        onChange={(e) => { setNewVlmModel(e.target.value); setHasChanges(true) }}
                      >
                        {(newVlmModel || currentVlmModel) &&
                          !vlmOptions.includes(newVlmModel || currentVlmModel) && (
                          <option value={newVlmModel || currentVlmModel}>
                            {newVlmModel || currentVlmModel}
                          </option>
                        )}
                        {vlmOptions.map(m => <option key={m} value={m}>{m}</option>)}
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={newVlmModel || currentVlmModel || ''}
                        onChange={(e) => { setNewVlmModel(e.target.value); setHasChanges(true) }}
                        placeholder={
                          modelsLoading
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

          {/* Auth (Subscription OAuth + API Key) — either method authorizes
              the provider. When the provider supports both, the subscription
              block sits above an "or" divider and the API-key block sits
              below; whichever is configured wins. When only API-key auth is
              available (most providers), the subscription block is skipped
              and the API key section renders as usual. Element vocabulary
              is intentionally the same as the IntegrationsSettings "OAuth
              or Token" pattern: connectFormDivider between choices,
              standard formGroup / formInput / Button elements throughout. */}
          {(() => {
            const supportsSub = !!currentProvider?.supports_subscription_oauth
            const subStatus = subscriptionOauth[provider]
            const isSubConnected = !!subStatus?.connected
            const isSubPending = !!subscriptionPending[provider]
            const pb = subscriptionPasteback[provider]
            const codeValue = pastebackInput[provider] || ''
            const hasStoredKey = !!apiKeys[provider]?.has_key
            const requiresKey = !!currentProvider?.requires_api_key
            // When the subscription is connected, the API-key block collapses
            // by default under a subtle toggle. The user can still expand it
            // to change / clear a stored key without disconnecting first.
            const apiKeyExpanded =
              apiKeyExpandedByUser[provider] ?? (!isSubConnected || hasStoredKey)

            const subscriptionBlock = supportsSub && (
              <div className={styles.formGroup}>
                <label>
                  Subscription
                  {isSubConnected ? (
                    <Badge variant="success" style={{ marginLeft: 8 }}>Connected</Badge>
                  ) : pb?.awaiting ? (
                    <Badge variant="default" style={{ marginLeft: 8 }}>Awaiting code</Badge>
                  ) : null}
                </label>

                {isSubConnected ? (
                  <>
                    {(subStatus?.email || subStatus?.plan) && (
                      <span className={styles.subscriptionIdentity}>
                        {[subStatus?.email, subStatus?.plan].filter(Boolean).join(' · ')}
                      </span>
                    )}
                    <div className={styles.subscriptionButtonRow}>
                      <Button
                        variant="secondary"
                        disabled={isSubPending}
                        onClick={() => {
                          dispatch(setSubscriptionPending({ provider, pending: true }))
                          send('model_subscription_disconnect', { provider })
                        }}
                      >
                        {isSubPending ? <Loader2 size={14} className={styles.spinning} /> : 'Disconnect'}
                      </Button>
                    </div>
                  </>
                ) : pb?.awaiting ? (
                  <>
                    <input
                      type="text"
                      placeholder="Paste the code from the sign-in page"
                      value={codeValue}
                      onChange={(e) => setPastebackInput({ ...pastebackInput, [provider]: e.target.value })}
                      disabled={isSubPending}
                    />
                    <div className={styles.subscriptionButtonRow}>
                      <Button
                        variant="primary"
                        disabled={isSubPending || !codeValue.trim()}
                        onClick={() => {
                          dispatch(setSubscriptionPending({ provider, pending: true }))
                          send('model_subscription_complete', {
                            provider,
                            code: codeValue.trim(),
                            attemptId: pb.attemptId,
                          })
                        }}
                      >
                        {isSubPending ? <Loader2 size={14} className={styles.spinning} /> : 'Submit code'}
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={isSubPending}
                        onClick={() => {
                          dispatch(clearSubscriptionPasteback(provider))
                          setPastebackInput({ ...pastebackInput, [provider]: '' })
                        }}
                      >
                        Cancel
                      </Button>
                      {pb.authUrl && (
                        <a
                          href={pb.authUrl}
                          target="_blank"
                          rel="noreferrer"
                          className={styles.subscriptionInlineLink}
                        >
                          Reopen sign-in page
                        </a>
                      )}
                    </div>
                    {pb.errorMessage && (
                      <div className={styles.formError}>{pb.errorMessage}</div>
                    )}
                  </>
                ) : (
                  <div className={styles.subscriptionButtonRow}>
                    <Button
                      variant="primary"
                      disabled={isSubPending}
                      onClick={() => {
                        dispatch(setSubscriptionPending({ provider, pending: true }))
                        // OpenAI's OAuth uses a proper loopback callback
                        // (http://localhost:1455/auth/callback) — the browser
                        // redirects back automatically, no paste needed.
                        // xAI/Grok's flow ends on a "copy this code" page in
                        // most browser contexts, so it goes through the
                        // paste-back flow instead.
                        const useLoopback = provider === 'openai'
                        send(
                          useLoopback ? 'model_subscription_connect' : 'model_subscription_prepare',
                          { provider },
                        )
                        showToast(
                          'success',
                          `Opening browser to sign in with ${currentProvider?.name || provider}…`,
                        )
                      }}
                    >
                      {isSubPending
                        ? <><Loader2 size={14} className={styles.spinning} /> Opening browser…</>
                        : (currentProvider?.subscription_label || `Sign in with ${currentProvider?.name || provider}`)}
                    </Button>
                  </div>
                )}
              </div>
            )

            // Compact "Use API key instead" toggle when subscription owns
            // auth. Clicking expands the full API-key formGroup below the
            // divider, so the user can still add/replace a key without
            // disconnecting the subscription first.
            const apiKeyCollapsedToggle = supportsSub && isSubConnected && !apiKeyExpanded && (
              <button
                type="button"
                className={styles.subscriptionSecondaryLink}
                onClick={() => setApiKeyExpandedByUser({ ...apiKeyExpandedByUser, [provider]: true })}
              >
                Use API key instead
              </button>
            )

            const apiKeyBlock = requiresKey && (
              <div className={styles.formGroup}>
                <label>
                  API Key
                  {hasStoredKey ? (
                    <Badge variant="success" style={{ marginLeft: 8 }}>Configured</Badge>
                  ) : isSubConnected ? (
                    <Badge variant="default" style={{ marginLeft: 8 }}>Optional</Badge>
                  ) : (
                    <Badge variant="warning" style={{ marginLeft: 8 }}>Required</Badge>
                  )}
                </label>
                {hasStoredKey && (
                  <div className={styles.maskedKey}>{apiKeys[provider].masked_key}</div>
                )}
                <input
                  type="password"
                  value={newApiKey}
                  onChange={(e) => { setNewApiKey(e.target.value); setHasChanges(true) }}
                  placeholder={hasStoredKey ? 'Enter new key to replace...' : 'Enter API key...'}
                />
                {currentProvider?.openrouter_proxy && (
                  <p style={{ fontSize: '0.78rem', color: 'var(--text-muted, #888)', marginTop: 6, lineHeight: 1.4 }}>
                    {apiKeys['openrouter']?.has_key
                      ? 'OpenRouter is configured and will be used automatically if the direct API is unavailable in your region.'
                      : 'This provider may be geo-restricted. If the direct API fails, configure OpenRouter as a fallback — it will be used automatically.'}
                  </p>
                )}
              </div>
            )

            // If the provider doesn't support subscription auth, only the
            // API-key block renders — no divider, no wrapper.
            if (!supportsSub) return apiKeyBlock

            return (
              <>
                {subscriptionBlock}
                {requiresKey && (
                  <div className={styles.connectFormDivider}>or</div>
                )}
                {apiKeyCollapsedToggle}
                {(apiKeyExpanded || !isSubConnected) && apiKeyBlock}
              </>
            )
          })()}

          {/* OpenRouter credits (catalog providers only — OR today) */}
          {currentProvider?.supports_catalog && (
            <OpenRouterCreditsBanner
              send={send}
              onMessage={onMessage}
              isConnected={isConnected}
              hasApiKey={!!apiKeys[provider]?.has_key}
            />
          )}

          {/* AWS Bedrock credentials */}
          {currentProvider?.is_bedrock && (
            <>
              <div className={styles.formGroup}>
                <label>
                  AWS Access Key ID
                  {awsCredentialsStatus?.has_access_key_id ? (
                    <Badge variant="success" style={{ marginLeft: 8 }}>Configured</Badge>
                  ) : (
                    <Badge variant="warning" style={{ marginLeft: 8 }}>Optional</Badge>
                  )}
                </label>
                {awsCredentialsStatus?.has_access_key_id && (
                  <div className={styles.maskedKey}>{awsCredentialsStatus.masked_access_key_id}</div>
                )}
                <input
                  type="text"
                  value={newAwsAccessKeyId}
                  onChange={(e) => { setNewAwsAccessKeyId(e.target.value); setHasChanges(true) }}
                  placeholder={
                    awsCredentialsStatus?.has_access_key_id
                      ? 'Enter new key ID to replace...'
                      : 'AKIA...'
                  }
                  autoComplete="off"
                />
                <p style={{ fontSize: '0.78rem', color: 'var(--text-muted, #888)', marginTop: 6, lineHeight: 1.4 }}>
                  Leave blank to use the boto3 credential chain (env vars, IAM role,
                  or SSO profile on the host).
                </p>
              </div>

              <div className={styles.formGroup}>
                <label>
                  AWS Secret Access Key
                  {awsCredentialsStatus?.has_secret_access_key && (
                    <Badge variant="success" style={{ marginLeft: 8 }}>Configured</Badge>
                  )}
                </label>
                <input
                  type="password"
                  value={newAwsSecretAccessKey}
                  onChange={(e) => { setNewAwsSecretAccessKey(e.target.value); setHasChanges(true) }}
                  placeholder={
                    awsCredentialsStatus?.has_secret_access_key
                      ? 'Enter new secret to replace...'
                      : 'Enter secret access key'
                  }
                  autoComplete="off"
                />
              </div>

              <div className={styles.formGroup}>
                <label>
                  AWS Session Token <span style={{ color: 'var(--text-muted, #888)' }}>(optional)</span>
                </label>
                <input
                  type="password"
                  value={newAwsSessionToken}
                  onChange={(e) => { setNewAwsSessionToken(e.target.value); setHasChanges(true) }}
                  placeholder="Only required for temporary STS credentials"
                  autoComplete="off"
                />
              </div>

              <div className={styles.formGroup}>
                <label>AWS Region</label>
                <input
                  type="text"
                  value={newAwsRegion || awsCredentialsStatus?.region || baseUrls['bedrock'] || ''}
                  onChange={(e) => { setNewAwsRegion(e.target.value); setHasChanges(true) }}
                  placeholder="us-east-1"
                />
                <p style={{ fontSize: '0.78rem', color: 'var(--text-muted, #888)', marginTop: 6, lineHeight: 1.4 }}>
                  Bedrock model availability and inference profile IDs vary by region —
                  see the AWS Bedrock model catalog for what's enabled in yours.
                </p>
              </div>
            </>
          )}

          {/* Base URL — suppressed for bedrock since region lives in the AWS block above */}
          {currentProvider?.base_url_env && provider !== 'bedrock' && (
            <div className={styles.formGroup}>
              <label>Server URL</label>
              <input
                type="text"
                value={newBaseUrl || baseUrls[provider] || ''}
                onChange={(e) => { setNewBaseUrl(e.target.value); setHasChanges(true) }}
                placeholder={currentProvider?.default_base_url || 'Enter base URL...'}
              />
            </div>
          )}

          {/* Actions */}
          <div className={styles.sectionFooter} style={{ borderTop: 'none', paddingTop: 0 }}>
            <Button
              variant="secondary"
              onClick={handleTestConnection}
              disabled={
                isTesting ||
                (!!currentProvider?.requires_api_key &&
                  !apiKeys[provider]?.has_key)
              }
              title={
                currentProvider?.requires_api_key &&
                !apiKeys[provider]?.has_key
                  ? 'API key required for testing'
                  : ''
              }
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

          {/* Image Generation */}
          <hr style={{ border: 'none', borderTop: '1px solid var(--border-primary)', margin: 'var(--space-4) 0' }} />
          <div className={styles.sectionHeader} style={{ marginBottom: 'var(--space-3)' }}>
            <h3>Image Generation</h3>
            <p>Configure the provider used for image generation</p>
          </div>
          {(() => {
            const imageGenProviders = providers.filter(p => p.has_image_gen)
            const effectiveImgProvider = newImageGenProvider || imageGenProvider
            const imgProviderInfo = imageGenProviders.find(p => p.id === effectiveImgProvider)
            return (
              <div className={styles.settingsForm} style={{ paddingTop: 0 }}>
                <div className={styles.formGroup}>
                  <label>Provider</label>
                  <select
                    value={effectiveImgProvider}
                    onChange={(e) => {
                      const sel = imageGenProviders.find(p => p.id === e.target.value)
                      setNewImageGenProvider(e.target.value)
                      setNewImageGenModel(sel?.image_gen_model || '')
                      setNewImageGenApiKey('')
                      setImageGenHasChanges(true)
                    }}
                  >
                    {imageGenProviders.map(p => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>

                {/* API Key for image gen provider */}
                {imgProviderInfo?.requires_api_key && (
                  <div className={styles.formGroup}>
                    <label>
                      API Key
                      {apiKeys[effectiveImgProvider]?.has_key ? (
                        <Badge variant="success" style={{ marginLeft: 8 }}>Configured</Badge>
                      ) : (
                        <Badge variant="warning" style={{ marginLeft: 8 }}>Required</Badge>
                      )}
                    </label>
                    {apiKeys[effectiveImgProvider]?.has_key && (
                      <div className={styles.maskedKey}>{apiKeys[effectiveImgProvider].masked_key}</div>
                    )}
                    <input
                      type="password"
                      value={newImageGenApiKey}
                      onChange={(e) => { setNewImageGenApiKey(e.target.value); setImageGenHasChanges(true) }}
                      placeholder={apiKeys[effectiveImgProvider]?.has_key ? 'Enter new key to replace...' : 'Enter API key...'}
                    />
                  </div>
                )}

                {/* Model override */}
                <div className={styles.formGroup}>
                  <label>Model</label>
                  <input
                    type="text"
                    value={newImageGenModel || currentImageGenModel || ''}
                    onChange={(e) => { setNewImageGenModel(e.target.value); setImageGenHasChanges(true) }}
                    placeholder={imgProviderInfo?.image_gen_model || 'Default model'}
                  />
                </div>

                <div className={styles.sectionFooter} style={{ borderTop: 'none', paddingTop: 0 }}>
                  <Button
                    variant="primary"
                    onClick={handleImageGenSave}
                    disabled={isImageGenSaving || !imageGenHasChanges}
                  >
                    {isImageGenSaving ? (
                      <>
                        <Loader2 size={14} className={styles.spinning} />
                        Saving...
                      </>
                    ) : (
                      'Save'
                    )}
                  </Button>
                </div>
              </div>
            )
          })()}

          {/* Video Generation */}
          <hr style={{ border: 'none', borderTop: '1px solid var(--border-primary)', margin: 'var(--space-4) 0' }} />
          <div className={styles.sectionHeader} style={{ marginBottom: 'var(--space-3)' }}>
            <h3>Video Generation</h3>
            <p>Configure the provider used for video generation</p>
          </div>
          {(() => {
            const videoGenProviders = providers.filter(p => p.has_video_gen)
            const effectiveVidProvider = newVideoGenProvider || videoGenProvider
            const vidProviderInfo = videoGenProviders.find(p => p.id === effectiveVidProvider)
            return (
              <div className={styles.settingsForm} style={{ paddingTop: 0 }}>
                <div className={styles.formGroup}>
                  <label>Provider</label>
                  <select
                    value={effectiveVidProvider}
                    onChange={(e) => {
                      const sel = videoGenProviders.find(p => p.id === e.target.value)
                      setNewVideoGenProvider(e.target.value)
                      setNewVideoGenModel(sel?.video_gen_model || '')
                      setNewVideoGenApiKey('')
                      setVideoGenHasChanges(true)
                    }}
                  >
                    {videoGenProviders.map(p => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>

                {/* API Key for video gen provider */}
                {vidProviderInfo?.requires_api_key && (
                  <div className={styles.formGroup}>
                    <label>
                      API Key
                      {apiKeys[effectiveVidProvider]?.has_key ? (
                        <Badge variant="success" style={{ marginLeft: 8 }}>Configured</Badge>
                      ) : (
                        <Badge variant="warning" style={{ marginLeft: 8 }}>Required</Badge>
                      )}
                    </label>
                    {apiKeys[effectiveVidProvider]?.has_key && (
                      <div className={styles.maskedKey}>{apiKeys[effectiveVidProvider].masked_key}</div>
                    )}
                    <input
                      type="password"
                      value={newVideoGenApiKey}
                      onChange={(e) => { setNewVideoGenApiKey(e.target.value); setVideoGenHasChanges(true) }}
                      placeholder={apiKeys[effectiveVidProvider]?.has_key ? 'Enter new key to replace...' : 'Enter API key...'}
                    />
                  </div>
                )}

                {/* Model override */}
                <div className={styles.formGroup}>
                  <label>Model</label>
                  <input
                    type="text"
                    value={newVideoGenModel || currentVideoGenModel || ''}
                    onChange={(e) => { setNewVideoGenModel(e.target.value); setVideoGenHasChanges(true) }}
                    placeholder={vidProviderInfo?.video_gen_model || 'Default model'}
                  />
                </div>

                <div className={styles.sectionFooter} style={{ borderTop: 'none', paddingTop: 0 }}>
                  <Button
                    variant="primary"
                    onClick={handleVideoGenSave}
                    disabled={isVideoGenSaving || !videoGenHasChanges}
                  >
                    {isVideoGenSaving ? (
                      <>
                        <Loader2 size={14} className={styles.spinning} />
                        Saving...
                      </>
                    ) : (
                      'Save'
                    )}
                  </Button>
                </div>
              </div>
            )
          })()}

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
                  {currentProvider?.openrouter_proxy && (
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
