import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type { ReasoningChoice } from '../../types'
import { register } from '../socket/messageRegistry'

// What the chat input's reasoning picker offers for the model in use. The
// backend computes it from the live LLM interface (reasoning_options_get),
// so it tracks model switches; the CHOICE is per session and lives on the
// session (SessionInfo.reasoningEffort) or, for a draft chat, in UI state.

/** How long the provider keeps a request's prompt cache. 'exact': guaranteed
 *  at least this long; 'typical': the provider's usual figure only. */
export interface CacheLifetime {
  kind: 'exact' | 'typical'
  seconds: number
}

/** What every model reports, adjustable reasoning or not. */
interface ModelContext {
  model: string
  /** Where requests are served (provider, or its subscription backend). */
  surface: string
  /** Input tokens a request may carry at each choice; the event stream is
   *  summarized when the next request would carry more. */
  inputBudgets: Record<ReasoningChoice, number>
  /** null: the provider documents no cache lifetime. */
  cacheLifetime: CacheLifetime | null
  /** false: responses never say what was cached, so no hit rate exists. */
  reportsCachedTokens: boolean
}

export type ReasoningOptions =
  /** The model has no reasoning rule: nothing is adjustable. */
  | (ModelContext & { configurable: false })
  | (ModelContext & {
    configurable: true
    /** Selectable choices in display order. */
    choices: ReasoningChoice[]
    /** The model's default level (marked "Default"; new chats start here). */
    defaultLevel: ReasoningChoice
    /** What 'provider_default' does: 'off', a level, or 'dynamic'. */
    providerDefault: string
    /** Effective choice for every stored choice (pi-style clamping). */
    resolution: Record<ReasoningChoice, ReasoningChoice>
  })

interface ReasoningState {
  options: ReasoningOptions | null
}

const initialState: ReasoningState = {
  options: null,
}

const reasoningSlice = createSlice({
  name: 'reasoning',
  initialState,
  reducers: {
    setReasoningOptions(state, action: PayloadAction<ReasoningOptions>) {
      state.options = action.payload
    },
  },
})

const { setReasoningOptions } = reasoningSlice.actions
export default reasoningSlice.reducer

register('reasoning_options_get', (data, dispatch) => {
  const d = data as { success: false } | ({ success: true } & ReasoningOptions)
  if (!d.success) return
  const { success: _, ...options } = d
  dispatch(setReasoningOptions(options))
})
