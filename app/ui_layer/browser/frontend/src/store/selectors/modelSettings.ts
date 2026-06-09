import type { RootState } from '../index'

export const selectModelProviders = (state: RootState) => state.modelSettings.providers
export const selectModelProvider = (state: RootState) => state.modelSettings.provider
export const selectApiKeys = (state: RootState) => state.modelSettings.apiKeys
export const selectBaseUrls = (state: RootState) => state.modelSettings.baseUrls
export const selectCurrentLlmModel = (state: RootState) => state.modelSettings.currentLlmModel
export const selectCurrentVlmModel = (state: RootState) => state.modelSettings.currentVlmModel
export const selectImageGenProvider = (state: RootState) => state.modelSettings.imageGenProvider
export const selectCurrentImageGenModel = (state: RootState) => state.modelSettings.currentImageGenModel
export const selectVideoGenProvider = (state: RootState) => state.modelSettings.videoGenProvider
export const selectCurrentVideoGenModel = (state: RootState) => state.modelSettings.currentVideoGenModel
export const selectSlowModeEnabled = (state: RootState) => state.modelSettings.slowModeEnabled
export const selectOllamaModels = (state: RootState) => state.modelSettings.ollamaModels
export const selectOllamaAvailable = (state: RootState) => state.modelSettings.ollamaAvailable
export const selectAwsCredentials = (state: RootState) => state.modelSettings.awsCredentials
export const selectModelHasLoadedProviders = (state: RootState) => state.modelSettings.hasLoadedProviders
export const selectModelHasLoadedSettings = (state: RootState) => state.modelSettings.hasLoadedSettings
export const selectModelHasLoadedSlowMode = (state: RootState) => state.modelSettings.hasLoadedSlowMode
