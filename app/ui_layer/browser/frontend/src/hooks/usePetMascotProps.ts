import { useCallback, useMemo } from 'react'
import type { MascotPetProps } from '@mascot'
import { useAppSelector } from '../store/hooks'
import {
  selectPet,
  selectPetStageUpNonce,
  selectPetFedNonce,
  selectPetPettedNonce,
} from '../store/selectors/pet'
import { useWebSocket } from '../contexts/WebSocketContext'

/** Resolve a body/accent color value. The backend stores either a
 *  catalog id ("default", "cream", ...) OR a raw "#RRGGBB" string when
 *  the user picked from the custom-color swatch. This helper transparently
 *  handles both. */
export function resolveColor(
  idOrHex: string | undefined,
  catalog: { id: string; value: string }[],
  fallback?: string,
): string | undefined {
  if (!idOrHex) return fallback
  const hit = catalog.find(c => c.id === idOrHex)
  if (hit) return hit.value
  if (idOrHex.startsWith('#')) return idOrHex
  return fallback
}

/** Bundle the pet-state Redux selectors + ws callbacks into a single
 *  prop set ready to spread onto `<MascotDisplay {...props} />`.
 *
 *  Used by both the chat panel mascot and the dedicated pet panel so the
 *  visual identity (stage, outfit, location) stays consistent across both
 *  views. Drag-release persists position via the WebSocket. */
export function usePetMascotProps(): MascotPetProps {
  const pet = useAppSelector(selectPet)
  const stageUpNonce = useAppSelector(selectPetStageUpNonce)
  const fedNonce = useAppSelector(selectPetFedNonce)
  const pettedNonce = useAppSelector(selectPetPettedNonce)
  const { petSetPosition, petStroke } = useWebSocket()

  const onDragRelease = useCallback((x: number, _y: number) => {
    petSetPosition(x, 0)
  }, [petSetPosition])

  // Clicking the mascot = petting it (mood bump). Shared by both chat
  // and pet panels — the click also runs the local "happy" reaction.
  const onClick = useCallback(() => {
    petStroke()
  }, [petStroke])

  const location = useMemo(
    () => pet.catalog.locations.find(l => l.id === pet.location) ?? null,
    [pet.catalog.locations, pet.location],
  )
  const bodyColor = useMemo(
    () => resolveColor(pet.outfit.body_color, pet.catalog.bodyColors),
    [pet.catalog.bodyColors, pet.outfit.body_color],
  )
  const accentColor = useMemo(
    () => resolveColor(pet.outfit.accent_color, pet.catalog.accentColors),
    [pet.catalog.accentColors, pet.outfit.accent_color],
  )

  return {
    stage: pet.stage,
    mood: pet.mood,
    hunger: pet.hunger,
    bodyColor,
    accentColor,
    antennaVariant: pet.outfit.antenna,
    accessory: pet.outfit.accessory,
    location,
    stageUpNonce,
    fedNonce,
    pettedNonce,
    onDragRelease,
    onClick,
  }
}
