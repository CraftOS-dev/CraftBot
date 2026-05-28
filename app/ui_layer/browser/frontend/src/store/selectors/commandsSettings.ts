import { createSelector } from '@reduxjs/toolkit'
import type { RootState } from '../index'

export const selectCommands = (state: RootState) => state.commandsSettings.commands
export const selectCommandsHasLoaded = (state: RootState) => state.commandsSettings.hasLoaded

export const selectCommandNames = createSelector(
  selectCommands,
  (commands) => commands.map(c => c.name),
)
