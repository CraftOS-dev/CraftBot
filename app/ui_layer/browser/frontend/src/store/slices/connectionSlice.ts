import { createSlice, PayloadAction } from '@reduxjs/toolkit'

export interface ConnectionState {
  connected: boolean
  version: string
  reconnectAttempt: number
}

const initialState: ConnectionState = {
  connected: false,
  version: '',
  reconnectAttempt: 0,
}

const connectionSlice = createSlice({
  name: 'connection',
  initialState,
  reducers: {
    setConnected(state, action: PayloadAction<boolean>) {
      state.connected = action.payload
      if (action.payload) state.reconnectAttempt = 0
    },
    setVersion(state, action: PayloadAction<string>) {
      state.version = action.payload
    },
    setReconnectAttempt(state, action: PayloadAction<number>) {
      state.reconnectAttempt = action.payload
    },
  },
})

export const { setConnected, setVersion, setReconnectAttempt } = connectionSlice.actions
export default connectionSlice.reducer
