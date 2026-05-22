import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type {
  OnboardingStep,
  OnboardingStepResponse,
  OnboardingSubmitResponse,
  OnboardingCompleteResponse,
} from '../../types'
import { register } from '../socket/messageRegistry'

interface OnboardingState {
  step: OnboardingStep | null
  error: string | null
  loading: boolean
  needsHardOnboarding: boolean
}

const initialState: OnboardingState = {
  step: null,
  error: null,
  loading: false,
  needsHardOnboarding: false,
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
    markComplete(state) {
      state.step = null
      state.loading = false
      state.error = null
      state.needsHardOnboarding = false
    },
  },
})

export const {
  setStep,
  setError,
  setLoading,
  setNeedsHardOnboarding,
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
    dispatch(setError(r.error || 'Failed to get step'))
  }
})

register('onboarding_submit', (data, dispatch) => {
  const r = data as OnboardingSubmitResponse
  if (r.success && r.nextStep) {
    dispatch(setStep(r.nextStep))
  } else if (!r.success) {
    dispatch(setError(r.error || 'Failed to submit'))
  }
})

register('onboarding_skip', (data, dispatch) => {
  const r = data as OnboardingSubmitResponse
  if (r.success && r.nextStep) {
    dispatch(setStep(r.nextStep))
  } else if (!r.success) {
    dispatch(setError(r.error || 'Cannot skip this step'))
  }
})

register('onboarding_back', (data, dispatch) => {
  const r = data as { success: boolean; step?: OnboardingStep; error?: string }
  if (r.success && r.step) {
    dispatch(setStep(r.step))
  } else if (!r.success) {
    dispatch(setError(r.error || 'Cannot go back'))
  }
})

register('onboarding_complete', (data, dispatch) => {
  const r = data as OnboardingCompleteResponse
  if (r.success) dispatch(markComplete())
})
