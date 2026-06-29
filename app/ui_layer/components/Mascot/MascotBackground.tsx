import type { CSSProperties, SyntheticEvent } from 'react'
import styles from './Mascot.module.css'

interface LocationSpec {
  day_image: string
  night_image: string
  image_grass_y?: string
  ground_line_y?: string
}

interface Props {
  /** Selected location — falls back to grass_field defaults. */
  location?: LocationSpec | null
  /** Fires with naturalWidth/naturalHeight after each bg image loads.
   *  MascotDisplay uses this to compute the scene's pan-clamp range
   *  (you can't pan past the image edge). */
  onAspectChange?: (aspect: number) => void
}

const DEFAULT_DAY = '/mascot-backgrounds/background_1_day.jpg'
const DEFAULT_NIGHT = '/mascot-backgrounds/background_1_night.jpg'

/** Decorative scene behind the mascot. Light theme shows the day image,
 *  dark theme shows the night image. Each location ships its own day +
 *  night pair plus tunables for the grass alignment.
 *
 *  Both images are pre-loaded so theme/location swaps crossfade without
 *  a flash. z-index 0 + pointer-events:none so it doesn't block the
 *  stage's wheel-to-zoom handler or mascot clicks. */
export function MascotBackground({ location, onAspectChange }: Props) {
  const dayUrl = location?.day_image ?? DEFAULT_DAY
  const nightUrl = location?.night_image ?? DEFAULT_NIGHT
  const style: CSSProperties = {}
  if (location?.image_grass_y) {
    (style as Record<string, string>)['--bg-image-grass-y'] = location.image_grass_y
  }
  if (location?.ground_line_y) {
    (style as Record<string, string>)['--bg-ground-line-y'] = location.ground_line_y
  }
  const handleLoad = (e: SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget
    if (img.naturalHeight > 0 && onAspectChange) {
      onAspectChange(img.naturalWidth / img.naturalHeight)
    }
  }
  return (
    <div className={styles.background} aria-hidden="true" style={style}>
      <img className={styles.bgDay} src={dayUrl} alt="" onLoad={handleLoad} />
      <img className={styles.bgNight} src={nightUrl} alt="" onLoad={handleLoad} />
    </div>
  )
}
