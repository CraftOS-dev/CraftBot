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
  has_vlm: boolean
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
  apiKeys: Record<string, ApiKeyStatus>
  baseUrls: Record<string, string>
  currentLlmModel: string
  currentVlmModel: string
  slowModeEnabled: boolean
  awsCredentials: AwsCredentialsStatus | null
  hasLoadedProviders: boolean
  hasLoadedSettings: boolean
  hasLoadedSlowMode: boolean
}

const initialState: ModelSettingsState = {
  providers: [],
  provider: 'anthropic',
  apiKeys: {},
  baseUrls: {},
  currentLlmModel: '',
  currentVlmModel: '',
  slowModeEnabled: false,
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
      llmModel: string
      vlmModel: string
      apiKeys: Record<string, ApiKeyStatus>
      baseUrls: Record<string, string>
      awsCredentials?: AwsCredentialsStatus | null
    }>) {
      state.provider = action.payload.provider
      state.currentLlmModel = action.payload.llmModel
      state.currentVlmModel = action.payload.vlmModel
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
    setCurrentLlmModel(state, action: PayloadAction<string>) {
      state.currentLlmModel = action.payload
    },
    setCurrentVlmModel(state, action: PayloadAction<string>) {
      state.currentVlmModel = action.payload
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
  },
})

export const {
  setProviders,
  setSettings,
  setProvider,
  setCurrentLlmModel,
  setCurrentVlmModel,
  setApiKeys,
  setBaseUrls,
  setSlowModeEnabled,
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
    llm_model: string | null
    vlm_model: string | null
    api_keys: Record<string, ApiKeyStatus>
    base_urls: Record<string, string>
    aws_credentials?: AwsCredentialsStatus | null
  }
  if (d.success) {
    dispatch(setSettings({
      provider: d.llm_provider || 'anthropic',
      llmModel: d.llm_model || '',
      vlmModel: d.vlm_model || '',
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
    llm_model?: string | null
    vlm_model?: string | null
    api_keys?: Record<string, ApiKeyStatus>
    base_urls?: Record<string, string>
    aws_credentials?: AwsCredentialsStatus | null
  }
  if (!d.success) return
  if (d.llm_provider) dispatch(setProvider(d.llm_provider))
  if (d.api_keys) dispatch(setApiKeys(d.api_keys))
  if (d.base_urls) dispatch(setBaseUrls(d.base_urls))
  if (d.llm_model !== undefined) dispatch(setCurrentLlmModel(d.llm_model || ''))
  if (d.vlm_model !== undefined) dispatch(setCurrentVlmModel(d.vlm_model || ''))
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
