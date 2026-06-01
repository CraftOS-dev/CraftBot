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
  has_vlm: boolean
  has_image_gen: boolean
  supports_catalog?: boolean
  is_bedrock?: boolean
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

interface ModelSettingsState {
  providers: ProviderInfo[]
  provider: string
  imageGenProvider: string
  apiKeys: Record<string, ApiKeyStatus>
  baseUrls: Record<string, string>
  currentLlmModel: string
  currentVlmModel: string
  currentImageGenModel: string
  slowModeEnabled: boolean
  ollamaModels: string[]
  ollamaAvailable: boolean | null
  awsCredentials: AwsCredentialsStatus | null
  hasLoadedProviders: boolean
  hasLoadedSettings: boolean
  hasLoadedSlowMode: boolean
}

const initialState: ModelSettingsState = {
  providers: [],
  provider: 'anthropic',
  imageGenProvider: 'openai',
  apiKeys: {},
  baseUrls: {},
  currentLlmModel: '',
  currentVlmModel: '',
  currentImageGenModel: '',
  slowModeEnabled: false,
  ollamaModels: [],
  ollamaAvailable: null,
  awsCredentials: null,
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
      llmModel: string
      vlmModel: string
      imageGenModel: string
      apiKeys: Record<string, ApiKeyStatus>
      baseUrls: Record<string, string>
      awsCredentials?: AwsCredentialsStatus | null
    }>) {
      state.provider = action.payload.provider
      state.imageGenProvider = action.payload.imageGenProvider
      state.currentLlmModel = action.payload.llmModel
      state.currentVlmModel = action.payload.vlmModel
      state.currentImageGenModel = action.payload.imageGenModel
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
  },
})

export const {
  setProviders,
  setSettings,
  setProvider,
  setImageGenProvider,
  setCurrentLlmModel,
  setCurrentVlmModel,
  setCurrentImageGenModel,
  setApiKeys,
  setBaseUrls,
  setSlowModeEnabled,
  setOllamaModels,
  setAwsCredentials,
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
    llm_model: string | null
    vlm_model: string | null
    image_gen_model: string | null
    api_keys: Record<string, ApiKeyStatus>
    base_urls: Record<string, string>
    aws_credentials?: AwsCredentialsStatus | null
  }
  if (d.success) {
    dispatch(setSettings({
      provider: d.llm_provider || 'anthropic',
      imageGenProvider: d.image_gen_provider || 'openai',
      llmModel: d.llm_model || '',
      vlmModel: d.vlm_model || '',
      imageGenModel: d.image_gen_model || '',
      apiKeys: d.api_keys || {},
      baseUrls: d.base_urls || {},
      awsCredentials: d.aws_credentials ?? null,
    }))
  }
})

register('model_settings_update', (data, dispatch) => {
  const d = data as {
    success: boolean
    llm_provider?: string
    image_gen_provider?: string
    llm_model?: string | null
    vlm_model?: string | null
    image_gen_model?: string | null
    api_keys?: Record<string, ApiKeyStatus>
    base_urls?: Record<string, string>
    aws_credentials?: AwsCredentialsStatus | null
  }
  if (!d.success) return
  if (d.llm_provider) dispatch(setProvider(d.llm_provider))
  // Always update imageGenProvider when the field is present (even on partial saves);
  // using `!== undefined` mirrors model_settings_get so version-mismatched backends
  // that omit the field don't silently leave the UI showing a stale provider.
  if (d.image_gen_provider !== undefined) dispatch(setImageGenProvider(d.image_gen_provider || 'openai'))
  if (d.api_keys) dispatch(setApiKeys(d.api_keys))
  if (d.base_urls) dispatch(setBaseUrls(d.base_urls))
  if (d.llm_model !== undefined) dispatch(setCurrentLlmModel(d.llm_model || ''))
  if (d.vlm_model !== undefined) dispatch(setCurrentVlmModel(d.vlm_model || ''))
  if (d.image_gen_model !== undefined) dispatch(setCurrentImageGenModel(d.image_gen_model || ''))
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
