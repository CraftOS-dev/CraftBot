/**
 * Avatar (SYSTEM-MANAGED — do not edit)
 *
 *   <Avatar name="Ada Lovelace" />            // initials, deterministic color
 *   <Avatar name="Ada" src={photoUrl} />      // image with initials fallback
 */

import { useState } from 'react'

export interface AvatarProps {
  /** Display name — initials and color derive from it. */
  name: string
  src?: string
  /** Diameter in px (default 32). */
  size?: number
}

const AVATAR_COLORS = [
  'var(--color-primary)',
  'var(--color-success)',
  'var(--color-warning)',
  'var(--color-error)',
  'var(--color-info)',
]

function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[words.length - 1][0]).toUpperCase()
}

function colorOf(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length]
}

export function Avatar({ name, src, size = 32 }: AvatarProps) {
  const [broken, setBroken] = useState(false)
  const color = colorOf(name)

  if (src && !broken) {
    return (
      <img
        src={src}
        alt={name}
        onError={() => setBroken(true)}
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          objectFit: 'cover',
          flexShrink: 0,
        }}
      />
    )
  }

  return (
    <span
      title={name}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: size,
        height: size,
        borderRadius: '50%',
        backgroundColor: `color-mix(in srgb, ${color} 20%, transparent)`,
        color,
        fontSize: size * 0.38,
        fontWeight: 'var(--font-weight-semibold)' as any,
        letterSpacing: '0.02em',
        flexShrink: 0,
        userSelect: 'none',
      }}
    >
      {initialsOf(name)}
    </span>
  )
}
