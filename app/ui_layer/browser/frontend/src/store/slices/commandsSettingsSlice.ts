import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

export interface CommandConfig {
  name: string
  description: string
}

interface CommandsSettingsState {
  commands: CommandConfig[]
  hasLoaded: boolean
}

const initialState: CommandsSettingsState = {
  commands: [],
  hasLoaded: false,
}

const commandsSettingsSlice = createSlice({
  name: 'commandsSettings',
  initialState,
  reducers: {
    setCommands(state, action: PayloadAction<CommandConfig[]>) {
      state.commands = action.payload
      state.hasLoaded = true
    },
  },
})

export const { setCommands } = commandsSettingsSlice.actions
export default commandsSettingsSlice.reducer

register('command_list', (data, dispatch) => {
  const d = data as { success: boolean; commands?: CommandConfig[] }
  if (d.success && d.commands) {
    dispatch(setCommands(d.commands))
  }
})
