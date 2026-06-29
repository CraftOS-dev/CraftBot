import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

export interface PetPosition {
  x: number
  y: number
}

export interface PetOutfit {
  body_color: string
  accent_color: string
  antenna: string
  accessory: string | null
}

export interface PetStageProgress {
  stage: number
  isMaxStage: boolean
  tokensIntoStage: number
  tokensForNextStage: number | null
  fraction: number
}

export interface CatalogColor {
  id: string
  label: string
  value: string
}

export interface CatalogUnlock {
  id: string
  label: string
  cost: number
  min_stage: number
}

export interface CatalogLocation extends CatalogUnlock {
  day_image: string
  night_image: string
  image_grass_y: string
  ground_line_y: string
}

export interface PetCatalog {
  bodyColors: CatalogColor[]
  accentColors: CatalogColor[]
  antennas: CatalogUnlock[]
  accessories: CatalogUnlock[]
  locations: CatalogLocation[]
  /** Shop battery purchase cost in tokens (mirrored from the backend
   *  pet_catalog.BATTERY_PURCHASE_COST so the UI doesn't have to keep its
   *  own copy of the number in sync). */
  batteryPurchaseCost: number
  /** Maximum batteries the inventory can hold. */
  batteryInventoryMax: number
}

export interface PetState {
  stage: number
  lifetimeTokens: number
  /** Tokens spent on consumables (currently only batteries). */
  spentTokens: number
  /** Currency available for purchases = lifetimeTokens - spentTokens. */
  spendableTokens: number
  mood: number
  hunger: number
  batteryInventory: number
  position: PetPosition
  location: string
  outfit: PetOutfit
  unlocks: string[]
  stageProgress: PetStageProgress
  catalog: PetCatalog
  /** Frontend-only: incremented when a stage-up event arrives so the
   *  pet panel can play the sparkle/grow animation. */
  stageUpNonce: number
  /** Frontend-only: incremented on each feed event so the eating animation triggers. */
  fedNonce: number
  /** Frontend-only: incremented on each pet/stroke event. */
  pettedNonce: number
}

const initialCatalog: PetCatalog = {
  bodyColors: [],
  accentColors: [],
  antennas: [],
  accessories: [],
  locations: [],
  batteryPurchaseCost: 5000,
  batteryInventoryMax: 99,
}

const initialState: PetState = {
  stage: 1,
  lifetimeTokens: 0,
  spentTokens: 0,
  spendableTokens: 0,
  mood: 50,
  hunger: 30,
  batteryInventory: 0,
  position: { x: 0, y: 0 },
  location: 'grass_field',
  outfit: {
    body_color: 'default',
    accent_color: 'default',
    antenna: 'antenna_1',
    accessory: null,
  },
  unlocks: [],
  stageProgress: {
    stage: 1,
    isMaxStage: false,
    tokensIntoStage: 0,
    tokensForNextStage: 1_000_000,
    fraction: 0,
  },
  catalog: initialCatalog,
  stageUpNonce: 0,
  fedNonce: 0,
  pettedNonce: 0,
}

const petSlice = createSlice({
  name: 'pet',
  initialState,
  reducers: {
    setSnapshot(state, action: PayloadAction<Partial<PetState>>) {
      Object.assign(state, action.payload)
    },
    bumpStageUp(state) {
      state.stageUpNonce += 1
    },
    bumpFed(state) {
      state.fedNonce += 1
    },
    bumpPetted(state) {
      state.pettedNonce += 1
    },
    setPosition(state, action: PayloadAction<PetPosition>) {
      state.position = action.payload
    },
  },
})

export const { setSnapshot, bumpStageUp, bumpFed, bumpPetted, setPosition } = petSlice.actions
export default petSlice.reducer

// --- inbound message handlers --------------------------------------------

register('init', (data, dispatch) => {
  const d = data as { pet?: Partial<PetState> } | undefined
  if (d?.pet && Object.keys(d.pet).length > 0) {
    dispatch(setSnapshot(d.pet))
  }
})

register('pet_state_update', (data, dispatch) => {
  dispatch(setSnapshot(data as Partial<PetState>))
})

register('pet_stage_up', (_data, dispatch) => {
  dispatch(bumpStageUp())
})

register('pet_fed', (_data, dispatch) => {
  dispatch(bumpFed())
})

register('pet_petted', (_data, dispatch) => {
  dispatch(bumpPetted())
})

register('pet_unlock', (data, dispatch) => {
  const d = data as { unlocks?: string[] } | undefined
  if (d?.unlocks) dispatch(setSnapshot({ unlocks: d.unlocks }))
})
