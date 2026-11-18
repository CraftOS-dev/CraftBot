/**
 * Settings > Model, as the browser's Model tab: the provider, the LLM and
 * vision models (from Ollama, live discovery or the OpenRouter catalog, else
 * typed), subscription sign-in (the system browser, then the code pasted
 * back), the API key (masked), AWS credentials for Bedrock, the server URL,
 * a connection test (a save that changes credentials tests first), image and
 * video generation, Ollama install and model downloads, and slow mode.
 *
 * Provider and models are drafts over the saved settings: nothing changes
 * until Save, and a change made elsewhere is flagged with a "load latest" row.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../../../state/hooks'
import { RESOURCES, useResource } from '../../../../../browser/frontend/src/store/resources'
import { useServerDraft } from '../../../../../browser/frontend/src/hooks/useServerDraft'
import {
  clearSubscriptionPasteback,
  setCurrentLlmModel,
  setCurrentVlmModel,
  setOllamaModels,
  setSlowModeEnabled,
  setSubscriptionPending,
} from '../../../../../browser/frontend/src/store/slices/modelSettingsSlice'
import {
  selectApiKeys,
  selectAwsCredentials,
  selectBaseUrls,
  selectCurrentImageGenModel,
  selectCurrentLlmModel,
  selectCurrentVideoGenModel,
  selectCurrentVlmModel,
  selectImageGenProvider,
  selectModelHasLoadedProviders,
  selectModelHasLoadedSettings,
  selectModelHasLoadedSlowMode,
  selectModelProvider,
  selectModelProviders,
  selectOllamaAvailable,
  selectOllamaModels,
  selectSlowModeEnabled,
  selectSubscriptionOauth,
  selectSubscriptionPasteback,
  selectSubscriptionPending,
  selectVideoGenProvider,
} from '../../../../../browser/frontend/src/store/selectors/modelSettings'
import { getOllamaInstallPercent } from '../../../../../browser/frontend/src/utils/ollamaInstall'
import { glyphs } from '../../../theme/theme'
import { useTab, useTabKeys } from '../tabContext'
import { FormView, useForm, type FormRow } from '../coreForm'
import { useFlash, useInbound } from '../coreHooks'
import { ASCII_METER, UNICODE_METER, formatBytes, meter, type ChoiceOption } from '../coreLogic'
import { openInBrowser } from '../coreEditor'

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

interface OpenRouterModel {
  id: string
  name: string
  context_length: number | null
  input_modalities: string[]
  pricing: { prompt: string | null; completion: string | null }
}

interface Credits {
  balance: number | null
  label: string | null
}

const VISION_HINTS = ['llava', 'vision', 'moondream', 'bakllava', 'vl']

function contextLabel(n: number | null): string {
  if (!n) return ''
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`
  return String(n)
}

function isFree(m: OpenRouterModel): boolean {
  const p = parseFloat(m.pricing?.prompt || '0')
  const c = parseFloat(m.pricing?.completion || '0')
  return m.id.endsWith(':free') || ((isNaN(p) || p === 0) && (isNaN(c) || c === 0))
}

export function ModelTab() {
  const { t } = useTranslation('settingsCore')
  const dispatch = useAppDispatch()
  const { active, width, height } = useTab()
  const form = useForm()
  const [flash, say] = useFlash()
  const g = glyphs()

  useResource(RESOURCES.modelProviders)
  useResource(RESOURCES.modelSettings)
  useResource(RESOURCES.slowMode)
  const connected = useAppSelector(s => s.connection.connected)
  const providers = useAppSelector(selectModelProviders)
  const savedProvider = useAppSelector(selectModelProvider)
  const apiKeys = useAppSelector(selectApiKeys)
  const baseUrls = useAppSelector(selectBaseUrls)
  const currentLlmModel = useAppSelector(selectCurrentLlmModel)
  const currentVlmModel = useAppSelector(selectCurrentVlmModel)
  const slowMode = useAppSelector(selectSlowModeEnabled)
  const ollamaModels = useAppSelector(selectOllamaModels)
  const ollamaAvailable = useAppSelector(selectOllamaAvailable)
  const awsStatus = useAppSelector(selectAwsCredentials)
  const imageGenProvider = useAppSelector(selectImageGenProvider)
  const currentImageGenModel = useAppSelector(selectCurrentImageGenModel)
  const videoGenProvider = useAppSelector(selectVideoGenProvider)
  const currentVideoGenModel = useAppSelector(selectCurrentVideoGenModel)
  const hasLoadedProviders = useAppSelector(selectModelHasLoadedProviders)
  const hasLoadedSettings = useAppSelector(selectModelHasLoadedSettings)
  const hasLoadedSlowMode = useAppSelector(selectModelHasLoadedSlowMode)
  const subscriptionOauth = useAppSelector(selectSubscriptionOauth)
  const subscriptionPending = useAppSelector(selectSubscriptionPending)
  const subscriptionPasteback = useAppSelector(selectSubscriptionPasteback)

  const providerDraft = useServerDraft(savedProvider)
  const llmDraft = useServerDraft(currentLlmModel)
  const vlmDraft = useServerDraft(currentVlmModel)
  const provider = providerDraft.value
  const llmModel = llmDraft.value
  const vlmModel = vlmDraft.value

  const [newApiKey, setNewApiKey] = useState('')
  const [newBaseUrl, setNewBaseUrl] = useState('')
  const [aws, setAws] = useState({ accessKeyId: '', secret: '', session: '', region: '' })
  const [hasChanges, setHasChanges] = useState(false)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testBeforeSave, setTestBeforeSave] = useState(false)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const savingSection = useRef<'llm' | 'image' | 'video' | null>(null)

  const [image, setImage] = useState({ provider: '', model: '', apiKey: '', changed: false, saving: false })
  const [video, setVideo] = useState({ provider: '', model: '', apiKey: '', changed: false, saving: false })

  const [ollamaLoading, setOllamaLoading] = useState(false)
  const [discovered, setDiscovered] = useState<string[]>([])
  const [discoveredLoading, setDiscoveredLoading] = useState(false)
  const [installPhase, setInstallPhase] = useState<'idle' | 'installing' | 'error'>('idle')
  const [installLog, setInstallLog] = useState<string[]>([])
  const [installError, setInstallError] = useState('')
  const [pullPhase, setPullPhase] = useState<'idle' | 'selecting' | 'pulling'>('idle')
  const [suggested, setSuggested] = useState<SuggestedModel[]>([])
  const [pullModel, setPullModel] = useState('')
  const [pullBytes, setPullBytes] = useState<{ completed: number; total: number; percent: number } | null>(null)
  const [pullStatus, setPullStatus] = useState('')

  const [orModels, setOrModels] = useState<OpenRouterModel[]>([])
  const [orLoading, setOrLoading] = useState(false)
  const [orError, setOrError] = useState<string | null>(null)
  const [credits, setCredits] = useState<Credits | null>(null)
  const [creditsError, setCreditsError] = useState<string | null>(null)
  const [pasteCode, setPasteCode] = useState<Record<string, string>>({})
  const [apiKeyExpanded, setApiKeyExpanded] = useState<Record<string, boolean>>({})

  const current = providers.find(p => p.id === provider)
  const orBaseUrl = newBaseUrl || baseUrls['openrouter'] || undefined

  const awsPayload = () => {
    if (provider !== 'bedrock') return undefined
    if (!aws.accessKeyId && !aws.secret && !aws.session && !aws.region) return undefined
    const out: Record<string, string> = {}
    if (aws.accessKeyId) out.access_key_id = aws.accessKeyId
    if (aws.secret) out.secret_access_key = aws.secret
    if (aws.session) out.session_token = aws.session
    if (aws.region) out.region = aws.region
    return out
  }

  const clearCredentials = () => {
    setNewApiKey('')
    setNewBaseUrl('')
    setAws({ accessKeyId: '', secret: '', session: '', region: '' })
  }

  const saveLlm = () => {
    setSaving(true)
    savingSection.current = 'llm'
    send('model_settings_update', {
      llmProvider: provider,
      vlmProvider: provider,
      llmModel: llmModel || undefined,
      vlmModel: vlmModel || undefined,
      apiKey: newApiKey || undefined,
      providerForKey: newApiKey ? provider : undefined,
      baseUrl: newBaseUrl || undefined,
      providerForUrl: newBaseUrl ? provider : undefined,
      awsCredentials: awsPayload(),
    })
  }

  // ── Replies to this tab's requests (the slice applies the data) ──

  useInbound('model_settings_update', data => {
    const section = savingSection.current
    if (!section) return
    savingSection.current = null
    const d = data as { success: boolean; error?: string }
    setSaving(false)
    setImage(s => ({ ...s, saving: false }))
    setVideo(s => ({ ...s, saving: false }))
    if (!d.success) {
      say(t('model.saveFailed', { error: d.error ?? '' }), 'error', 8000)
      return
    }
    if (section === 'llm') {
      clearCredentials()
      setHasChanges(false)
      providerDraft.reset()
      llmDraft.reset()
      vlmDraft.reset()
    } else if (section === 'image') setImage({ provider: '', model: '', apiKey: '', changed: false, saving: false })
    else setVideo({ provider: '', model: '', apiKey: '', changed: false, saving: false })
    say(t('model.saved'), 'success')
  })

  useInbound('model_connection_test', data => {
    const d = data as { success: boolean; message: string; error?: string; models?: string[] }
    setTesting(false)
    setTestResult({ success: d.success, message: d.message, error: d.error, models: d.models })
    if (testBeforeSave) {
      setTestBeforeSave(false)
      if (d.success) saveLlm()
    }
  })

  useInbound(['model_subscription_connect', 'model_subscription_disconnect', 'model_subscription_complete'], (data, type) => {
    const d = data as { provider?: string; success: boolean; message?: string; error?: string }
    if (d.provider !== provider) return
    if (type === 'model_subscription_connect' && !d.success) say(d.message || d.error || t('model.sub.connectFailed'), 'error', 8000)
    else if (type === 'model_subscription_connect' || type === 'model_subscription_complete') {
      if (d.success) say(t('model.sub.connected'), 'success')
    } else say(d.success ? d.message || t('model.sub.disconnected') : d.message || d.error || t('model.sub.disconnectFailed'), d.success ? 'success' : 'error')
  })

  useInbound('ollama_models_get', data => {
    const d = data as { success: boolean; models: string[] }
    setOllamaLoading(false)
    if (d.success && d.models?.length) {
      llmDraft.set(prev => (d.models.includes(prev) ? prev : d.models[0]))
      vlmDraft.set(prev => (d.models.includes(prev) ? prev : d.models[0]))
    }
  })

  useInbound('provider_models_get', data => {
    const d = data as { success: boolean; models?: string[]; provider?: string }
    if (d.provider && d.provider !== provider) return
    setDiscoveredLoading(false)
    const models = d.success && d.models ? d.models : []
    setDiscovered(models)
    if (models.length) llmDraft.set(prev => (prev && models.includes(prev) ? prev : models[0]))
  })

  useInbound('local_llm_suggested_models', data => {
    const d = data as { models?: SuggestedModel[] }
    setSuggested(d.models ?? [])
    const rec = d.models?.find(m => m.recommended)
    if (rec) setPullModel(prev => prev || rec.name)
  })

  useInbound('local_llm_pull_progress', data => {
    const d = data as { message: string; total: number; completed: number; percent: number }
    setPullStatus(d.message || '')
    if (d.total > 0) setPullBytes({ completed: d.completed, total: d.total, percent: d.percent })
  })

  useInbound('local_llm_pull_model', data => {
    const d = data as { success: boolean; model?: string; error?: string }
    setPullPhase('idle')
    setPullBytes(null)
    setPullStatus('')
    if (!d.success) {
      say(d.error || t('model.ollama.downloadFailed'), 'error', 8000)
      return
    }
    const pulled = d.model || pullModel
    setOllamaLoading(true)
    send('ollama_models_get', { baseUrl: newBaseUrl || baseUrls['remote'] || undefined })
    // Use the downloaded model at once, as the browser does.
    providerDraft.set('remote')
    llmDraft.set(pulled)
    setSaving(true)
    savingSection.current = 'llm'
    send('model_settings_update', {
      llmProvider: 'remote',
      vlmProvider: 'remote',
      llmModel: pulled,
      vlmModel: pulled,
      ...(newBaseUrl ? { baseUrl: newBaseUrl, providerForUrl: 'remote' } : {}),
    })
    say(t('model.ollama.downloaded', { model: pulled }), 'success')
  })

  useInbound('local_llm_install_progress', data => {
    const d = data as { message?: string }
    if (d.message) setInstallLog(log => [...log, d.message as string])
  })

  useInbound('local_llm_install', data => {
    const d = data as { success: boolean; error?: string }
    if (d.success) {
      setInstallPhase('idle')
      setInstallLog([])
      setOllamaLoading(true)
      send('ollama_models_get', { baseUrl: newBaseUrl || baseUrls['remote'] || undefined })
    } else {
      setInstallPhase('error')
      setInstallError(d.error || t('model.ollama.installFailed'))
    }
  })

  useInbound('slow_mode_set', data => {
    const d = data as { success: boolean; enabled: boolean; error?: string }
    if (d.success) say(d.enabled ? t('model.slow.enabled') : t('model.slow.disabled'), 'success')
    else say(d.error || t('model.slow.failed'), 'error')
  })

  useInbound('openrouter_models_get', data => {
    const d = data as { success: boolean; models?: OpenRouterModel[]; error?: string }
    setOrLoading(false)
    if (d.success && d.models) {
      setOrModels(d.models)
      setOrError(null)
    } else setOrError(d.error || t('model.or.loadFailed'))
  })

  useInbound('openrouter_credits_get', data => {
    const d = data as { success: boolean; balance?: number | null; label?: string | null; error?: string }
    if (d.success) {
      setCredits({ balance: d.balance ?? null, label: d.label ?? null })
      setCreditsError(null)
    } else {
      setCredits(null)
      setCreditsError(d.error || t('model.or.creditsFailed'))
    }
  })

  // ── Fetches that follow the selected provider ──

  useEffect(() => {
    if (!connected || provider !== 'remote') return
    setOllamaLoading(true)
    send('ollama_models_get', { baseUrl: baseUrls['remote'] || undefined })
  }, [provider, connected, baseUrls])

  useEffect(() => {
    setDiscovered([])
    if (!connected || !current?.has_model_discovery || current?.local_kind || provider === 'remote') return
    setDiscoveredLoading(true)
    send('provider_models_get', { provider, baseUrl: newBaseUrl || baseUrls[provider] || undefined, apiKey: newApiKey || undefined })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, connected, current?.has_model_discovery, current?.local_kind, baseUrls])

  const catalogWanted = !!current?.supports_catalog
  const orRequested = useRef<string | null>(null)
  useEffect(() => {
    if (!connected || !catalogWanted) return
    const key = orBaseUrl ?? ''
    if (orRequested.current === key) return
    orRequested.current = key
    setOrLoading(true)
    setOrError(null)
    send('openrouter_models_get', orBaseUrl ? { baseUrl: orBaseUrl } : {})
  }, [connected, catalogWanted, orBaseUrl])

  const hasOrKey = catalogWanted && !!apiKeys[provider]?.has_key
  useEffect(() => {
    if (!connected || !hasOrKey) {
      setCredits(null)
      return
    }
    send('openrouter_credits_get')
  }, [connected, hasOrKey])

  // Before the saved settings arrive, show the registry defaults.
  useEffect(() => {
    if (hasLoadedSettings) return
    const selected = providers.find(p => p.id === provider)
    if (selected && !llmModel) dispatch(setCurrentLlmModel(selected.llm_model || ''))
    if (selected && !vlmModel) dispatch(setCurrentVlmModel(selected.vlm_model || ''))
  }, [hasLoadedSettings, provider, providers, llmModel, vlmModel, dispatch])

  // ── Actions ──

  const changeProvider = (next: string) => {
    providerDraft.set(next)
    clearCredentials()
    setHasChanges(true)
    setTestResult(null)
    setInstallPhase('idle')
    setInstallLog([])
    setInstallError('')
    const selected = providers.find(p => p.id === next)
    llmDraft.set(selected?.llm_model || '')
    vlmDraft.set(selected?.vlm_model || '')
  }

  const testRequiresKey = !!current?.requires_api_key && !apiKeys[provider]?.has_key && !newApiKey.trim() && !subscriptionOauth[provider]?.connected

  const runTest = () => {
    setTesting(true)
    setTestResult(null)
    send('model_connection_test', {
      provider,
      apiKey: newApiKey || undefined,
      baseUrl: newBaseUrl || baseUrls[provider],
      model: llmModel || undefined,
      awsCredentials: awsPayload(),
    })
  }

  const runSave = () => {
    setTestResult(null)
    if (newApiKey || newBaseUrl || awsPayload()) {
      setTestBeforeSave(true)
      runTest()
    } else saveLlm()
  }

  const saveImage = () => {
    const effective = image.provider || imageGenProvider
    setImage(s => ({ ...s, saving: true }))
    savingSection.current = 'image'
    send('model_settings_update', {
      imageGenProvider: effective,
      imageGenModel: image.model || currentImageGenModel || undefined,
      ...(image.apiKey ? { apiKey: image.apiKey, providerForKey: effective } : {}),
    })
  }

  const saveVideo = () => {
    const effective = video.provider || videoGenProvider
    setVideo(s => ({ ...s, saving: true }))
    savingSection.current = 'video'
    send('model_settings_update', {
      videoGenProvider: effective,
      videoGenModel: video.model || currentVideoGenModel || undefined,
      ...(video.apiKey ? { apiKey: video.apiKey, providerForKey: effective } : {}),
    })
  }

  const signIn = () => {
    dispatch(setSubscriptionPending({ provider, pending: true }))
    // OpenAI and Claude finish through a local callback; the others end on a
    // page with a code to paste back. The backend opens the browser either way.
    const loopback = provider === 'openai' || provider === 'anthropic'
    send(loopback ? 'model_subscription_connect' : 'model_subscription_prepare', { provider })
    say(t('model.sub.opening', { provider: current?.name || provider }), 'muted')
  }

  const disconnect = () => {
    form.confirm(t('model.sub.disconnectConfirm', { provider: current?.name || provider }), () => {
      dispatch(setSubscriptionPending({ provider, pending: true }))
      send('model_subscription_disconnect', { provider })
    })
  }

  const reopen = async (url: string) => {
    const ok = await openInBrowser(url)
    say(ok ? t('model.sub.reopened') : t('model.sub.openFailed'), ok ? 'muted' : 'error')
  }

  // ── Rows ──

  const keyDetail = (id: string, optional = false) =>
    apiKeys[id]?.has_key ? t('model.key.configured') : optional ? t('model.key.optional') : t('model.key.required')

  const modelOptions: string[] = provider === 'remote' ? ollamaModels : current?.local_kind ? [] : discovered
  const modelsLoading = provider === 'remote' ? ollamaLoading : discoveredLoading

  const catalogOptions = (vision: boolean): ChoiceOption[] =>
    orModels
      .filter(m => !vision || m.input_modalities?.includes('image'))
      .map(m => ({
        value: m.id,
        label: m.id,
        detail: [contextLabel(m.context_length), isFree(m) ? t('model.or.free') : '', m.input_modalities?.includes('image') ? t('model.or.vision') : '']
          .filter(Boolean)
          .join(' · '),
      }))

  const modelRow = (id: 'llm' | 'vlm'): FormRow => {
    const draft = id === 'llm' ? llmDraft : vlmDraft
    const label = id === 'llm' ? t('model.llm') : t('model.vlm')
    const saved = id === 'llm' ? currentLlmModel : currentVlmModel
    let options: ChoiceOption[] = []
    if (current?.supports_catalog) options = catalogOptions(id === 'vlm')
    else if (id === 'vlm' && provider === 'remote') {
      const vision = ollamaModels.filter(m => VISION_HINTS.some(k => m.toLowerCase().includes(k)))
      options = (vision.length ? vision : ollamaModels).map(m => ({ value: m, label: m }))
    } else options = modelOptions.map(m => ({ value: m, label: m }))
    const loading = current?.supports_catalog ? orLoading : modelsLoading
    if (options.length) {
      if (draft.value && !options.some(o => o.value === draft.value)) options = [{ value: draft.value, label: draft.value }, ...options]
      return {
        kind: 'choice',
        id: `model.${id}`,
        label,
        value: draft.value,
        options,
        picker: true,
        pickerTitle: label,
        detail: draft.isDirty ? t('model.unsaved') : undefined,
        detailTone: 'warn',
        onChange: value => draft.set(value),
        onKey: current?.supports_catalog
          ? (input: string) => {
              if (input !== 'r') return false
              setOrLoading(true)
              send('openrouter_models_get', { ...(orBaseUrl ? { baseUrl: orBaseUrl } : {}), forceRefresh: true })
              return true
            }
          : undefined,
        hints: current?.supports_catalog ? [{ keys: 'r', label: t('hint.refresh') }] : [],
      }
    }
    return {
      kind: 'text',
      id: `model.${id}`,
      label,
      value: draft.value,
      placeholder: loading ? t('model.loadingModels') : saved || (id === 'llm' ? t('model.enterLlm') : t('model.enterVlm')),
      detail: current?.supports_catalog && orError ? orError : draft.isDirty ? t('model.unsaved') : undefined,
      detailTone: orError ? 'error' : 'warn',
      onSubmit: value => draft.set(value.trim()),
    }
  }

  const rows: FormRow[] = []
  if (!hasLoadedProviders) {
    rows.push({ kind: 'note', text: t('model.loading') })
  } else {
    rows.push({
      kind: 'choice',
      id: 'provider',
      label: t('model.provider'),
      value: provider,
      picker: true,
      pickerTitle: t('model.providerPicker'),
      options: providers.map(p => ({
        value: p.id,
        label: p.name,
        detail: subscriptionOauth[p.id]?.connected
          ? t('model.signedIn')
          : apiKeys[p.id]?.has_key
            ? t('model.key.configured')
            : p.local_kind || p.id === 'remote'
              ? t('model.local')
              : p.requires_api_key
                ? t('model.needsKey')
                : '',
      })),
      detail: providerDraft.isDirty ? t('model.unsaved') : undefined,
      detailTone: 'warn',
      onChange: changeProvider,
    })
    if (current) {
      rows.push(modelRow('llm'))
      if (provider === 'remote') rows.push(...ollamaRows())
      if (current.has_vlm) rows.push(modelRow('vlm'))
      rows.push(...authRows())
      if (current.supports_catalog) {
        rows.push({
          kind: 'info',
          label: t('model.or.credits'),
          value: creditsError
            ? t('model.or.creditsError', { error: creditsError })
            : credits
              ? credits.balance != null
                ? t('model.or.balance', { amount: credits.balance.toFixed(2) })
                : t('model.or.payAsYouGo')
              : hasOrKey
                ? t('model.or.creditsLoading')
                : t('model.or.creditsNoKey'),
          tone: creditsError ? 'error' : undefined,
          detail: credits?.label ?? undefined,
        })
      }
      if (current.is_bedrock) rows.push(...bedrockRows())
      if (current.base_url_env && provider !== 'bedrock') {
        rows.push({
          kind: 'text',
          id: 'baseUrl',
          label: t('model.serverUrl'),
          value: newBaseUrl || baseUrls[provider] || '',
          placeholder: current.default_base_url || t('model.enterBaseUrl'),
          detail: newBaseUrl ? t('model.unsaved') : undefined,
          detailTone: 'warn',
          onSubmit: value => {
            const next = value.trim()
            if (next === (baseUrls[provider] || '')) return
            setNewBaseUrl(next)
            setHasChanges(true)
          },
        })
      }
    }
    const dirty = hasChanges || providerDraft.isDirty || llmDraft.isDirty || vlmDraft.isDirty
    rows.push(
      {
        kind: 'action',
        id: 'test',
        label: testing && !testBeforeSave ? t('model.testing') : t('model.test'),
        disabled: testing || testRequiresKey,
        detail: testRequiresKey ? t('model.testNeedsKey') : undefined,
        onRun: runTest,
      },
      {
        kind: 'action',
        id: 'save',
        label: saving ? t('model.saving') : testing && testBeforeSave ? t('model.testingBeforeSave') : t('model.save'),
        tone: 'brand',
        disabled: saving || testing || !dirty,
        detail: dirty ? t('model.dirty') : t('model.clean'),
        detailTone: dirty ? 'warn' : 'muted',
        onRun: runSave,
      },
    )
    if (providerDraft.remoteChanged || llmDraft.remoteChanged || vlmDraft.remoteChanged) {
      rows.push({
        kind: 'action',
        id: 'loadLatest',
        label: t('changedElsewhereAction'),
        tone: 'warn',
        onRun: () => {
          providerDraft.acceptRemote()
          llmDraft.acceptRemote()
          vlmDraft.acceptRemote()
          clearCredentials()
          setHasChanges(false)
        },
      })
    }
    if (testResult) {
      const ok = testResult.success
      rows.push({
        kind: 'note',
        tone: ok ? 'success' : 'error',
        text: `${ok ? g.done : g.failed} ${ok ? (testBeforeSave ? t('model.testOkSaving') : t('model.testOk')) : t('model.testFailed')}: ${ok ? testResult.message : testResult.error || testResult.message}`,
        maxLines: 3,
      })
      if (ok && testResult.models?.length) rows.push({ kind: 'note', text: testResult.models.join(', '), maxLines: 2, indent: 4 })
      if (!ok && current?.openrouter_proxy) {
        rows.push({ kind: 'note', text: `${t('model.geoNote')} ${apiKeys['openrouter']?.has_key ? t('model.geoConfigured') : t('model.geoNotConfigured')}`, maxLines: 3, indent: 4 })
      }
    }

    rows.push({ kind: 'heading', text: t('model.image.title') }, ...genRows('image'))
    rows.push({ kind: 'heading', text: t('model.video.title') }, ...genRows('video'))
    rows.push(
      { kind: 'heading', text: t('model.other') },
      {
        kind: 'toggle',
        id: 'slowMode',
        label: t('model.slow.label'),
        value: slowMode,
        disabled: !hasLoadedSlowMode,
        detail: t('model.slow.desc'),
        onChange: enabled => {
          dispatch(setSlowModeEnabled(enabled))
          send('slow_mode_set', { enabled })
        },
      },
    )
  }

  function ollamaRows(): FormRow[] {
    const out: FormRow[] = []
    if (!ollamaLoading && ollamaAvailable === false) {
      if (installPhase === 'idle') {
        out.push(
          { kind: 'note', tone: 'warn', text: t('model.ollama.notDetected') },
          {
            kind: 'action',
            id: 'ollama.install',
            label: t('model.ollama.install'),
            tone: 'brand',
            onRun: () => {
              setInstallPhase('installing')
              setInstallLog([])
              send('local_llm_install')
            },
          },
          {
            kind: 'action',
            id: 'ollama.retry',
            label: t('model.ollama.retry'),
            onRun: () => {
              setOllamaLoading(true)
              dispatch(setOllamaModels({ models: [], available: false }))
              send('ollama_models_get', { baseUrl: newBaseUrl || baseUrls['remote'] || undefined })
            },
          },
        )
      } else if (installPhase === 'installing') {
        const pct = getOllamaInstallPercent(installLog)
        out.push(
          { kind: 'info', label: t('model.ollama.installing'), value: `${pct}%` },
          { kind: 'note', text: meter(pct / 100, Math.max(10, width - 8), null, g.vbar === '|' ? ASCII_METER : UNICODE_METER), tone: 'brand' },
          ...installLog.slice(-4).map((line): FormRow => ({ kind: 'note', text: line, maxLines: 1, indent: 4 })),
        )
      } else {
        out.push(
          { kind: 'note', tone: 'error', text: `${t('model.ollama.installFailed')}: ${installError}` },
          { kind: 'action', id: 'ollama.back', label: t('model.ollama.back'), onRun: () => { setInstallPhase('idle'); setInstallError('') } },
        )
      }
    }
    if (ollamaAvailable === true && pullPhase === 'idle') {
      out.push({
        kind: 'action',
        id: 'ollama.pull',
        label: t('model.ollama.downloadNew'),
        onRun: () => {
          setPullPhase('selecting')
          setPullBytes(null)
          setPullStatus('')
          if (!suggested.length) send('local_llm_suggested_models')
          form.select('ollama.pullModel')
        },
      })
    }
    if (pullPhase === 'selecting') {
      out.push(
        {
          kind: 'choice',
          id: 'ollama.pullModel',
          label: t('model.ollama.pullModel'),
          value: pullModel,
          display: suggested.length ? t('model.ollama.pick') : t('model.ollama.loadingList'),
          picker: true,
          pickerTitle: t('model.ollama.selectModel'),
          options: suggested.map(m => ({ value: m.name, label: m.label, detail: `${m.size}${m.recommended ? ` · ${t('model.ollama.recommended')}` : ''}` })),
          onChange: setPullModel,
        },
        {
          kind: 'action',
          id: 'ollama.download',
          label: t('model.ollama.download'),
          tone: 'brand',
          disabled: !pullModel,
          onRun: () => {
            setPullPhase('pulling')
            send('local_llm_pull_model', { model: pullModel, baseUrl: newBaseUrl || baseUrls['remote'] || undefined })
          },
        },
        { kind: 'action', id: 'ollama.cancelPull', label: t('model.ollama.cancel'), onRun: () => setPullPhase('idle') },
      )
    }
    if (pullPhase === 'pulling') {
      const pct = pullBytes?.percent ?? 0
      out.push(
        {
          kind: 'info',
          label: t('model.ollama.downloading'),
          value: pullModel,
          detail: pullBytes && pullBytes.total > 0 ? `${formatBytes(pullBytes.completed)} / ${formatBytes(pullBytes.total)} · ${pct}%` : undefined,
        },
        { kind: 'note', text: meter(pct / 100, Math.max(10, width - 8), null, g.vbar === '|' ? ASCII_METER : UNICODE_METER), tone: 'brand' },
        { kind: 'note', text: pullStatus || t('model.ollama.starting'), maxLines: 1, indent: 4 },
      )
    }
    return out
  }

  function authRows(): FormRow[] {
    if (!current) return []
    const out: FormRow[] = []
    const supportsSub = !!current.supports_subscription_oauth
    const status = subscriptionOauth[provider]
    const subConnected = !!status?.connected
    const pending = !!subscriptionPending[provider]
    const pb = subscriptionPasteback[provider]
    const hasKey = !!apiKeys[provider]?.has_key
    const requiresKey = !!current.requires_api_key
    const keyExpanded = apiKeyExpanded[provider] ?? (!subConnected || hasKey)

    if (supportsSub) {
      if (provider === 'anthropic') out.push({ kind: 'note', text: t('model.sub.claudeNote'), maxLines: 3 })
      if (subConnected) {
        out.push({
          kind: 'action',
          id: 'sub.disconnect',
          label: t('model.sub.disconnect'),
          disabled: pending,
          detail: [t('model.sub.connectedAs'), status?.email, status?.plan].filter(Boolean).join(' · '),
          detailTone: 'success',
          onRun: disconnect,
        })
      } else if (pb?.awaiting) {
        out.push({
          kind: 'text',
          id: 'sub.code',
          label: t('model.sub.code'),
          value: pasteCode[provider] ?? '',
          placeholder: t('model.sub.codePlaceholder'),
          disabled: pending,
          detail: pending ? t('model.sub.checking') : undefined,
          onSubmit: value => {
            const code = value.trim()
            setPasteCode(m => ({ ...m, [provider]: code }))
            if (!code) return
            dispatch(setSubscriptionPending({ provider, pending: true }))
            send('model_subscription_complete', { provider, code, attemptId: pb.attemptId })
          },
        })
        if (pb.authUrl) {
          const url = pb.authUrl
          out.push(
            { kind: 'action', id: 'sub.open', label: t('model.sub.reopen'), onRun: () => void reopen(url) },
            { kind: 'note', text: t('model.sub.urlNote'), maxLines: 1 },
            { kind: 'note', text: url, indent: 4, maxLines: 4 },
          )
        }
        out.push({
          kind: 'action',
          id: 'sub.cancel',
          label: t('model.sub.cancel'),
          disabled: pending,
          onRun: () => {
            dispatch(clearSubscriptionPasteback(provider))
            setPasteCode(m => ({ ...m, [provider]: '' }))
          },
        })
        if (pb.errorMessage) out.push({ kind: 'note', tone: 'error', text: pb.errorMessage, maxLines: 3 })
      } else {
        out.push({
          kind: 'action',
          id: 'sub.signIn',
          label: pending ? t('model.sub.waiting') : current.subscription_label || t('model.sub.signInWith', { provider: current.name }),
          tone: 'brand',
          disabled: pending,
          detail: t('model.sub.signInDetail'),
          onRun: signIn,
        })
        if (pb?.errorMessage) out.push({ kind: 'note', tone: 'error', text: pb.errorMessage, maxLines: 3 })
      }
      if (!subConnected && status?.configured) {
        out.push(
          { kind: 'note', text: t('model.sub.recovery'), maxLines: 2 },
          { kind: 'action', id: 'sub.reset', label: t('model.sub.disconnect'), disabled: pending, onRun: disconnect },
        )
      }
      if (status?.error) out.push({ kind: 'note', tone: 'error', text: status.error, maxLines: 2 })
      if (subConnected && !keyExpanded && requiresKey) {
        out.push({ kind: 'action', id: 'key.expand', label: t('model.sub.useKey'), onRun: () => setApiKeyExpanded(m => ({ ...m, [provider]: true })) })
        return out
      }
    }
    if (requiresKey) {
      out.push({
        kind: 'text',
        id: 'apiKey',
        label: t('model.key.label'),
        value: newApiKey,
        masked: true,
        startEmpty: true,
        display: newApiKey ? '•'.repeat(Math.min(12, newApiKey.length)) : hasKey ? apiKeys[provider].masked_key : '',
        placeholder: hasKey ? t('model.key.replace') : t('model.key.enter'),
        detail: newApiKey ? t('model.unsaved') : keyDetail(provider, subConnected),
        detailTone: newApiKey ? 'warn' : hasKey ? 'success' : subConnected ? 'muted' : 'warn',
        onSubmit: value => {
          const key = value.trim()
          if (!key) return
          setNewApiKey(key)
          setHasChanges(true)
        },
        onKey: newApiKey
          ? (input: string) => {
              if (input !== 'x') return false
              setNewApiKey('')
              return true
            }
          : undefined,
        hints: newApiKey ? [{ keys: 'x', label: t('hint.discard') }] : [],
      })
      if (current.openrouter_proxy) {
        out.push({ kind: 'note', text: apiKeys['openrouter']?.has_key ? t('model.key.proxyConfigured') : t('model.key.proxyFallback'), maxLines: 3 })
      }
    }
    return out
  }

  function bedrockRows(): FormRow[] {
    const setField = (field: keyof typeof aws) => (value: string) => {
      setAws(a => ({ ...a, [field]: value.trim() }))
      setHasChanges(true)
    }
    return [
      {
        kind: 'text',
        id: 'aws.id',
        label: t('model.aws.accessKeyId'),
        value: aws.accessKeyId,
        display: aws.accessKeyId || awsStatus?.masked_access_key_id || '',
        startEmpty: true,
        placeholder: awsStatus?.has_access_key_id ? t('model.aws.replace') : 'AKIA...',
        detail: awsStatus?.has_access_key_id ? t('model.key.configured') : t('model.key.optional'),
        onSubmit: setField('accessKeyId'),
      },
      {
        kind: 'text',
        id: 'aws.secret',
        label: t('model.aws.secret'),
        value: aws.secret,
        masked: true,
        startEmpty: true,
        display: aws.secret ? '•'.repeat(12) : '',
        placeholder: awsStatus?.has_secret_access_key ? t('model.aws.replace') : t('model.aws.secretEnter'),
        detail: awsStatus?.has_secret_access_key ? t('model.key.configured') : undefined,
        onSubmit: setField('secret'),
      },
      {
        kind: 'text',
        id: 'aws.session',
        label: t('model.aws.session'),
        value: aws.session,
        masked: true,
        startEmpty: true,
        display: aws.session ? '•'.repeat(12) : '',
        placeholder: t('model.aws.sessionPlaceholder'),
        onSubmit: setField('session'),
      },
      {
        kind: 'text',
        id: 'aws.region',
        label: t('model.aws.region'),
        value: aws.region || awsStatus?.region || baseUrls['bedrock'] || '',
        placeholder: 'us-east-1',
        onSubmit: setField('region'),
      },
      { kind: 'note', text: t('model.aws.note'), maxLines: 2 },
    ]
  }

  function genRows(kind: 'image' | 'video'): FormRow[] {
    const state = kind === 'image' ? image : video
    const setState = kind === 'image' ? setImage : setVideo
    const list = providers.filter(p => (kind === 'image' ? p.has_image_gen : p.has_video_gen))
    const effective = state.provider || (kind === 'image' ? imageGenProvider : videoGenProvider)
    const info = list.find(p => p.id === effective)
    const savedModel = kind === 'image' ? currentImageGenModel : currentVideoGenModel
    const out: FormRow[] = [
      {
        kind: 'choice',
        id: `${kind}.provider`,
        label: t('model.provider'),
        value: effective,
        picker: true,
        pickerTitle: kind === 'image' ? t('model.image.picker') : t('model.video.picker'),
        options: list.map(p => ({ value: p.id, label: p.name, detail: apiKeys[p.id]?.has_key ? t('model.key.configured') : '' })),
        onChange: value => {
          const sel = list.find(p => p.id === value)
          setState({ provider: value, model: (kind === 'image' ? sel?.image_gen_model : sel?.video_gen_model) || '', apiKey: '', changed: true, saving: false })
        },
      },
    ]
    if (info?.requires_api_key) {
      out.push({
        kind: 'text',
        id: `${kind}.apiKey`,
        label: t('model.key.label'),
        value: state.apiKey,
        masked: true,
        startEmpty: true,
        display: state.apiKey ? '•'.repeat(12) : apiKeys[effective]?.has_key ? apiKeys[effective].masked_key : '',
        placeholder: apiKeys[effective]?.has_key ? t('model.key.replace') : t('model.key.enter'),
        detail: state.apiKey ? t('model.unsaved') : keyDetail(effective),
        detailTone: state.apiKey ? 'warn' : apiKeys[effective]?.has_key ? 'success' : 'warn',
        onSubmit: value => value.trim() && setState(s => ({ ...s, apiKey: value.trim(), changed: true })),
      })
    }
    out.push(
      {
        kind: 'text',
        id: `${kind}.model`,
        label: t('model.modelLabel'),
        value: state.model || savedModel || '',
        placeholder: (kind === 'image' ? info?.image_gen_model : info?.video_gen_model) || t('model.defaultModel'),
        onSubmit: value => setState(s => ({ ...s, model: value.trim(), changed: true })),
      },
      {
        kind: 'action',
        id: `${kind}.save`,
        label: state.saving ? t('model.saving') : kind === 'image' ? t('model.image.save') : t('model.video.save'),
        tone: 'brand',
        disabled: state.saving || !state.changed,
        detail: state.changed ? t('model.dirty') : undefined,
        detailTone: 'warn',
        onRun: kind === 'image' ? saveImage : saveVideo,
      },
    )
    return out
  }

  useTabKeys((input, key) => form.handleKey(rows, input, key))

  return <FormView form={form} rows={rows} width={width} height={height} active={active} flash={flash} />
}
