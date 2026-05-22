import type { RootState } from '../index'

export const selectSkills = (state: RootState) => state.skillsSettings.skills
export const selectTotalSkills = (state: RootState) => state.skillsSettings.total
export const selectEnabledSkills = (state: RootState) => state.skillsSettings.enabled
export const selectSkillsHasLoaded = (state: RootState) => state.skillsSettings.hasLoaded
