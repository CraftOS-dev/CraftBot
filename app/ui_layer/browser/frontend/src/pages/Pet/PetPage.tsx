import { useEffect, useState } from 'react'
import { MascotDisplay } from '@mascot'
import { useAppSelector } from '../../store/hooks'
import { selectPet } from '../../store/selectors/pet'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { usePetMascotProps } from '../../hooks'
import { PetHUD } from './PetHUD'
import { ShopModal, CustomizeModal, LocationModal } from './PetModals'
import styles from './PetPage.module.css'

type OpenModal = 'shop' | 'wardrobe' | 'location' | null

export function PetPage() {
  const pet = useAppSelector(selectPet)
  const petMascotProps = usePetMascotProps()
  const {
    petFeed,
    petBuyBattery,
    petSetOutfit,
    petSetLocation,
    petUnlock,
    petRequestState,
  } = useWebSocket()

  // Pull a fresh snapshot when the page mounts so a direct nav to /pet
  // before WS `init` fires still shows up-to-date state.
  useEffect(() => { petRequestState() }, [petRequestState])

  const [openModal, setOpenModal] = useState<OpenModal>(null)
  const close = () => setOpenModal(null)

  // Energy reads as fullness (100 = full battery, 0 = starving).
  const energy = 100 - pet.hunger

  return (
    <div className={styles.page}>
      <MascotDisplay variant="panel" mascotSize={320} {...petMascotProps} />

      <PetHUD
        mood={pet.mood}
        energy={energy}
        batteryCount={pet.batteryInventory}
        onOpenShop={() => setOpenModal('shop')}
        onFeed={petFeed}
        onOpenWardrobe={() => setOpenModal('wardrobe')}
        onOpenLocation={() => setOpenModal('location')}
      />

      <ShopModal
        open={openModal === 'shop'}
        onClose={close}
        pet={pet}
        onUnlock={petUnlock}
        onBuyBattery={petBuyBattery}
      />
      <CustomizeModal
        open={openModal === 'wardrobe'}
        onClose={close}
        pet={pet}
        onSetOutfit={petSetOutfit}
      />
      <LocationModal
        open={openModal === 'location'}
        onClose={close}
        pet={pet}
        onSetLocation={petSetLocation}
      />
    </div>
  )
}
