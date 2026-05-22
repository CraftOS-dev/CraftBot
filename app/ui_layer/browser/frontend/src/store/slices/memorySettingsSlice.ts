import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

export interface MemoryItem {
  id: string
  timestamp: string
  category: string
  content: string
  raw: string
}

interface MemorySettingsState {
  enabled: boolean
  items: MemoryItem[]
  hasLoadedMode: boolean
  hasLoadedItems: boolean
}

const initialState: MemorySettingsState = {
  enabled: true,
  items: [],
  hasLoadedMode: false,
  hasLoadedItems: false,
}

const memorySettingsSlice = createSlice({
  name: 'memorySettings',
  initialState,
  reducers: {
    setEnabled(state, action: PayloadAction<boolean>) {
      state.enabled = action.payload
      state.hasLoadedMode = true
    },
    setItems(state, action: PayloadAction<MemoryItem[]>) {
      state.items = action.payload
      state.hasLoadedItems = true
    },
  },
})

export const { setEnabled, setItems } = memorySettingsSlice.actions
export default memorySettingsSlice.reducer

register('memory_mode_get', (data, dispatch) => {
  const d = data as { success: boolean; enabled: boolean }
  if (d.success) dispatch(setEnabled(d.enabled))
})

register('memory_mode_set', (data, dispatch) => {
  const d = data as { success: boolean; enabled: boolean }
  if (d.success) dispatch(setEnabled(d.enabled))
})

register('memory_items_get', (data, dispatch) => {
  const d = data as { success: boolean; items: MemoryItem[] }
  if (d.success) dispatch(setItems(d.items || []))
})
