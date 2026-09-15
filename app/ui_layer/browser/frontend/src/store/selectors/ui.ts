import type { RootState } from '../index'
import { resolveUiState, type UiStateDescriptor } from '../uiState/defineUiState'

/** A persisted UI state value, or its descriptor's default. */
export const selectUiState = <T>(state: RootState, descriptor: UiStateDescriptor<T>): T =>
  resolveUiState(descriptor, state.ui.values[descriptor.key])
