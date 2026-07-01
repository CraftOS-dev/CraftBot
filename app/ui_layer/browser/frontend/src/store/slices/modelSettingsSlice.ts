import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

export interface ProviderInfo {
  id: string
  name: string
  requires_api_key: boolean
  api_key_env?: string
  base_url_env?: string
  llm_model: string | null
  vlm_model: string | null
  image_gen_model: string | null
  video_gen_model: string | null
  has_vlm: boolean
  has_image_gen: boolean
  has_video_gen: boolean
  supports_catalog?: boolean
  is_bedrock?: boolean
  // Subscription OAuth (ChatGPT Plus/Pro, SuperGrok). When true the
  // settings page shows a "Sign in with <provider>" button next to the
  // API-key field. Anthropic is intentionally absent.
  supports_subscription_oauth?: boolean
  subscription_label?: string | null
  subscription_models?: string[]
}

// One entry per provider that supports subscription OAuth. The backend
// includes only providers where supports_subscription_oauth=true.
export interface SubscriptionStatus {
  supported: boolean
  connected: boolean
  email?: string
  plan?: string
  expires_at?: number
  expires_in_seconds?: number
}

export interface ApiKeyStatus {
  has_key: boolean
  masked_key: string
}

export interface AwsCredentialsStatus {
  has_access_key_id: boolean
  has_secret_access_key: boolean
  has_session_token: boolean
  masked_access_key_id: string
  region: string
}

// Per-provider paste-back state. Once `attempt_id` is set, the UI knows the
// user has clicked Connect and is now waiting to either complete the loopback
// flow (silent success) or paste a code from the provider's "copy this code"
// page (paste-back flow). Cleared on successful connect.
export interface PastebackState {
  awaiting: boolean
  attemptId?: string
  authUrl?: string
  errorMessage?: string
}

interface ModelSettingsState {
  providers: ProviderInfo[]
  provider: string
  imageGenProvider: string
  videoGenProvider: string
  apiKeys: Record<string, ApiKeyStatus>
  baseUrls: Record<string, string>
  currentLlmModel: string
  currentVlmModel: string
  currentImageGenModel: string
  currentVideoGenModel: string
  slowModeEnabled: boolean
  ollamaModels: string[]
  ollamaAvailable: boolean | null
  awsCredentials: AwsCredentialsStatus | null
  subscriptionOauth: Record<string, SubscriptionStatus>
  subscriptionPending: Record<string, boolean>
  subscriptionPasteback: Record<string, PastebackState>
  hasLoadedProviders: boolean
  hasLoadedSettings: boolean
  hasLoadedSlowMode: boolean
}

const initialState: ModelSettingsState = {
  providers: [],
  provider: 'anthropic',
  imageGenProvider: 'openai',
  videoGenProvider: 'gemini',
  apiKeys: {},
  baseUrls: {},
  currentLlmModel: '',
  currentVlmModel: '',
  currentImageGenModel: '',
  currentVideoGenModel: '',
  slowModeEnabled: false,
  ollamaModels: [],
  ollamaAvailable: null,
  awsCredentials: null,
  subscriptionOauth: {},
  subscriptionPending: {},
  subscriptionPasteback: {},
  hasLoadedProviders: false,
  hasLoadedSettings: false,
  hasLoadedSlowMode: false,
}

const modelSettingsSlice = createSlice({
  name: 'modelSettings',
  initialState,
  reducers: {
    setProviders(state, action: PayloadAction<ProviderInfo[]>) {
      state.providers = action.payload
      state.hasLoadedProviders = true
    },
    setSettings(state, action: PayloadAction<{
      provider: string
      imageGenProvider: string
      videoGenProvider: string
      llmModel: string
      vlmModel: string
      imageGenModel: string
      videoGenModel: string
      apiKeys: Record<string, ApiKeyStatus>
      baseUrls: Record<string, string>
      awsCredentials?: AwsCredentialsStatus | null
    }>) {
      state.provider = action.payload.provider
      state.imageGenProvider = action.payload.imageGenProvider
      state.videoGenProvider = action.payload.videoGenProvider
      state.currentLlmModel = action.payload.llmModel
      state.currentVlmModel = action.payload.vlmModel
      state.currentImageGenModel = action.payload.imageGenModel
      state.currentVideoGenModel = action.payload.videoGenModel
      state.apiKeys = action.payload.apiKeys
      state.baseUrls = action.payload.baseUrls
      if (action.payload.awsCredentials !== undefined) {
        state.awsCredentials = action.payload.awsCredentials
      }
      state.hasLoadedSettings = true
    },
    setAwsCredentials(state, action: PayloadAction<AwsCredentialsStatus | null>) {
      state.awsCredentials = action.payload
    },
    setProvider(state, action: PayloadAction<string>) {
      state.provider = action.payload
    },
    setImageGenProvider(state, action: PayloadAction<string>) {
      state.imageGenProvider = action.payload
    },
    setCurrentLlmModel(state, action: PayloadAction<string>) {
      state.currentLlmModel = action.payload
    },
    setCurrentVlmModel(state, action: PayloadAction<string>) {
      state.currentVlmModel = action.payload
    },
    setCurrentImageGenModel(state, action: PayloadAction<string>) {
      state.currentImageGenModel = action.payload
    },
    setVideoGenProvider(state, action: PayloadAction<string>) {
      state.videoGenProvider = action.payload
    },
    setCurrentVideoGenModel(state, action: PayloadAction<string>) {
      state.currentVideoGenModel = action.payload
    },
    setApiKeys(state, action: PayloadAction<Record<string, ApiKeyStatus>>) {
      state.apiKeys = action.payload
    },
    setBaseUrls(state, action: PayloadAction<Record<string, string>>) {
      state.baseUrls = action.payload
    },
    setSlowModeEnabled(state, action: PayloadAction<boolean>) {
      state.slowModeEnabled = action.payload
      state.hasLoadedSlowMode = true
    },
    setOllamaModels(state, action: PayloadAction<{ models: string[]; available: boolean }>) {
      state.ollamaModels = action.payload.models
      state.ollamaAvailable = action.payload.available
    },
    setSubscriptionOauth(state, action: PayloadAction<Record<string, SubscriptionStatus>>) {
      state.subscriptionOauth = action.payload
    },
    setSubscriptionStatus(state, action: PayloadAction<{ provider: string; status: SubscriptionStatus }>) {
      state.subscriptionOauth[action.payload.provider] = action.payload.status
    },
    setSubscriptionPending(state, action: PayloadAction<{ provider: string; pending: boolean }>) {
      state.subscriptionPending[action.payload.provider] = action.payload.pending
    },
    setSubscriptionPasteback(state, action: PayloadAction<{ provider: string; state: PastebackState }>) {
      state.subscriptionPasteback[action.payload.provider] = action.payload.state
    },
    clearSubscriptionPasteback(state, action: PayloadAction<string>) {
      delete state.subscriptionPasteback[action.payload]
    },
  },
})

export const {
  setProviders,
  setSettings,
  setProvider,
  setImageGenProvider,
  setVideoGenProvider,
  setCurrentLlmModel,
  setCurrentVlmModel,
  setCurrentImageGenModel,
  setCurrentVideoGenModel,
  setApiKeys,
  setBaseUrls,
  setSlowModeEnabled,
  setOllamaModels,
  setAwsCredentials,
  setSubscriptionOauth,
  setSubscriptionStatus,
  setSubscriptionPending,
  setSubscriptionPasteback,
  clearSubscriptionPasteback,
} = modelSettingsSlice.actions

export default modelSettingsSlice.reducer

register('model_providers_get', (data, dispatch) => {
  const d = data as { success: boolean; providers: ProviderInfo[] }
  if (d.success && d.providers) dispatch(setProviders(d.providers))
})

register('model_settings_get', (data, dispatch) => {
  const d = data as {
    success: boolean
    llm_provider: string
    image_gen_provider: string
    video_gen_provider: string
    llm_model: string | null
    vlm_model: string | null
    image_gen_model: string | null
    video_gen_model: string | null
    api_keys: Record<string, ApiKeyStatus>
    base_urls: Record<string, string>
    aws_credentials?: AwsCredentialsStatus | null
    subscription_oauth?: Record<string, SubscriptionStatus>
  }
  if (d.success) {
    dispatch(setSettings({
      provider: d.llm_provider || 'anthropic',
      imageGenProvider: d.image_gen_provider || 'openai',
      videoGenProvider: d.video_gen_provider || 'gemini',
      llmModel: d.llm_model || '',
      vlmModel: d.vlm_model || '',
      imageGenModel: d.image_gen_model || '',
      videoGenModel: d.video_gen_model || '',
      apiKeys: d.api_keys || {},
      baseUrls: d.base_urls || {},
      awsCredentials: d.aws_credentials ?? null,
    }))
    if (d.subscription_oauth) {
      dispatch(setSubscriptionOauth(d.subscription_oauth))
    }
  }
})

register('model_settings_update', (data, dispatch) => {
  const d = data as {
    success: boolean
    llm_provider?: string
    image_gen_provider?: string
    video_gen_provider?: string
    llm_model?: string | null
    vlm_model?: string | null
    image_gen_model?: string | null
    video_gen_model?: string | null
    api_keys?: Record<string, ApiKeyStatus>
    base_urls?: Record<string, string>
    aws_credentials?: AwsCredentialsStatus | null
  }
  if (!d.success) return
  if (d.llm_provider) dispatch(setProvider(d.llm_provider))
  // Always update imageGenProvider/videoGenProvider when present (even on partial saves);
  // using `!== undefined` so version-mismatched backends that omit the field don't
  // silently leave the UI showing a stale provider.
  if (d.image_gen_provider !== undefined) dispatch(setImageGenProvider(d.image_gen_provider || 'openai'))
  if (d.video_gen_provider !== undefined) dispatch(setVideoGenProvider(d.video_gen_provider || 'gemini'))
  if (d.api_keys) dispatch(setApiKeys(d.api_keys))
  if (d.base_urls) dispatch(setBaseUrls(d.base_urls))
  if (d.llm_model !== undefined) dispatch(setCurrentLlmModel(d.llm_model || ''))
  if (d.vlm_model !== undefined) dispatch(setCurrentVlmModel(d.vlm_model || ''))
  if (d.image_gen_model !== undefined) dispatch(setCurrentImageGenModel(d.image_gen_model || ''))
  if (d.video_gen_model !== undefined) dispatch(setCurrentVideoGenModel(d.video_gen_model || ''))
  if (d.aws_credentials !== undefined) dispatch(setAwsCredentials(d.aws_credentials))
})

register('slow_mode_get', (data, dispatch) => {
  const d = data as { success: boolean; enabled: boolean }
  if (d.success) dispatch(setSlowModeEnabled(d.enabled))
})

register('slow_mode_set', (data, dispatch) => {
  const d = data as { success: boolean; enabled: boolean }
  if (d.success) dispatch(setSlowModeEnabled(d.enabled))
})

register('ollama_models_get', (data, dispatch) => {
  const d = data as { success: boolean; models: string[] }
  dispatch(setOllamaModels({ models: d.success ? (d.models || []) : [], available: d.success }))
})

// Subscription OAuth (ChatGPT Plus/Pro, SuperGrok)
register('model_subscription_connect', (data, dispatch) => {
  const d = data as { success: boolean; provider?: string; status?: SubscriptionStatus; message?: string; error?: string }
  if (d.provider) {
    dispatch(setSubscriptionPending({ provider: d.provider, pending: false }))
    if (d.status) dispatch(setSubscriptionStatus({ provider: d.provider, status: d.status }))
  }
})

register('model_subscription_disconnect', (data, dispatch) => {
  const d = data as { success: boolean; provider?: string; status?: SubscriptionStatus }
  if (d.provider) {
    dispatch(setSubscriptionPending({ provider: d.provider, pending: false }))
    if (d.status) dispatch(setSubscriptionStatus({ provider: d.provider, status: d.status }))
  }
})

register('model_subscription_status', (data, dispatch) => {
  const d = data as { success: boolean; provider?: string; status?: SubscriptionStatus }
  if (d.success && d.provider && d.status) {
    dispatch(setSubscriptionStatus({ provider: d.provider, status: d.status }))
  }
})

register('model_subscription_prepare', (data, dispatch) => {
  const d = data as { success: boolean; provider?: string; auth_url?: string; attempt_id?: string; error?: string }
  if (!d.provider) return
  dispatch(setSubscriptionPending({ provider: d.provider, pending: false }))
  if (d.success) {
    dispatch(setSubscriptionPasteback({
      provider: d.provider,
      state: { awaiting: true, attemptId: d.attempt_id, authUrl: d.auth_url },
    }))
  } else {
    dispatch(setSubscriptionPasteback({
      provider: d.provider,
      state: { awaiting: false, errorMessage: d.error || 'Failed to prepare sign-in' },
    }))
  }
})

register('model_subscription_complete', (data, dispatch) => {
  const d = data as { success: boolean; provider?: string; status?: SubscriptionStatus; message?: string; error?: string }
  if (!d.provider) return
  dispatch(setSubscriptionPending({ provider: d.provider, pending: false }))
  if (d.success) {
    if (d.status) dispatch(setSubscriptionStatus({ provider: d.provider, status: d.status }))
    dispatch(clearSubscriptionPasteback(d.provider))
  } else {
    dispatch(setSubscriptionPasteback({
      provider: d.provider,
      state: { awaiting: true, errorMessage: d.error || d.message || 'Code exchange failed' },
    }))
  }
})
