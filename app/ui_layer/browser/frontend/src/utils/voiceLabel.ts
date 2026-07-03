import { inferVoiceGender } from './voiceGender'

// Vendor/engine prefixes we hide from the user — they don't care which company
// shipped the voice, only what it sounds like.
const VENDOR_PREFIX =
  /^(google|microsoft|apple|amazon|samsung|ibm|nuance|espeak|e-speak)\s+/i

/**
 * Turn a raw system voice name into something friendly for the settings
 * dropdown. Strips the vendor prefix and the technical
 * "- Language (Region)" suffix, folds the gender word into a "· Female/Male"
 * tag, and keeps a readable character/language name.
 *
 * Examples:
 *   "Microsoft David - English (United States)" → "David · Male"
 *   "Google UK English Female"                  → "UK English · Female"
 *   "Google 國語（臺灣）"                          → "國語（臺灣）"
 */
export function friendlyVoiceName(voice: SpeechSynthesisVoice): string {
  let name = (voice.name || '').trim()

  name = name.replace(VENDOR_PREFIX, '')

  // Microsoft-style "David - English (United States)": keep the given name.
  const dashIdx = name.indexOf(' - ')
  if (dashIdx !== -1) {
    name = name.slice(0, dashIdx).trim()
  }

  // The gender is rendered as a separate tag, so drop the word from the name.
  name = name
    .replace(/\b(fe)?male\b/gi, '')
    .replace(/\s{2,}/g, ' ')
    .replace(/[\-–—•·|,]+\s*$/, '')
    .trim()

  if (!name) name = (voice.name || 'Voice').trim()

  const gender = inferVoiceGender(voice)
  const tag = gender === 'female' ? ' · Female' : gender === 'male' ? ' · Male' : ''
  return `${name}${tag}`
}
