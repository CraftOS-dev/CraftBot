import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type {
  OnboardingStep,
  OnboardingStepResponse,
  OnboardingSubmitResponse,
  OnboardingCompleteResponse,
} from '../../types'
import { register } from '../socket/messageRegistry'
import i18n from '../../i18n/config'

interface OnboardingState {
  step: OnboardingStep | null
  error: string | null
  loading: boolean
  needsHardOnboarding: boolean
  // Set when hard onboarding finishes: the wizard plays its outro animation
  // (message -> fade -> mascot to centre -> launch) and only then swaps to the
  // main app. Holds the agent's name for the farewell line.
  finishing: { agentName: string } | null
}

const initialState: OnboardingState = {
  step: null,
  error: null,
  loading: false,
  needsHardOnboarding: false,
  finishing: null,
}

const onboardingSlice = createSlice({
  name: 'onboarding',
  initialState,
  reducers: {
    setStep(state, action: PayloadAction<OnboardingStep | null>) {
      state.step = action.payload
      state.loading = false
      state.error = null
    },
    setError(state, action: PayloadAction<string | null>) {
      state.error = action.payload
      state.loading = false
    },
    setLoading(state, action: PayloadAction<boolean>) {
      state.loading = action.payload
    },
    setNeedsHardOnboarding(state, action: PayloadAction<boolean>) {
      state.needsHardOnboarding = action.payload
    },
    // Begin the finishing outro. Keeps needsHardOnboarding true so the wizard
    // stays mounted (and its mascot on screen) until markComplete runs.
    startFinishing(state, action: PayloadAction<{ agentName: string }>) {
      state.finishing = action.payload
      state.loading = false
      state.error = null
    },
    markComplete(state) {
      state.step = null
      state.loading = false
      state.error = null
      state.needsHardOnboarding = false
      state.finishing = null
    },
  },
})

export const {
  setStep,
  setError,
  setLoading,
  setNeedsHardOnboarding,
  startFinishing,
  markComplete,
} = onboardingSlice.actions

export default onboardingSlice.reducer

// --- inbound message handlers --------------------------------------------

register('init', (data, dispatch) => {
  const d = data as { needsHardOnboarding?: boolean } | undefined
  dispatch(setNeedsHardOnboarding(d?.needsHardOnboarding ?? false))
})

register('onboarding_step', (data, dispatch) => {
  const r = data as OnboardingStepResponse
  if (r.success) {
    if (r.completed) {
      dispatch(markComplete())
    } else if (r.step) {
      dispatch(setStep(r.step))
    }
  } else {
    dispatch(setError(r.error || i18n.t('nav:slices.onboarding.failedToGetStep')))
  }
})

register('onboarding_submit', (data, dispatch) => {
  const r = data as OnboardingSubmitResponse
  if (r.success && r.nextStep) {
    dispatch(setStep(r.nextStep))
  } else if (!r.success) {
    dispatch(setError(r.error || i18n.t('nav:slices.onboarding.failedToSubmit')))
  }
})

register('onboarding_skip', (data, dispatch) => {
  const r = data as OnboardingSubmitResponse
  if (r.success && r.nextStep) {
    dispatch(setStep(r.nextStep))
  } else if (!r.success) {
    dispatch(setError(r.error || i18n.t('nav:slices.onboarding.cannotSkip')))
  }
})

register('onboarding_back', (data, dispatch) => {
  const r = data as { success: boolean; step?: OnboardingStep; error?: string }
  if (r.success && r.step) {
    dispatch(setStep(r.step))
  } else if (!r.success) {
    dispatch(setError(r.error || i18n.t('nav:slices.onboarding.cannotGoBack')))
  }
})

register('onboarding_complete', (data, dispatch) => {
  const r = data as OnboardingCompleteResponse
  // Don't swap to the main app yet - hand off to the wizard's outro animation,
  // which calls markComplete when it finishes.
  if (r.success) dispatch(startFinishing({ agentName: r.agentName || 'CraftBot' }))
})
