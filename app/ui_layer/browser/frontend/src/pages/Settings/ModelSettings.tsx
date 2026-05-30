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
} from '../../store/slices/modelSettingsSlice'
import {
  selectModelProviders,
  selectModelProvider,
  selectApiKeys,
  selectBaseUrls,
  selectCurrentLlmModel as selectCurrentLlmModelSel,
  selectCurrentVlmModel as selectCurrentVlmModelSel,
  selectSlowModeEnabled,
  selectAwsCredentials,
  selectModelHasLoadedProviders,
  selectModelHasLoadedSettings,
  selectModelHasLoadedSlowMode,
} from '../../store/selectors/modelSettings'
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
  is_bedrock?: boolean
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
  const awsCredentialsStatus = useAppSelector(selectAwsCredentials)
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

  // Bedrock-specific form state — AWS credentials don't fit the api_key shape
  // (multiple fields). All four are blank until the user fills them in;
  // unchanged values fall through to whatever is already in settings.json.
  const [newAwsAccessKeyId, setNewAwsAccessKeyId] = useState('')
  const [newAwsSecretAccessKey, setNewAwsSecretAccessKey] = useState('')
  const [newAwsSessionToken, setNewAwsSessionToken] = useState('')
  const [newAwsRegion, setNewAwsRegion] = useState('')

  // UI state (transient — local).
  const [isSaving, setIsSaving] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [testBeforeSave, setTestBeforeSave] = useState(false)

  // OpenRouter catalog — fetched once on first OpenRouter selection,
  // shared between the LLM and VLM pickers below.
  const orCatalog = useOpenRouterCatalog(
    send,
    onMessage,
    isConnected,
    provider === 'openrouter',
    newBaseUrl || baseUrls['openrouter'] || undefined,
  )

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
          setNewAwsAccessKeyId('')
          setNewAwsSecretAccessKey('')
          setNewAwsSessionToken('')
          setNewAwsRegion('')
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
      onMessage('slow_mode_set', (data: unknown) => {
        const d = data as { success: boolean; enabled: boolean; error?: string }
        if (d.success) {
          showToast('success', `Slow mode ${d.enabled ? 'enabled' : 'disabled'}`)
        } else {
          showToast('error', d.error || 'Failed to update slow mode')
        }
      }),
    ]

    return () => cleanups.forEach(cleanup => cleanup())
  }, [isConnected, onMessage, send, dispatch, testBeforeSave, provider, newApiKey, newBaseUrl, baseUrls, currentLlmModel, currentVlmModel, showToast, newAwsAccessKeyId, newAwsSecretAccessKey, newAwsSessionToken, newAwsRegion, newLlmModel, newVlmModel])

  // Load initial data only once when connected, cached across remounts.
  useEffect(() => {
    if (!isConnected) return
    if (!hasLoadedProviders) send('model_providers_get')
    if (!hasLoadedSettings) send('model_settings_get')
    if (!hasLoadedSlowMode) send('slow_mode_get')
  }, [isConnected, send, hasLoadedProviders, hasLoadedSettings, hasLoadedSlowMode])

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
    setNewAwsAccessKeyId('')
    setNewAwsSecretAccessKey('')
    setNewAwsSessionToken('')
    setNewAwsRegion('')
    setHasChanges(true)
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
                  <input
                    type="text"
                    value={newLlmModel || currentLlmModel || ''}
                    onChange={(e) => { setNewLlmModel(e.target.value); setHasChanges(true) }}
                    placeholder={currentLlmModel || 'Enter LLM model name...'}
                  />
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
                  <input
                    type="text"
                    value={newVlmModel || currentVlmModel || ''}
                    onChange={(e) => { setNewVlmModel(e.target.value); setHasChanges(true) }}
                    placeholder={currentVlmModel || 'Enter VLM model name...'}
                  />
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

          {/* AWS Bedrock credentials */}
          {provider === 'bedrock' && currentProvider?.is_bedrock && (
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
                placeholder="Enter base URL..."
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
                (provider !== 'bedrock' && !apiKeys[provider]?.has_key)
              }
              title={
                provider !== 'bedrock' && !apiKeys[provider]?.has_key
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
