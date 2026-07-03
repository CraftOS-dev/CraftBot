/**
 * Best-effort language detection from a text sample, based on Unicode script
 * ranges. Returns a BCP-47 primary language subtag (e.g. "ja", "ko", "ar") for
 * distinctive scripts, or `null` when the script can't pin down a language
 * (most notably the Latin script, which is shared by many languages).
 *
 * This is intentionally lightweight — no ML, no dictionaries. It exists so that
 * read-aloud can pick a voice that matches the language of a chat message
 * (reading Japanese with a Japanese voice, etc.) rather than mispronouncing it
 * with the default voice. For Latin-script text we return `null` so the caller
 * falls back to the user's chosen voice / the browser default.
 */
export function detectLanguage(text: string): string | null {
  if (!text) return null

  const counts: Record<string, number> = {}
  const bump = (key: string) => {
    counts[key] = (counts[key] ?? 0) + 1
  }

  for (const ch of text) {
    const cp = ch.codePointAt(0)
    if (cp === undefined) continue

    // Japanese kana are decisive for Japanese.
    if ((cp >= 0x3040 && cp <= 0x30ff) || (cp >= 0x31f0 && cp <= 0x31ff)) bump('ja')
    // Hangul → Korean.
    else if ((cp >= 0xac00 && cp <= 0xd7a3) || (cp >= 0x1100 && cp <= 0x11ff) || (cp >= 0x3130 && cp <= 0x318f)) bump('ko')
    // Han ideographs — ambiguous between zh/ja; counted separately and only
    // resolved to Chinese if no kana were seen.
    else if ((cp >= 0x4e00 && cp <= 0x9fff) || (cp >= 0x3400 && cp <= 0x4dbf)) bump('han')
    // Cyrillic → Russian (as the most common default).
    else if (cp >= 0x0400 && cp <= 0x04ff) bump('ru')
    // Arabic.
    else if ((cp >= 0x0600 && cp <= 0x06ff) || (cp >= 0x0750 && cp <= 0x077f)) bump('ar')
    // Hebrew.
    else if (cp >= 0x0590 && cp <= 0x05ff) bump('he')
    // Devanagari → Hindi.
    else if (cp >= 0x0900 && cp <= 0x097f) bump('hi')
    // Thai.
    else if (cp >= 0x0e00 && cp <= 0x0e7f) bump('th')
    // Greek.
    else if (cp >= 0x0370 && cp <= 0x03ff) bump('el')
  }

  // Kana present → Japanese, even if Han is also present (mixed script).
  if (counts.ja) return 'ja'
  // Han without kana → Chinese.
  if (counts.han) counts.zh = counts.han
  delete counts.han

  let best: string | null = null
  let bestCount = 0
  for (const [lang, count] of Object.entries(counts)) {
    if (count > bestCount) {
      best = lang
      bestCount = count
    }
  }

  return best
}
