import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type {
  LocalLLMState,
  LocalLLMCheckResponse,
  LocalLLMTestResponse,
  LocalLLMInstallResponse,
  LocalLLMProgressResponse,
  LocalLLMPullProgressResponse,
  SuggestedModel,
} from '../../types'
import i18n from '../../i18n/config'
import { register } from '../socket/messageRegistry'
import { getSocketClient } from '../socket/socketInstance'

// Phases that mustn't be downgraded by a background check result.
const BUSY_PHASES: ReadonlyArray<LocalLLMState['phase']> = [
  'installing',
  'starting',
  'pulling_model',
]

const initialState: LocalLLMState = {
  phase: 'idle',
  defaultUrl: 'http://localhost:11434',
  installProgress: [],
  pullProgress: [],
  pullBytes: null,
  suggestedModels: [],
}

const localLlmSlice = createSlice({
  name: 'localLlm',
  initialState,
  reducers: {
    applyCheck(state, action: PayloadAction<LocalLLMCheckResponse>) {
      const r = action.payload
      if (BUSY_PHASES.includes(state.phase)) return
      if (!r.success) {
        state.phase = 'error'
        state.error = r.error
        return
      }
      state.phase = r.running ? 'running' : r.installed ? 'not_running' : 'not_installed'
      state.version = r.version
      state.defaultUrl = r.default_url || state.defaultUrl
      state.error = undefined
      state.testResult = undefined
    },
    applyTest(state, action: PayloadAction<LocalLLMTestResponse>) {
      const r = action.payload
      const testResult = { success: r.success, message: r.message, error: r.error, models: r.models }
      if (r.success && (!r.models || r.models.length === 0)) {
        state.phase = 'selecting_model'
      } else if (r.success) {
        state.phase = 'connected'
      }
      state.testResult = testResult
    },
    appendInstallProgress(state, action: PayloadAction<LocalLLMProgressResponse>) {
      state.installProgress.push(action.payload.message)
    },
    applyInstall(state, action: PayloadAction<LocalLLMInstallResponse>) {
      const r = action.payload
      if (r.success) {
        state.phase = 'checking'
        state.installProgress = []
      } else {
        state.phase = 'error'
        state.error = r.error ?? i18n.t('nav:slices.localLlm.installationFailed')
      }
    },
    applyStart(state, action: PayloadAction<LocalLLMInstallResponse>) {
      const r = action.payload
      state.phase = r.success ? 'running' : 'error'
      state.error = r.success ? undefined : (r.error ?? i18n.t('nav:slices.localLlm.failedToStart'))
      state.testResult = undefined
    },
    setSuggestedModels(state, action: PayloadAction<SuggestedModel[]>) {
      state.suggestedModels = action.payload
    },
    applyPullProgress(state, action: PayloadAction<LocalLLMPullProgressResponse>) {
      const r = action.payload
      const isDownloading = r.total > 0
      if (!isDownloading && r.message && !state.pullProgress.includes(r.message)) {
        state.pullProgress.push(r.message)
      }
      if (isDownloading) {
        state.pullBytes = { completed: r.completed, total: r.total, percent: r.percent }
      }
    },
    applyPullModel(state, action: PayloadAction<LocalLLMInstallResponse>) {
      const r = action.payload
      if (r.success) {
        state.pullProgress = []
        state.error = undefined
      } else {
        state.phase = 'error'
        state.error = r.error ?? i18n.t('nav:slices.localLlm.modelDownloadFailed')
      }
    },
    setPhase(state, action: PayloadAction<LocalLLMState['phase']>) {
      state.phase = action.payload
    },
    // Optimistic pre-send transitions, used by the context's send helpers.
    markChecking(state) {
      if (BUSY_PHASES.includes(state.phase)) return
      state.phase = 'checking'
      state.error = undefined
    },
    markInstalling(state) {
      state.phase = 'installing'
      state.installProgress = []
      state.error = undefined
    },
    markInstallFailed(state, action: PayloadAction<string>) {
      state.phase = 'error'
      state.error = action.payload
    },
    markStarting(state) {
      state.phase = 'starting'
      state.error = undefined
    },
    markPullingModel(state) {
      state.phase = 'pulling_model'
      state.pullProgress = []
      state.pullBytes = null
      state.error = undefined
    },
  },
})

export const {
  applyCheck,
  applyTest,
  appendInstallProgress,
  applyInstall,
  applyStart,
  setSuggestedModels,
  applyPullProgress,
  applyPullModel,
  setPhase,
  markChecking,
  markInstalling,
  markInstallFailed,
  markStarting,
  markPullingModel,
} = localLlmSlice.actions

export default localLlmSlice.reducer

// --- inbound message handlers --------------------------------------------

register('local_llm_check', (data, dispatch) => {
  dispatch(applyCheck(data as LocalLLMCheckResponse))
})

register('local_llm_test', (data, dispatch) => {
  const r = data as LocalLLMTestResponse
  dispatch(applyTest(r))
  // Side-effect: no models present → fetch the suggested list.
  if (r.success && (!r.models || r.models.length === 0)) {
    getSocketClient().send('local_llm_suggested_models')
  }
})

register('local_llm_install_progress', (data, dispatch) => {
  dispatch(appendInstallProgress(data as LocalLLMProgressResponse))
})

register('local_llm_install', (data, dispatch) => {
  const r = data as LocalLLMInstallResponse
  dispatch(applyInstall(r))
  // Side-effect: poll status after a successful install.
  if (r.success) getSocketClient().send('local_llm_check')
})

register('local_llm_start', (data, dispatch) => {
  dispatch(applyStart(data as LocalLLMInstallResponse))
})

register('local_llm_suggested_models', (data, dispatch) => {
  const d = data as { models?: SuggestedModel[] }
  dispatch(setSuggestedModels(d.models || []))
})

register('local_llm_pull_progress', (data, dispatch) => {
  dispatch(applyPullProgress(data as LocalLLMPullProgressResponse))
})

register('local_llm_pull_model', (data, dispatch, getState) => {
  const r = data as LocalLLMInstallResponse
  dispatch(applyPullModel(r))
  // Side-effect: re-test with the current URL to advance to connected.
  if (r.success) {
    const { defaultUrl } = getState().localLlm
    getSocketClient().send('local_llm_test', { url: defaultUrl })
  }
})
