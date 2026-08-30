import type { Side, Alignment } from 'driver.js'
import type { TourAnchorId } from './anchors'

// Imperative capabilities a step can ask the app to perform before it is
// shown: expanding the sidebar so a nav item is on screen, opening a fresh New
// Chat so the chat is demonstrated on a clean draft rather than the Main
// session, or expanding the Chats group so the pinned Main row is visible. The
// owning component registers the implementation (see `useTourEnvAction`); a
// step only names the capability, keeping the tour decoupled from internals.
export type TourEnvActionId =
  | 'ensureSidebarVisible'
  | 'openNewChat'
  | 'ensureChatsExpanded'
  | 'openSettingsTab'
  | 'openLivingUIModal'
  | 'closeLivingUIModal'
  | 'openLivingUITab'

// A step's environment entry: an action id on its own, or that id paired with a
// string argument (e.g. which Settings tab to open).
export type TourEnvAction = TourEnvActionId | { id: TourEnvActionId; arg: string }

export interface TourStep {
  /** Stable id for debugging/analytics. Not shown to the user. */
  id: string
  /** Element to highlight. Omit for a centered modal step (welcome / done). */
  anchor?: TourAnchorId
  /**
   * Route the app must be on before the step is shown. The controller
   * navigates here first if needed, then waits for the anchor to mount.
   */
  route?: string
  /** Environment actions to run before highlighting. Must be idempotent. */
  env?: TourEnvAction[]
  /**
   * Popover placement only. The title/description copy is looked up from the
   * `tour` namespace by step id (`tour:steps.<id>.title` / `.description`), so
   * it stays translatable. Omit for a centered modal step with default
   * placement (welcome / done).
   */
  popover?: {
    side?: Side
    align?: Alignment
  }
}

export type TourId = 'core'

export interface TourDefinition {
  id: TourId
  /** When true, the tour auto-starts once for a first-time user. */
  autoStart: boolean
  steps: TourStep[]
}
