import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

export interface PlaybookWorksBestWith {
  agent_profile?: string
  skills?: string[]
  mcp_servers?: string[]
  agent_app_apps?: string[]
}

export interface Playbook {
  id: string
  name: string
  category?: string
  tags?: string[]
  emoji?: string
  description?: string
  works_best_with?: PlaybookWorksBestWith
  steps?: string[]
  prompt: string
}

interface PlaybooksState {
  /** The bundled catalogue, as last sent by the backend. */
  items: Playbook[]
  hasLoaded: boolean
  error: string | null
}

const initialState: PlaybooksState = {
  items: [],
  hasLoaded: false,
  error: null,
}

const playbooksSlice = createSlice({
  name: 'playbooks',
  initialState,
  reducers: {
    setPlaybooks(state, action: PayloadAction<Playbook[]>) {
      state.items = action.payload
      state.hasLoaded = true
      state.error = null
    },
    setPlaybooksError(state, action: PayloadAction<string>) {
      state.error = action.payload
      state.hasLoaded = true
    },
    /** Back to "never loaded" so the view shows its spinner while retrying. */
    resetPlaybooks(state) {
      state.hasLoaded = false
      state.error = null
    },
  },
})

export const { setPlaybooks, setPlaybooksError, resetPlaybooks } = playbooksSlice.actions
export default playbooksSlice.reducer

// The catalogue lives in the store rather than in the views that show it:
// ResourceSync only asks for it once per connection, so a view that kept it
// in local state lost it on every remount and never asked again.
register('playbook_list', (data, dispatch) => {
  const d = data as { success?: boolean; playbooks?: Playbook[]; error?: string }
  if (d?.success && Array.isArray(d.playbooks)) dispatch(setPlaybooks(d.playbooks))
  else dispatch(setPlaybooksError(d?.error || ''))
})
