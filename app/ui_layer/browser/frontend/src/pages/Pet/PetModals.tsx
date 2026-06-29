import type { PropsWithChildren } from 'react'
import { useRef, useState } from 'react'
import { CraftBotMascot, BatterySprite } from '@mascot'
import type { PetState } from '../../store/slices/petSlice'
import { resolveColor } from '../../hooks/usePetMascotProps'
import {
  CloseIcon,
  GoldCoinIcon,
  InfoIcon,
  LockIcon,
  AntennaPreview,
  AccessoryPreview,
} from './PetIcons'
import styles from './PetPage.module.css'

// Token formatter for locked-cell costs.
function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`
  return String(n)
}

// ─────────────────────────────────────────────────────────────────────
// Modal shell
// ─────────────────────────────────────────────────────────────────────
interface ModalProps {
  open: boolean
  onClose: () => void
  title?: string
}

function Modal({ open, onClose, title, children }: PropsWithChildren<ModalProps>) {
  if (!open) return null
  return (
    <div className={styles.modalBackdrop} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <button className={styles.modalClose} onClick={onClose} aria-label="Close">
          <CloseIcon />
        </button>
        {title && <h2 className={styles.modalTitle}>{title}</h2>}
        <div className={styles.modalBody}>
          {children}
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Shop — three sections: Antennas, Hats, Locations
// ─────────────────────────────────────────────────────────────────────
interface ShopModalProps extends ModalProps {
  pet: PetState
  onUnlock: (id: string) => void
  onBuyBattery: () => void
}

interface CatalogEntry {
  id: string
  label: string
  cost: number
  min_stage: number
}

function ShopSection({
  title,
  items,
  preview,
  pet,
  onUnlock,
}: {
  title: string
  items: CatalogEntry[]
  preview: (id: string) => JSX.Element
  pet: PetState
  // Cost is passed back so the parent ShopModal can trigger its
  // coin-spend float animation with the correct amount; the click
  // event is forwarded too so the animation can land at the clicked
  // button's center.
  onUnlock: (id: string, cost: number, e: React.MouseEvent) => void
}) {
  const locked = items.filter((i) => !pet.unlocks.includes(i.id))
  if (locked.length === 0) return null
  // Unlocks now actually DEDUCT tokens, so affordability must check
  // spendable (lifetime − spent), not raw lifetime.
  const spendable = pet.spendableTokens ?? pet.lifetimeTokens
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>{title}</div>
      <div className={styles.itemGrid}>
        {locked.map((item) => {
          const stageOK = pet.stage >= item.min_stage
          const affordable = spendable >= item.cost
          const canUnlock = stageOK && affordable
          return (
            <div key={item.id} className={styles.itemWrapper}>
              <button
                className={`${styles.itemCell} ${!canUnlock ? styles.itemCellLocked : ''}`}
                onClick={(e) => canUnlock && onUnlock(item.id, item.cost, e)}
                disabled={!canUnlock}
                title={
                  !stageOK
                    ? `Unlocks at stage ${item.min_stage}`
                    : `Unlock for ${fmt(item.cost)} tokens`
                }
              >
                <div className={styles.itemPreview}>{preview(item.id)}</div>
                {/* Stage-lock badge in the corner — separate from the
                    cost badge so a new player can see BOTH "you can't
                    unlock this yet" AND "this is how much it'll cost". */}
                {!stageOK && (
                  <div className={styles.itemLockOverlay}>
                    <LockIcon size={20} />
                  </div>
                )}
              </button>
              <div className={`${styles.itemLabel} ${!canUnlock ? styles.itemLabelLocked : ''}`}>
                {item.label}
              </div>
              <div className={styles.itemPriceTag}>
                <GoldCoinIcon size={12} />
                {fmt(item.cost)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function ShopModal({ open, onClose, pet, onUnlock, onBuyBattery }: ShopModalProps) {
  const accent = resolveColor(pet.outfit.accent_color, pet.catalog.accentColors, '#FF4F19')!

  const lockedAntennas = pet.catalog.antennas.filter((a) => !pet.unlocks.includes(a.id))
  const lockedHats = pet.catalog.accessories.filter((a) => !pet.unlocks.includes(a.id))
  const lockedLocations = pet.catalog.locations.filter((l) => !pet.unlocks.includes(l.id))
  const allUnlockable = lockedAntennas.length === 0 && lockedHats.length === 0 && lockedLocations.length === 0

  // Defensive ?? defaults so an older backend snapshot (one that hasn't
  // been redeployed since the battery-purchase feature shipped) still
  // renders sensible numbers instead of `undefined` strings.
  const batteryCost = pet.catalog.batteryPurchaseCost ?? 5000
  const batteryMax = pet.catalog.batteryInventoryMax ?? 99
  const spendable = pet.spendableTokens ?? pet.lifetimeTokens
  const inventoryFull = pet.batteryInventory >= batteryMax
  const canAfford = spendable >= batteryCost
  const canBuyBattery = !inventoryFull && canAfford

  // Coin-spend float effect — every unlock / battery buy pushes a
  // `-X tokens` chip that floats up from the CLICKED BUTTON's center
  // and fades. Position is captured at click time (viewport coords)
  // so the effect lands exactly where the user pressed, regardless of
  // modal scroll position. The chip is removed automatically after
  // the animation duration so long sessions don't accumulate DOM nodes.
  const [spendEffects, setSpendEffects] = useState<
    { id: number; amount: number; x: number; y: number }[]
  >([])
  const nextEffectId = useRef(0)
  const SPEND_EFFECT_MS = 900
  const triggerSpend = (amount: number, x: number, y: number) => {
    const id = nextEffectId.current++
    setSpendEffects((prev) => [...prev, { id, amount, x, y }])
    window.setTimeout(() => {
      setSpendEffects((prev) => prev.filter((e) => e.id !== id))
    }, SPEND_EFFECT_MS)
  }
  /** Extract the center of a click event's target in viewport coords. */
  const clickCenter = (e: React.MouseEvent): { x: number; y: number } => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
  }
  const handleUnlock = (id: string, cost: number, e: React.MouseEvent) => {
    if (cost > 0) {
      const c = clickCenter(e)
      triggerSpend(cost, c.x, c.y)
    }
    onUnlock(id)
  }
  const handleBuyBattery = (e: React.MouseEvent) => {
    const c = clickCenter(e)
    triggerSpend(batteryCost, c.x, c.y)
    onBuyBattery()
  }

  return (
    <>
      {/* Fixed-position spend chips — rendered as a sibling of the
          Modal so they overlay the entire viewport. Each chip is
          positioned at the click point captured when the user pressed
          unlock/buy, and animates up + fades via CSS. */}
      {spendEffects.map((e) => (
        <span
          key={e.id}
          className={styles.spendEffectFloat}
          style={{ left: e.x, top: e.y }}
        >
          <GoldCoinIcon size={14} />
          −{fmt(e.amount)}
        </span>
      ))}
    <Modal open={open} onClose={onClose} title="Shop">
      <div className={styles.walletBar}>
        <span
          className={styles.walletBarLabel}
          style={{ display: 'inline-flex', alignItems: 'center' }}
          aria-label="Wallet"
        >
          <GoldCoinIcon size={22} />
        </span>
        <span className={styles.walletBarValue}>
          {/* Spendable = lifetime − spent. This is what actually
              decreases on every purchase, so it's the only number
              that makes sense to lead with. Lifetime is still tracked
              internally and gates stage unlocks, but the user sees
              their growth stage elsewhere. */}
          <span>
            {spendable.toLocaleString()} tokens
          </span>
          <span
            className={styles.walletInfoWrap}
            tabIndex={0}
            role="button"
            aria-label="How the token economy works"
          >
            <InfoIcon size={16} />
            <div className={styles.walletInfoTooltip} role="tooltip">
              <div className={styles.walletInfoTitle}>Token Economy</div>
              <p style={{ margin: '0 0 8px' }}>
                The number shown is your <strong>token credits</strong>
                , what you have left to spend right now. Every
                unlock and every battery purchase deducts from it.
              </p>
              <p style={{ margin: '0 0 8px' }}>
                Tokens are earned automatically as your agent runs
                tasks. Your total earnings (separate from credits)
                is what graduates your pet to its next growth stage
                in the background.
              </p>
              <p style={{ margin: 0 }}>
                Feeding a battery refills hunger and lifts mood.
                Without batteries on hand the pet gets hungry over
                time, so it is worth keeping a few in reserve.
              </p>
            </div>
          </span>
        </span>
      </div>

      {/* Batteries — always present, always purchasable (until inventory full). */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>Batteries</div>
        <div className={styles.batteryRow}>
          <div className={styles.batteryRowIcon}>
            <BatterySprite />
          </div>
          <div className={styles.batteryRowInfo}>
            <div className={styles.batteryRowTitle}>Battery</div>
            <div className={styles.batteryRowMeta}>
              Inventory {pet.batteryInventory} / {batteryMax}
            </div>
          </div>
          <button
            className={styles.batteryRowBuy}
            onClick={(e) => canBuyBattery && handleBuyBattery(e)}
            disabled={!canBuyBattery}
            title={
              inventoryFull
                ? 'Inventory full'
                : !canAfford
                ? 'Not enough tokens'
                : `Buy 1 battery for ${fmt(batteryCost)} tokens`
            }
          >
            Buy · {fmt(batteryCost)}
          </button>
        </div>
      </div>

      {allUnlockable ? (
        <div className={styles.emptyState}>Nothing left to unlock.</div>
      ) : (
        <>
          <ShopSection
            title="Antennas"
            items={pet.catalog.antennas}
            preview={(id) => <AntennaPreview variantId={id} color={accent} />}
            pet={pet}
            onUnlock={handleUnlock}
          />
          <ShopSection
            title="Hats"
            items={pet.catalog.accessories}
            preview={(id) => <AccessoryPreview accessoryId={id} />}
            pet={pet}
            onUnlock={handleUnlock}
          />
          {lockedLocations.length > 0 && (
            <div className={styles.section}>
              <div className={styles.sectionHeader}>Locations</div>
              <div className={styles.locationGrid}>
                {lockedLocations.map((loc) => {
                  const affordable = spendable >= loc.cost
                  return (
                    <div key={loc.id} className={styles.locationWrapper}>
                      <button
                        className={`${styles.locationCell} ${!affordable ? styles.locationCellLocked : ''}`}
                        onClick={(e) => affordable && handleUnlock(loc.id, loc.cost, e)}
                        disabled={!affordable}
                        title={
                          affordable
                            ? `Unlock for ${fmt(loc.cost)} tokens`
                            : `Need ${fmt(loc.cost)} tokens`
                        }
                      >
                        <img
                          src={loc.day_image}
                          alt=""
                          className={styles.locationPreview}
                          onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
                        />
                      </button>
                      <div className={`${styles.itemLabel} ${!affordable ? styles.itemLabelLocked : ''}`}>
                        {loc.label}
                      </div>
                      <div className={styles.itemPriceTag}>
                        <GoldCoinIcon size={12} />
                        {fmt(loc.cost)}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </>
      )}
    </Modal>
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Customize — split layout: mascot preview on the left, sections right
// ─────────────────────────────────────────────────────────────────────
interface CustomizeModalProps extends ModalProps {
  pet: PetState
  onSetOutfit: (outfit: Partial<{ body_color: string; accent_color: string; antenna: string; accessory: string | null }>) => void
}

export function CustomizeModal({ open, onClose, pet, onSetOutfit }: CustomizeModalProps) {
  // A color value is "custom" when it isn't one of the catalog ids —
  // i.e. it was picked from the rainbow swatch (stored as #RRGGBB).
  const isCustomBody = !pet.catalog.bodyColors.some((c) => c.id === pet.outfit.body_color)
  const isCustomAccent = !pet.catalog.accentColors.some((c) => c.id === pet.outfit.accent_color)
  const bodyColor = resolveColor(pet.outfit.body_color, pet.catalog.bodyColors, '#FFFEFE')!
  const accent = resolveColor(pet.outfit.accent_color, pet.catalog.accentColors, '#FF4F19')!

  // Hidden <input type="color"> elements are clicked imperatively by
  // the visible swatch buttons so we get the native picker UI without
  // having to style it.
  const bodyColorInputRef = useRef<HTMLInputElement>(null)
  const accentColorInputRef = useRef<HTMLInputElement>(null)

  return (
    <Modal open={open} onClose={onClose} title="Customize">
      <div className={styles.customizeLayout}>
        {/* LEFT: live mascot preview reflecting current outfit. */}
        <div className={styles.customizeMascot}>
          <CraftBotMascot
            state="resting"
            size={220}
            stage={pet.stage}
            bodyColor={bodyColor}
            accentColor={accent}
            antennaVariant={pet.outfit.antenna}
            accessory={pet.outfit.accessory}
          />
        </div>

        {/* RIGHT: customization sections. */}
        <div className={styles.customizeOptions}>
          <div className={styles.section}>
            <div className={styles.sectionHeader}>Body</div>
            <div className={styles.swatchGrid}>
              {pet.catalog.bodyColors.map((c) => (
                <button
                  key={c.id}
                  className={`${styles.swatchCell} ${pet.outfit.body_color === c.id ? styles.swatchSelected : ''}`}
                  style={{ background: c.value }}
                  onClick={() => onSetOutfit({ body_color: c.id })}
                  aria-label={c.label}
                  title={c.label}
                />
              ))}
              {/* Custom color — opens native color picker; when a custom
                  color is active the swatch shows that color, otherwise
                  the rainbow gradient + "+" indicates it's pickable. */}
              <button
                type="button"
                className={`${styles.swatchCell} ${styles.swatchCustom} ${isCustomBody ? styles.swatchSelected : ''}`}
                style={isCustomBody ? { background: bodyColor } : undefined}
                onClick={() => bodyColorInputRef.current?.click()}
                aria-label="Custom body color"
                title={isCustomBody ? `Custom: ${bodyColor}` : 'Pick a custom body color'}
              >
                {!isCustomBody && <span className={styles.swatchCustomLabel}>+</span>}
                <input
                  ref={bodyColorInputRef}
                  type="color"
                  value={isCustomBody ? bodyColor : '#FFFEFE'}
                  onChange={(e) => onSetOutfit({ body_color: e.target.value })}
                  className={styles.swatchCustomInput}
                  tabIndex={-1}
                  aria-hidden="true"
                />
              </button>
            </div>
          </div>

          <div className={styles.section}>
            <div className={styles.sectionHeader}>Accent</div>
            <div className={styles.swatchGrid}>
              {pet.catalog.accentColors.map((c) => (
                <button
                  key={c.id}
                  className={`${styles.swatchCell} ${pet.outfit.accent_color === c.id ? styles.swatchSelected : ''}`}
                  style={{ background: c.value }}
                  onClick={() => onSetOutfit({ accent_color: c.id })}
                  aria-label={c.label}
                  title={c.label}
                />
              ))}
              <button
                type="button"
                className={`${styles.swatchCell} ${styles.swatchCustom} ${isCustomAccent ? styles.swatchSelected : ''}`}
                style={isCustomAccent ? { background: accent } : undefined}
                onClick={() => accentColorInputRef.current?.click()}
                aria-label="Custom accent color"
                title={isCustomAccent ? `Custom: ${accent}` : 'Pick a custom accent color'}
              >
                {!isCustomAccent && <span className={styles.swatchCustomLabel}>+</span>}
                <input
                  ref={accentColorInputRef}
                  type="color"
                  value={isCustomAccent ? accent : '#FF4F19'}
                  onChange={(e) => onSetOutfit({ accent_color: e.target.value })}
                  className={styles.swatchCustomInput}
                  tabIndex={-1}
                  aria-hidden="true"
                />
              </button>
            </div>
          </div>

          {pet.stage >= 2 && (
            <div className={styles.section}>
              <div className={styles.sectionHeader}>Antenna</div>
              <div className={styles.itemGrid}>
                {pet.catalog.antennas.map((a) => {
                  const unlocked = pet.unlocks.includes(a.id)
                  const selected = pet.outfit.antenna === a.id
                  return (
                    <div key={a.id} className={styles.itemWrapper}>
                      <button
                        className={`${styles.itemCell} ${selected ? styles.itemCellSelected : ''} ${!unlocked ? styles.itemCellLocked : ''}`}
                        onClick={() => unlocked && onSetOutfit({ antenna: a.id })}
                        disabled={!unlocked}
                        aria-label={a.label}
                        title={a.label}
                      >
                        <div className={styles.itemPreview}>
                          <AntennaPreview variantId={a.id} color={accent} />
                        </div>
                        {!unlocked && (
                          <div className={styles.itemLockOverlay}>
                            <LockIcon size={20} />
                          </div>
                        )}
                      </button>
                      <div className={`${styles.itemLabel} ${!unlocked ? styles.itemLabelLocked : ''}`}>
                        {a.label}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          <div className={styles.section}>
            <div className={styles.sectionHeader}>Hat</div>
            <div className={styles.itemGrid}>
              <div className={styles.itemWrapper}>
                <button
                  className={`${styles.itemCell} ${pet.outfit.accessory === null ? styles.itemCellSelected : ''}`}
                  onClick={() => onSetOutfit({ accessory: null })}
                  aria-label="None"
                  title="None"
                >
                  <div className={styles.noneIndicator}>—</div>
                </button>
                <div className={styles.itemLabel}>None</div>
              </div>
              {pet.catalog.accessories.map((a) => {
                const unlocked = pet.unlocks.includes(a.id)
                const selected = pet.outfit.accessory === a.id
                return (
                  <div key={a.id} className={styles.itemWrapper}>
                    <button
                      className={`${styles.itemCell} ${selected ? styles.itemCellSelected : ''} ${!unlocked ? styles.itemCellLocked : ''}`}
                      onClick={() => unlocked && onSetOutfit({ accessory: a.id })}
                      disabled={!unlocked}
                      aria-label={a.label}
                      title={a.label}
                    >
                      <div className={styles.itemPreview}>
                        <AccessoryPreview accessoryId={a.id} />
                      </div>
                      {!unlocked && (
                        <div className={styles.itemLockOverlay}>
                          <LockIcon size={20} />
                        </div>
                      )}
                    </button>
                    <div className={`${styles.itemLabel} ${!unlocked ? styles.itemLabelLocked : ''}`}>
                      {a.label}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </Modal>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Location — picker for the stage background
// ─────────────────────────────────────────────────────────────────────
interface LocationModalProps extends ModalProps {
  pet: PetState
  onSetLocation: (id: string) => void
}

export function LocationModal({ open, onClose, pet, onSetLocation }: LocationModalProps) {
  return (
    <Modal open={open} onClose={onClose} title="Location">
      <div className={styles.locationGrid}>
        {pet.catalog.locations.map((l) => {
          const unlocked = pet.unlocks.includes(l.id)
          const selected = pet.location === l.id
          return (
            <div key={l.id} className={styles.locationWrapper}>
              <button
                className={`${styles.locationCell} ${selected ? styles.locationCellSelected : ''} ${!unlocked ? styles.locationCellLocked : ''}`}
                onClick={() => unlocked && onSetLocation(l.id)}
                disabled={!unlocked}
                aria-label={l.label}
                title={l.label}
              >
                <img
                  src={l.day_image}
                  alt=""
                  className={styles.locationPreview}
                  onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
                />
                {!unlocked && (
                  <div className={styles.itemLockOverlay}>
                    <LockIcon size={22} />
                  </div>
                )}
              </button>
              <div className={`${styles.itemLabel} ${!unlocked ? styles.itemLabelLocked : ''}`}>
                {l.label}
              </div>
            </div>
          )
        })}
      </div>
    </Modal>
  )
}
