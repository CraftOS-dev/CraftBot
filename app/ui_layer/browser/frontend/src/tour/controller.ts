import { driver, type Config, type DriveStep, type Driver } from 'driver.js'
import type { TourDefinition, TourEnvActionId, TourStep } from './types'
import { tourSelector } from './anchors'
import { markTourCompleted } from './storage'
import i18n from '../i18n/config'

// A step's title/description live in the `tour` namespace keyed by its id
// (`tour:steps.<id>.title`). Keys are built dynamically, so they're validated
// against the catalog at runtime rather than by the compiler.
const tourText = (key: string): string =>
  (i18n.t as unknown as (k: string) => string)(key)

// How long to wait for a step's anchor to mount (after navigation and any
// environment actions) before giving up and skipping the step.
const ELEMENT_WAIT_MS = 4000
const ELEMENT_POLL_MS = 50

/**
 * The bridge between the framework-agnostic controller and the React app.
 * Supplied by TourProvider so the controller never imports React or router.
 */
export interface TourEnvironment {
  /** Navigate the SPA to a path (react-router navigate). */
  navigate: (path: string) => void
  /** Current pathname, read fresh on each call. */
  getPathname: () => string
  /** Invoke a named environment action (with an optional argument) if registered. */
  runEnvAction: (id: TourEnvActionId, arg?: string) => void
}

type Direction = 1 | -1

/**
 * Wait for `selector` to resolve to a laid-out element, polling on animation
 * frames. Resolves the element, or null on timeout / cancellation. Cancelable
 * so a torn-down tour stops polling immediately.
 */
function waitForElement(
  selector: string,
  timeoutMs: number,
  isCancelled: () => boolean,
): Promise<HTMLElement | null> {
  return new Promise(resolve => {
    const start = performance.now()
    const tick = () => {
      if (isCancelled()) return resolve(null)
      const el = document.querySelector<HTMLElement>(selector)
      // getClientRects() is empty for display:none / not-yet-laid-out nodes,
      // but non-empty for position:fixed elements (unlike offsetParent), so it
      // works for the mobile sidebar drawer too.
      if (el && el.getClientRects().length > 0) return resolve(el)
      if (performance.now() - start >= timeoutMs) return resolve(null)
      window.setTimeout(() => requestAnimationFrame(tick), ELEMENT_POLL_MS)
    }
    requestAnimationFrame(tick)
  })
}

/**
 * Drives a single tour over driver.js. Owns exactly one driver instance and
 * all cross-route / cross-state transition logic. Framework-agnostic: it talks
 * to the app only through the injected TourEnvironment.
 */
export class TourController {
  private readonly def: TourDefinition
  private readonly env: TourEnvironment
  private readonly onExit: () => void

  private driverObj: Driver | null = null
  private stepIndex = 0
  private transitioning = false
  private cancelled = false
  private finished = false

  constructor(def: TourDefinition, env: TourEnvironment, onExit: () => void) {
    this.def = def
    this.env = env
    this.onExit = onExit
  }

  isActive(): boolean {
    return this.driverObj?.isActive() ?? false
  }

  /** Start the tour at its first showable step. */
  async start(): Promise<void> {
    if (this.driverObj || this.finished) return
    this.driverObj = driver(this.buildConfig())
    const first = await this.resolveFrom(0, 1)
    if (this.finished || !this.driverObj) return
    if (first === null) {
      // No anchors resolved at all — abort quietly without marking complete.
      this.teardown(false)
      return
    }
    this.stepIndex = first
    this.driverObj.drive(first)
  }

  /** Tear down without marking complete (e.g. the provider unmounted). */
  destroy(): void {
    this.teardown(false)
  }

  private buildConfig(): Config {
    return {
      steps: this.def.steps.map(step => this.toDriveStep(step)),
      animate: true,
      overlayColor: '#000',
      overlayOpacity: 0.6,
      stagePadding: 6,
      stageRadius: 8,
      smoothScroll: true,
      allowClose: true,
      // A read-only walkthrough: the highlighted element is not clickable, so a
      // user can't derail the tour by acting on it mid-step.
      disableActiveInteraction: true,
      popoverClass: 'cb-tour',
      showProgress: true,
      // driver.js substitutes {{current}}/{{total}} itself, so override
      // i18next's delimiters here to leave those braces untouched.
      progressText: i18n.t('tour:progressText', {
        interpolation: { prefix: '{|', suffix: '|}' },
      }),
      showButtons: ['next', 'previous', 'close'],
      nextBtnText: i18n.t('common:actions.next'),
      prevBtnText: i18n.t('common:actions.back'),
      doneBtnText: i18n.t('common:actions.done'),
      // We own all navigation between steps, so intercept the buttons and drive
      // the transition ourselves.
      onNextClick: () => { void this.advance(1) },
      onPrevClick: () => { void this.advance(-1) },
      // Fires for every teardown path the user initiates (X, Esc, overlay, and
      // Done on the last step) — the single place we record completion.
      onDestroyStarted: () => { this.teardown(true) },
    }
  }

  private toDriveStep(step: TourStep): DriveStep {
    return {
      element: step.anchor ? tourSelector(step.anchor) : undefined,
      popover: {
        title: tourText(`tour:steps.${step.id}.title`),
        description: tourText(`tour:steps.${step.id}.description`),
        side: step.popover?.side,
        align: step.popover?.align,
      },
    }
  }

  private async advance(direction: Direction): Promise<void> {
    if (!this.driverObj || this.transitioning || this.finished) return
    const target = this.stepIndex + direction
    if (target < 0) return
    if (target >= this.def.steps.length) {
      // Advanced past the last step ("Done") — complete the tour.
      this.teardown(true)
      return
    }
    this.transitioning = true
    try {
      const resolved = await this.resolveFrom(target, direction)
      if (this.finished || !this.driverObj) return
      if (resolved === null) {
        // Nothing further to show in this direction. Forward means the tour is
        // effectively over; backward simply stays on the current step.
        if (direction === 1) this.teardown(true)
        return
      }
      this.stepIndex = resolved
      this.driverObj.moveTo(resolved)
    } finally {
      this.transitioning = false
    }
  }

  /**
   * Scan from `startIndex` in `direction` for the first step that can actually
   * be shown, preparing each candidate as it goes: run its environment actions,
   * navigate to its route, then wait for its anchor to mount. Steps whose
   * anchor never appears (e.g. a feature is disabled) are skipped. Modal steps
   * (no anchor) always resolve. Returns the resolved index, or null if none.
   */
  private async resolveFrom(startIndex: number, direction: Direction): Promise<number | null> {
    let idx = startIndex
    while (idx >= 0 && idx < this.def.steps.length) {
      const step = this.def.steps[idx]

      step.env?.forEach(action =>
        typeof action === 'string'
          ? this.env.runEnvAction(action)
          : this.env.runEnvAction(action.id, action.arg),
      )

      if (step.route && this.env.getPathname() !== step.route) {
        this.env.navigate(step.route)
      }

      if (!step.anchor) return idx

      const el = await waitForElement(
        tourSelector(step.anchor),
        ELEMENT_WAIT_MS,
        () => this.cancelled,
      )
      if (this.cancelled) return null
      if (el) return idx

      idx += direction
    }
    return null
  }

  private teardown(markComplete: boolean): void {
    if (this.finished) return
    this.finished = true
    this.cancelled = true
    if (markComplete) markTourCompleted(this.def.id)
    const d = this.driverObj
    this.driverObj = null
    // driver.destroy() is the low-level teardown and does not re-enter
    // onDestroyStarted, so this is safe to call from within that hook.
    if (d?.isActive()) d.destroy()
    this.onExit()
  }
}
