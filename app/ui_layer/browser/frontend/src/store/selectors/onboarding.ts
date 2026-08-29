import type { RootState } from '../index'

export const selectOnboardingStep = (state: RootState) => state.onboarding.step
export const selectOnboardingError = (state: RootState) => state.onboarding.error
export const selectOnboardingLoading = (state: RootState) => state.onboarding.loading
export const selectNeedsHardOnboarding = (state: RootState) =>
  state.onboarding.needsHardOnboarding
export const selectOnboardingFinishing = (state: RootState) =>
  state.onboarding.finishing
