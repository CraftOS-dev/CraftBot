/**
 * Convert a Markdown string into plain text suitable for text-to-speech.
 *
 * This is deliberately lightweight — it strips the syntax that sounds wrong
 * when read aloud (emphasis markers, code fences, link URLs, headings) while
 * preserving the readable prose and the visible text of links. It is not a
 * full Markdown parser; the goal is "sounds natural", not perfect fidelity.
 */
export function stripMarkdown(input: string): string {
  let text = input

  // Remove fenced code blocks entirely — reading source aloud is noise.
  text = text.replace(/```[\s\S]*?```/g, ' ')
  // Inline code: keep the contents, drop the backticks.
  text = text.replace(/`([^`]+)`/g, '$1')

  // Images: drop entirely (alt text is rarely useful when spoken).
  text = text.replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
  // Links: keep the visible label, drop the URL.
  text = text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')

  // Headings, blockquotes and list markers at line start.
  text = text.replace(/^\s{0,3}#{1,6}\s+/gm, '')
  text = text.replace(/^\s*>\s?/gm, '')
  text = text.replace(/^\s*[-*+]\s+/gm, '')
  text = text.replace(/^\s*\d+\.\s+/gm, '')

  // Emphasis / bold / strikethrough markers.
  text = text.replace(/(\*\*|__)(.*?)\1/g, '$2')
  text = text.replace(/(\*|_)(.*?)\1/g, '$2')
  text = text.replace(/~~(.*?)~~/g, '$1')

  // Horizontal rules and stray table pipes.
  text = text.replace(/^\s*([-*_])(\s*\1){2,}\s*$/gm, ' ')
  text = text.replace(/\|/g, ' ')

  // Collapse whitespace runs but keep paragraph breaks for natural pauses.
  text = text.replace(/[ \t]+/g, ' ')
  text = text.replace(/\n{3,}/g, '\n\n')

  return text.trim()
}
