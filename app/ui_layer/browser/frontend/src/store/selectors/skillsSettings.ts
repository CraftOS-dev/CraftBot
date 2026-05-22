import { createSelector } from '@reduxjs/toolkit'
import type { RootState } from '../index'

export const selectSkills = (state: RootState) => state.skillsSettings.skills
export const selectTotalSkills = (state: RootState) => state.skillsSettings.total
export const selectEnabledSkills = (state: RootState) => state.skillsSettings.enabled
export const selectSkillsHasLoaded = (state: RootState) => state.skillsSettings.hasLoaded

// Derived: names of enabled, user-invocable skills. Memoized so consumers
// (e.g. SlashCommandAutocomplete) don't re-render on every keystroke.
export const selectEnabledSkillNames = createSelector(
  selectSkills,
  (skills) => skills.filter(s => s.enabled).map(s => s.name),
)
