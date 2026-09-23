// Shared mascot vocabulary. Lives at the ui_layer level so a future CLI mascot
// can reuse the same state names even if it can't reuse the React component.

export type MascotState =
  // Generic agent states (used by the chat panel mascot display)
  | 'idle'
  // 'resting' is the holding state for the 30-minute pre-sleep window —
  // the agent is idle but the mascot still looks awake.
  | 'resting'
  | 'thinking'
  | 'working'
  | 'waiting'
  | 'paused'
  | 'error'
  // AgentApp lifecycle states (preserved from the original CraftBotPet)
  | 'creating'
  | 'launching'
  | 'stopped'

export interface MascotPose {
  /** Sleeping silhouette + closed eyes + sleep Z's */
  sleeping: boolean
  /** Cheek blush flanks the eyes (used during creation milestones) */
  showBlush: boolean
}
