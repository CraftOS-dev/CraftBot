// Stable DOM anchors for the guided product tour.
//
// Component CSS is authored with CSS Modules, whose class names are hashed at
// build time and therefore useless as tour targets. Instead, tour targets are
// explicit `data-tour="<id>"` attributes. The same typed id is referenced by
// the component (via `tourAnchorProps`) and by the step definition (via
// `tourSelector`), so renaming an anchor is a compile error rather than a
// silently broken step.

export type TourAnchorId =
  | 'chat-composer'
  | 'chat-plus'
  | 'nav-new-chat'
  | 'nav-chats'
  | 'nav-main-session'
  | 'nav-agent-app'
  // Tabs inside the "Add Agent App" modal.
  | 'agentapp-tab-marketplace'
  | 'agentapp-tab-custom'
  | 'agentapp-tab-import'
  | 'nav-dashboard'
  | 'nav-memory'
  | 'nav-workspace'
  // On-page anchors for the Settings page: the whole category rail, plus the
  // individual tabs the tour calls out.
  | 'settings-categories'
  | 'settings-proactive'
  | 'settings-skills'
  | 'settings-integrations'

const ATTR = 'data-tour' as const

/**
 * Props to spread onto the JSX element a tour step should highlight:
 *   <button {...tourAnchorProps('nav-new-chat')} />
 */
export function tourAnchorProps(id: TourAnchorId): { 'data-tour': TourAnchorId } {
  return { [ATTR]: id }
}

/** CSS selector the tour controller hands to driver.js to locate the anchor. */
export function tourSelector(id: TourAnchorId): string {
  return `[${ATTR}="${id}"]`
}
