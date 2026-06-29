import type { RootState } from '../index'

export const selectPet = (state: RootState) => state.pet
export const selectPetStage = (state: RootState) => state.pet.stage
export const selectPetMood = (state: RootState) => state.pet.mood
export const selectPetHunger = (state: RootState) => state.pet.hunger
export const selectPetBattery = (state: RootState) => state.pet.batteryInventory
export const selectPetOutfit = (state: RootState) => state.pet.outfit
export const selectPetLocation = (state: RootState) => state.pet.location
export const selectPetUnlocks = (state: RootState) => state.pet.unlocks
export const selectPetCatalog = (state: RootState) => state.pet.catalog
export const selectPetStageProgress = (state: RootState) => state.pet.stageProgress
export const selectPetPosition = (state: RootState) => state.pet.position
export const selectPetStageUpNonce = (state: RootState) => state.pet.stageUpNonce
export const selectPetFedNonce = (state: RootState) => state.pet.fedNonce
export const selectPetPettedNonce = (state: RootState) => state.pet.pettedNonce
