// Canonical action-name registry + shared helpers for the two remaining
// action display surfaces: the compact timeline rows (ActivityBlocks.tsx)
// and the mascot speech-bubble formatters (mascotFormatters.ts).
//
// SupportedActionName is the shared type between those registries: the
// mascot's FORMATTER_REGISTRY is typed against it, so adding a name here
// forces a matching formatter (and vice versa).

/** Canonical list of every action name with bespoke display handling. */
export const SUPPORTED_ACTION_NAMES = [
  // file ops
  'stream_edit',
  'read_file',
  'find_files',
  'list_folder',
  'convert_to_pdf',
  'convert_from_pdf',
  'read_pdf',
  'convert_to_markdown',
  // code execution
  'run_python',
  'run_shell',
  // web
  'web_search',
  'web_fetch',
  'http_request',
  // media
  'generate_image',
  'describe_image',
  'perform_ocr',
  'understand_video',
  // search
  'grep_files',
  'memory_search',
  // messaging
  'send_message',
  'send_message_with_attachment',
  // todos
  'update_todos',
] as const

export type SupportedActionName = typeof SUPPORTED_ACTION_NAMES[number]

/** Normalize an incoming action name (which may arrive snake_case, with
 *  spaces, or with dashes from skill metadata) into its canonical form. */
export function normalizeActionName(name: string): string {
  return name.toLowerCase().replace(/[\s-]+/g, '_')
}

/** Type guard — checks at runtime whether a normalized name is one of
 *  the known action names. Used to safely index the registries. */
export function isSupportedActionName(name: string): name is SupportedActionName {
  return (SUPPORTED_ACTION_NAMES as readonly string[]).includes(name)
}

// ─────────────────────────────────────────────────────────────────────
// update_todos payload extraction (shared by the timeline row's
// "N/M done" preview and the mascot formatter's checklist summary)
// ─────────────────────────────────────────────────────────────────────

export interface TodoEntry { content: string; status: string }

export function extractTodos(inputObj: Record<string, unknown> | null): TodoEntry[] | null {
  if (!inputObj) return null
  const raw = inputObj.todos
  let items: unknown[] | null = null
  if (Array.isArray(raw)) items = raw
  else if (typeof raw === 'string') {
    try {
      const norm = raw
        .replace(/\bTrue\b/g, 'true')
        .replace(/\bFalse\b/g, 'false')
        .replace(/\bNone\b/g, 'null')
        .replace(/'/g, '"')
      const parsed = JSON.parse(norm)
      if (Array.isArray(parsed)) items = parsed
    } catch { /* fall through */ }
  }
  if (!items) return null
  const todos: TodoEntry[] = []
  for (const it of items) {
    if (it && typeof it === 'object') {
      const obj = it as Record<string, unknown>
      if (typeof obj.content === 'string' && typeof obj.status === 'string') {
        todos.push({ content: obj.content, status: obj.status })
      }
    }
  }
  return todos.length > 0 ? todos : null
}
