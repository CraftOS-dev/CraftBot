export type VoiceGender = 'male' | 'female'

// Well-known given names shipped with common OS/browser voice packs. The Web
// Speech API does not expose gender, so we infer it from the voice name. This
// is best-effort — unknown voices simply return null (treated as "either").
const FEMALE_NAMES = [
  'zira', 'samantha', 'victoria', 'karen', 'moira', 'tessa', 'fiona', 'veena',
  'susan', 'allison', 'ava', 'serena', 'kate', 'hazel', 'catherine', 'amelie',
  'amélie', 'anna', 'helena', 'sabina', 'laura', 'paulina', 'sara', 'alice',
  'elsa', 'carmit', 'damayanti', 'ellen', 'ioana', 'joana', 'kanya', 'kyoko',
  'lekha', 'luciana', 'mariska', 'mei-jia', 'melina', 'milena', 'monica',
  'mónica', 'nora', 'paola', 'sin-ji', 'tarik', 'ting-ting', 'yuna', 'zosia',
  'zuzana', 'linh', 'nicky', 'aria', 'jenny', 'michelle', 'clara', 'sonia',
  'libby', 'maisie', 'natasha', 'yan', 'xiaoxiao', 'hyunsu',
]

const MALE_NAMES = [
  'david', 'mark', 'george', 'daniel', 'alex', 'fred', 'thomas', 'jorge',
  'diego', 'yuri', 'pavel', 'rishi', 'aaron', 'arthur', 'gordon', 'oliver',
  'reed', 'rocko', 'eddy', 'grandpa', 'guy', 'jamie', 'ryan', 'brian', 'james',
  'lee', 'luca', 'carlos', 'juan', 'felipe', 'maged', 'nikos', 'xander',
  'kenji', 'otoya', 'hattori', 'yunjhe', 'liang', 'kangkang', 'william',
  'christopher', 'eric', 'roger', 'steffan', 'davis', 'tony', 'nam',
]

/**
 * Best-effort gender for a speech-synthesis voice, inferred from its name.
 * Returns null when it can't be determined.
 */
export function inferVoiceGender(voice: SpeechSynthesisVoice): VoiceGender | null {
  const name = (voice.name || '').toLowerCase()

  // Explicit markers first. `\bfemale\b` is checked before `\bmale\b`; the
  // latter cannot match inside "female" because there is no word boundary
  // between the "e" and "m".
  if (/\bfemale\b/.test(name) || /\bwoman\b/.test(name)) return 'female'
  if (/\bmale\b/.test(name) || /\bman\b/.test(name)) return 'male'

  for (const n of FEMALE_NAMES) {
    if (name.includes(n)) return 'female'
  }
  for (const n of MALE_NAMES) {
    if (name.includes(n)) return 'male'
  }
  return null
}
