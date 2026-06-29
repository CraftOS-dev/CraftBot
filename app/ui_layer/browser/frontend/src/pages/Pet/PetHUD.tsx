import { BatterySprite } from '@mascot'
import {
  MoodIcon,
  EnergyIcon,
  ShopIcon,
  WardrobeIcon,
  LocationIcon,
  type FillState,
} from './PetIcons'
import styles from './PetPage.module.css'

interface StatRowProps {
  value: number               // 0..100
  Icon: (props: { state: FillState; size?: number }) => JSX.Element
}

/** 5 icons across, each representing 20 units of the stat. */
function StatRow({ value, Icon }: StatRowProps) {
  const SLOTS = 5
  const PER_SLOT = 20
  return (
    <div className={styles.statRow}>
      {Array.from({ length: SLOTS }, (_, i) => {
        const slotMin = i * PER_SLOT
        const slotValue = Math.max(0, Math.min(PER_SLOT, value - slotMin))
        const state: FillState =
          slotValue >= PER_SLOT ? 'full'
          : slotValue >= PER_SLOT / 2 ? 'half'
          : 'empty'
        return <Icon key={i} state={state} />
      })}
    </div>
  )
}

interface PetHUDProps {
  mood: number
  energy: number
  batteryCount: number
  onOpenShop: () => void
  onFeed: () => void
  onOpenWardrobe: () => void
  onOpenLocation: () => void
}

export function PetHUD({
  mood,
  energy,
  batteryCount,
  onOpenShop,
  onFeed,
  onOpenWardrobe,
  onOpenLocation,
}: PetHUDProps) {
  const canFeed = batteryCount > 0
  return (
    <>
      <div className={styles.hudTopLeft}>
        <StatRow value={mood} Icon={MoodIcon} />
        <StatRow value={energy} Icon={EnergyIcon} />
      </div>
      <div className={styles.hudTopRight}>
        <button
          className={`${styles.hudButton} ${styles.hudButtonBare}`}
          onClick={() => canFeed && onFeed()}
          disabled={!canFeed}
          aria-label={`Feed (${batteryCount} batteries)`}
        >
          <BatterySprite size={30} />
          {batteryCount > 0 && (
            <span className={styles.hudBadge}>{batteryCount}</span>
          )}
        </button>
        <button className={styles.hudButton} onClick={onOpenShop} aria-label="Shop">
          <ShopIcon />
        </button>
        <button className={styles.hudButton} onClick={onOpenWardrobe} aria-label="Customize">
          <WardrobeIcon />
        </button>
        <button className={styles.hudButton} onClick={onOpenLocation} aria-label="Location">
          <LocationIcon />
        </button>
      </div>
    </>
  )
}
