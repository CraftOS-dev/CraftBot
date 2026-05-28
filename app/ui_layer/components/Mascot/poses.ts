import type { MascotPose, MascotState } from './types'

// Each mascot state resolves to a pose descriptor that drives the SVG's
// animation classes. Keeping this as data (rather than a switch inside the
// component) makes it easy to add states + lets the CLI mascot, when it
// arrives, consume the same vocabulary without depending on React.

export const POSES: Record<MascotState, MascotPose> = {
  idle:       { sleeping: true,  showBlush: false },
  // 'resting' is the awake-but-quiet state used while the agent is idle
  // but hasn't been idle long enough to enter the sleeping pose yet.
  resting:    { sleeping: false, showBlush: false },
  stopped:    { sleeping: true,  showBlush: false },
  thinking:   { sleeping: false, showBlush: false },
  working:    { sleeping: false, showBlush: false },
  creating:   { sleeping: false, showBlush: false },
  launching:  { sleeping: false, showBlush: false },
  waiting:    { sleeping: false, showBlush: false },
  paused:     { sleeping: false, showBlush: false },
  error:      { sleeping: true,  showBlush: false },
}

export function getPose(state: MascotState): MascotPose {
  return POSES[state]
}
