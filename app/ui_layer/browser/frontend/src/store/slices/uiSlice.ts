import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import {
  isDefaultUiValue,
  type UiStateDescriptor,
  type UiStateLifetime,
} from '../uiState/defineUiState'

// Persisted UI state — panel sizes, open/closed sections, filters, scroll
// offsets — keyed by descriptor key (see store/uiState/catalog.ts).
//
// Living in Redux is what makes it survive navigation: pages unmount, the
// store doesn't. The persistence middleware (store/uiState/persistence.ts)
// writes changes to local/sessionStorage, and the store is preloaded from
// there on boot. An absent key means "use the descriptor's default".
export interface UiSliceState {
  values: Record<string, unknown>
}

const initialState: UiSliceState = {
  values: {},
}

interface UiStateChange {
  key: string
  lifetime: UiStateLifetime
  /** undefined resets the key to its default. */
  value: unknown
}

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    // A change made in this tab. The persistence middleware writes it out.
    uiStateChanged(state, action: PayloadAction<UiStateChange>) {
      applyValue(state, action.payload.key, action.payload.value)
    },
    // A change another tab already wrote to localStorage — mirrored here
    // only, never written back.
    uiStateSynced(state, action: PayloadAction<{ key: string; value: unknown }>) {
      applyValue(state, action.payload.key, action.payload.value)
    },
  },
})

function applyValue(state: UiSliceState, key: string, value: unknown) {
  if (value === undefined) {
    delete state.values[key]
  } else {
    state.values[key] = value
  }
}

export const { uiStateChanged, uiStateSynced } = uiSlice.actions
export default uiSlice.reducer

/** Action creator: set a descriptor's value (setting its default clears the key). */
export function setUiState<T>(descriptor: UiStateDescriptor<T>, value: T) {
  return uiStateChanged({
    key: descriptor.key,
    lifetime: descriptor.lifetime,
    value: isDefaultUiValue(descriptor, value) ? undefined : value,
  })
}
