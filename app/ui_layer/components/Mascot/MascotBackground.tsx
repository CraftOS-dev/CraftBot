import styles from './Mascot.module.css'

// Two image layers (day + night) are always rendered. CSS toggles their
// opacity off [data-theme] on <html> — pre-loading both means the theme
// switch is instant with a smooth crossfade, no flash-of-empty-background
// while a new image downloads.
const DAY_URL = '/mascot-backgrounds/background_1_day.jpg'
const NIGHT_URL = '/mascot-backgrounds/background_1_night.jpg'

/** Decorative scene behind the mascot. Light theme shows the day image,
 *  dark theme shows the night image. Sits at z-index 0 (mascotLayer is
 *  z-index 2) and is pointer-events:none so it doesn't block the
 *  stage's wheel-to-zoom handler or mascot clicks. */
export function MascotBackground() {
  return (
    <div className={styles.background} aria-hidden="true">
      <img className={styles.bgDay} src={DAY_URL} alt="" />
      <img className={styles.bgNight} src={NIGHT_URL} alt="" />
    </div>
  )
}
