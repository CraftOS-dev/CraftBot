import React from 'react'
import { Square, CheckSquare } from 'lucide-react'
import type { ActionItem } from '../../types'
import {
  Section, FilePathChip, UrlChip, CodeBlock, Terminal, ResultList, ResultCard,
  ImageThumbnail, ImageThumbnailRow, MetaPill, MetaRow, DiffView, Collapsible,
  Pending, WaitForReplyPill, primStyles,
} from './primitives'
import { strField, boolField, arrField, dictField, parseDict } from './parse'

// Renderer contract: receives the action item + pre-parsed input/output dicts
// (each is null if absent or unparseable). Returns the JSX that goes inside
// .actionBox (replacing the default Input/Output sections). The error section
// and "More detail" expansion are still added by ActionBlock.
export interface ActionRendererProps {
  item: ActionItem
  inputObj: Record<string, unknown> | null
  outputObj: Record<string, unknown> | null
  onOpenFile: (path: string) => void
}

export type ActionRenderer = React.FC<ActionRendererProps>

// Turn a workspace-side absolute or relative path into a URL the static
// `/api/workspace/{path}` handler can serve. The server's _validate_path
// rejects anything outside the workspace, so external paths will 404 here —
// the <img> onError fallback renders a placeholder instead of a broken icon.
function toWorkspaceUrl(absPath: string): string {
  const normalized = absPath.replace(/\\/g, '/').replace(/^\/+/, '')
  return `/api/workspace/${encodeURI(normalized)}`
}

// ─────────────────────────────────────────────────────────────────────
// FILE OPS
// ─────────────────────────────────────────────────────────────────────

const StreamEditRenderer: ActionRenderer = ({ inputObj, onOpenFile }) => {
  const filePath = strField(inputObj, 'file_path') ?? ''
  const oldStr = strField(inputObj, 'old_string') ?? ''
  const newStr = strField(inputObj, 'new_string') ?? ''

  return (
    <>
      <Section label="File">
        {filePath
          ? <FilePathChip path={filePath} onOpen={onOpenFile} />
          : <Pending label="Waiting for file…" />}
      </Section>
      <Section label="Diff">
        {oldStr || newStr
          ? <DiffView oldText={oldStr} newText={newStr} />
          : <Pending label="Waiting for edit…" />}
      </Section>
    </>
  )
}

const ReadFileRenderer: ActionRenderer = ({ inputObj, outputObj, onOpenFile }) => {
  const filePath = strField(inputObj, 'file_path') ?? ''
  const content = strField(outputObj, 'content')

  return (
    <>
      <Section label="File">
        {filePath
          ? <FilePathChip path={filePath} onOpen={onOpenFile} />
          : <Pending label="Waiting for file…" />}
      </Section>
      <Section label="Content">
        {content
          ? <Collapsible text={content} collapsedLines={10} />
          : <Pending label={outputObj ? '(empty)' : 'Reading…'} />}
      </Section>
    </>
  )
}

const FindFilesRenderer: ActionRenderer = ({ inputObj, outputObj, onOpenFile }) => {
  const pattern = strField(inputObj, 'pattern') ?? ''
  const matches = (arrField(outputObj, 'matches') ?? []).filter((m): m is string => typeof m === 'string')

  return (
    <>
      <Section label="Pattern">
        {pattern ? <MetaPill>{pattern}</MetaPill> : <Pending label="Waiting…" />}
      </Section>
      <Section label="Matches">
        {!outputObj
          ? <Pending label="Searching…" />
          : matches.length === 0
            ? <Pending label="No matches." />
            : (
              <div className={primStyles.resultList}>
                {matches.map((m, i) => <FilePathChip key={i} path={m} onOpen={onOpenFile} />)}
              </div>
            )}
      </Section>
    </>
  )
}

const ListFolderRenderer: ActionRenderer = ({ inputObj, outputObj, onOpenFile }) => {
  const path = strField(inputObj, 'path') ?? ''
  const contents = (arrField(outputObj, 'contents') ?? []).filter((c): c is string => typeof c === 'string')
  // list_folder returns names only, not types — fall back to a simple
  // extension heuristic so folder entries get a trailing slash.
  const sorted = [...contents].sort((a, b) => {
    const aIsFolder = !a.includes('.')
    const bIsFolder = !b.includes('.')
    if (aIsFolder !== bIsFolder) return aIsFolder ? -1 : 1
    return a.localeCompare(b)
  })

  return (
    <>
      <Section label="Folder">
        {path
          ? <FilePathChip path={path} onOpen={onOpenFile} showFull />
          : <Pending label="Waiting…" />}
      </Section>
      <Section label="Contents">
        {!outputObj
          ? <Pending label="Listing…" />
          : sorted.length === 0
            ? <Pending label="(empty)" />
            : (
              <div className={primStyles.dirTree}>
                {sorted.map((name, i) => {
                  const isLast = i === sorted.length - 1
                  const branch = isLast ? '└── ' : '├── '
                  const isFolder = !name.includes('.')
                  return (
                    <div key={i}>
                      <span className={primStyles.dirTreeBranch}>{branch}</span>
                      <span className={isFolder ? primStyles.dirTreeFolder : undefined}>
                        {isFolder ? `${name}/` : name}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
      </Section>
    </>
  )
}

// Renderer for convert_to_pdf — handles all source formats via one schema.
const ConvertToPdfRenderer: ActionRenderer = ({ inputObj, outputObj, onOpenFile }) => {
  const outPath = strField(outputObj, 'path') ?? strField(inputObj, 'output_path') ?? ''
  const content = strField(inputObj, 'content') ?? ''
  const sourcePath = strField(inputObj, 'source_path') ?? ''
  const url = strField(inputObj, 'url') ?? ''
  const imagePaths = (arrField(inputObj, 'image_paths') ?? [])
    .filter((p): p is string => typeof p === 'string')

  return (
    <>
      <Section label="Output PDF">
        {outPath
          ? <FilePathChip path={outPath} onOpen={onOpenFile} />
          : <Pending label="Waiting for file…" />}
      </Section>
      <Section label="Source">
        {content
          ? <Collapsible text={content} collapsedLines={8} />
          : sourcePath
            ? <FilePathChip path={sourcePath} onOpen={onOpenFile} />
            : url
              ? <Collapsible text={url} collapsedLines={2} />
              : imagePaths.length
                ? <Collapsible text={imagePaths.join('\n')} collapsedLines={8} />
                : <Pending label="Waiting for source…" />}
      </Section>
    </>
  )
}

const ReadPdfRenderer: ActionRenderer = ({ inputObj, outputObj, onOpenFile }) => {
  const filePath = strField(inputObj, 'file_path') ?? ''
  const contentObj = dictField(outputObj, 'content')
  const elements = arrField(contentObj, 'elements') ?? []
  // Concatenate the extracted text from each layout element so the user sees
  // the file's actual content, not just page counts.
  const text = elements
    .map(el => (el && typeof el === 'object' && !Array.isArray(el)
      ? strField(el as Record<string, unknown>, 'text')
      : null))
    .filter((t): t is string => !!t)
    .join('\n')

  return (
    <>
      <Section label="PDF">
        {filePath
          ? <FilePathChip path={filePath} onOpen={onOpenFile} />
          : <Pending label="Waiting for file…" />}
      </Section>
      <Section label="Extracted Text">
        {!outputObj
          ? <Pending label="Extracting…" />
          : text
            ? <Collapsible text={text} collapsedLines={8} />
            : <Pending label="(no text)" />}
      </Section>
    </>
  )
}

const ConvertToMarkdownRenderer: ActionRenderer = ({ inputObj, outputObj, onOpenFile }) => {
  const input = strField(inputObj, 'input_file') ?? ''
  const output = strField(outputObj, 'md_file') ?? strField(inputObj, 'output_md') ?? ''

  return (
    <>
      <Section label="Source">
        {input
          ? <FilePathChip path={input} onOpen={onOpenFile} />
          : <Pending label="Waiting…" />}
      </Section>
      <Section label="Output">
        {output
          ? <FilePathChip path={output} onOpen={onOpenFile} />
          : <Pending label="Converting…" />}
      </Section>
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────
// CODE EXECUTION
// ─────────────────────────────────────────────────────────────────────

const RunPythonRenderer: ActionRenderer = ({ inputObj, outputObj }) => {
  const code = strField(inputObj, 'code') ?? ''
  const stdout = strField(outputObj, 'stdout') ?? ''
  const stderr = strField(outputObj, 'stderr') ?? ''

  return (
    <>
      <Section label="Code">
        {code
          ? <CodeBlock code={code} lang="python" />
          : <Pending label="Waiting for code…" />}
      </Section>
      <Section label="Output">
        {outputObj
          ? <Terminal stdout={stdout} stderr={stderr} />
          : <Pending label="Running…" />}
      </Section>
    </>
  )
}

const RunShellRenderer: ActionRenderer = ({ inputObj, outputObj }) => {
  const command = strField(inputObj, 'command') ?? ''
  const stdout = strField(outputObj, 'stdout') ?? ''
  const stderr = strField(outputObj, 'stderr') ?? ''

  return (
    <>
      <Section label="Command">
        {command
          ? <CodeBlock code={`$ ${command}`} />
          : <Pending label="Waiting for command…" />}
      </Section>
      <Section label="Output">
        {outputObj
          ? <Terminal stdout={stdout} stderr={stderr} />
          : <Pending label="Running…" />}
      </Section>
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────
// WEB
// ─────────────────────────────────────────────────────────────────────

const WebSearchRenderer: ActionRenderer = ({ inputObj, outputObj }) => {
  const query = strField(inputObj, 'query') ?? ''
  const results = (arrField(outputObj, 'results') ?? []).filter(
    (r): r is Record<string, unknown> => !!r && typeof r === 'object' && !Array.isArray(r),
  )

  return (
    <>
      <Section label="Query">
        {query ? <div>{query}</div> : <Pending label="Waiting…" />}
      </Section>
      <Section label="Results">
        {!outputObj
          ? <Pending label="Searching…" />
          : results.length === 0
            ? <Pending label="No results." />
            : (
              <ResultList>
                {results.map((r, i) => (
                  <ResultCard
                    key={i}
                    title={strField(r, 'title') ?? '(no title)'}
                    url={strField(r, 'url')}
                    snippet={strField(r, 'snippet')}
                  />
                ))}
              </ResultList>
            )}
      </Section>
    </>
  )
}

const WebFetchRenderer: ActionRenderer = ({ inputObj, outputObj }) => {
  const url = strField(inputObj, 'url') ?? ''
  const title = strField(outputObj, 'title')
  const content = strField(outputObj, 'content') ?? ''

  return (
    <>
      <Section label="URL">
        {url
          ? <UrlChip url={url} label={title || url} />
          : <Pending label="Waiting…" />}
      </Section>
      <Section label="Content">
        {!outputObj
          ? <Pending label="Fetching…" />
          : content
            ? <Collapsible text={content} collapsedLines={8} />
            : <Pending label="(empty)" />}
      </Section>
    </>
  )
}

const HttpRequestRenderer: ActionRenderer = ({ inputObj, outputObj }) => {
  const method = (strField(inputObj, 'method') ?? 'GET').toUpperCase()
  const url = strField(inputObj, 'url') ?? ''
  const body = strField(inputObj, 'data')
    ?? (inputObj?.json ? JSON.stringify(inputObj.json, null, 2) : '')
  const respBody = strField(outputObj, 'body') ?? ''

  return (
    <>
      <Section label="Request">
        <MetaRow>
          <MetaPill>{method}</MetaPill>
          {url && <UrlChip url={url} />}
        </MetaRow>
        {body && <CodeBlock code={body} lang="json" />}
      </Section>
      <Section label="Response">
        {!outputObj
          ? <Pending label="Sending…" />
          : respBody
            ? <Collapsible text={respBody} collapsedLines={8} />
            : <Pending label="(empty)" />}
      </Section>
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────
// MEDIA
// ─────────────────────────────────────────────────────────────────────

const GenerateImageRenderer: ActionRenderer = ({ inputObj, outputObj }) => {
  const prompt = strField(inputObj, 'prompt') ?? ''
  const paths = (arrField(outputObj, 'image_paths') ?? []).filter((p): p is string => typeof p === 'string')

  return (
    <>
      <Section label="Prompt">
        {prompt ? <div>{prompt}</div> : <Pending label="Waiting…" />}
      </Section>
      <Section label="Images">
        {!outputObj
          ? <Pending label="Generating…" />
          : paths.length === 0
            ? <Pending label="No images produced." />
            : <ImageThumbnailRow srcs={paths.map(toWorkspaceUrl)} alt={prompt} />}
      </Section>
    </>
  )
}

const DescribeImageRenderer: ActionRenderer = ({ inputObj, outputObj }) => {
  const imagePath = strField(inputObj, 'image_path') ?? ''
  const prompt = strField(inputObj, 'prompt')
  const description = strField(outputObj, 'description') ?? ''

  return (
    <>
      <Section label="Image">
        {imagePath
          ? <ImageThumbnail src={toWorkspaceUrl(imagePath)} alt={prompt ?? imagePath} />
          : <Pending label="Waiting…" />}
        {prompt && <div className={primStyles.pendingPlaceholder}>{prompt}</div>}
      </Section>
      <Section label="Description">
        {!outputObj
          ? <Pending label="Analyzing…" />
          : description
            ? <Collapsible text={description} collapsedLines={6} />
            : <Pending label="(empty)" />}
      </Section>
    </>
  )
}

const PerformOcrRenderer: ActionRenderer = ({ inputObj, outputObj }) => {
  const imagePath = strField(inputObj, 'image_path') ?? ''
  const summary = strField(outputObj, 'summary') ?? ''

  return (
    <>
      <Section label="Image">
        {imagePath
          ? <ImageThumbnail src={toWorkspaceUrl(imagePath)} alt={imagePath} />
          : <Pending label="Waiting…" />}
      </Section>
      <Section label="Extracted Text">
        {!outputObj
          ? <Pending label="OCR in progress…" />
          : summary
            ? <Collapsible text={summary} collapsedLines={6} />
            : <Pending label="(empty)" />}
      </Section>
    </>
  )
}

const UnderstandVideoRenderer: ActionRenderer = ({ inputObj, outputObj, onOpenFile }) => {
  const videoPath = strField(inputObj, 'video_path') ?? ''
  const query = strField(inputObj, 'query')
  const summary = strField(outputObj, 'summary') ?? ''

  return (
    <>
      <Section label="Video">
        {videoPath
          ? <FilePathChip path={videoPath} onOpen={onOpenFile} />
          : <Pending label="Waiting…" />}
        {query && <div className={primStyles.pendingPlaceholder}>{query}</div>}
      </Section>
      <Section label="Summary">
        {!outputObj
          ? <Pending label="Analyzing video…" />
          : summary
            ? <Collapsible text={summary} collapsedLines={6} />
            : <Pending label="(empty)" />}
      </Section>
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────
// SEARCH
// ─────────────────────────────────────────────────────────────────────

const GrepFilesRenderer: ActionRenderer = ({ inputObj, outputObj, onOpenFile }) => {
  const pattern = strField(inputObj, 'pattern') ?? ''
  const mode = strField(inputObj, 'output_mode') ?? 'files_with_matches'
  const filenames = (arrField(outputObj, 'filenames') ?? []).filter((f): f is string => typeof f === 'string')
  const content = strField(outputObj, 'content')

  return (
    <>
      <Section label="Pattern">
        {pattern ? <MetaPill>{pattern}</MetaPill> : <Pending label="Waiting…" />}
      </Section>
      <Section label="Results">
        {!outputObj
          ? <Pending label="Searching…" />
          : mode === 'content' && content
            ? <CodeBlock code={content} />
            : filenames.length > 0
              ? (
                <div className={primStyles.resultList}>
                  {filenames.map((f, i) => <FilePathChip key={i} path={f} onOpen={onOpenFile} />)}
                </div>
              )
              : <Pending label="No matches." />}
      </Section>
    </>
  )
}

const MemorySearchRenderer: ActionRenderer = ({ inputObj, outputObj, onOpenFile }) => {
  const query = strField(inputObj, 'query') ?? ''
  const results = (arrField(outputObj, 'results') ?? []).filter(
    (r): r is Record<string, unknown> => !!r && typeof r === 'object' && !Array.isArray(r),
  )

  return (
    <>
      <Section label="Query">
        {query ? <div>{query}</div> : <Pending label="Waiting…" />}
      </Section>
      <Section label="Results">
        {!outputObj
          ? <Pending label="Searching…" />
          : results.length === 0
            ? <Pending label="No matches." />
            : (
              <ResultList>
                {results.map((r, i) => {
                  const title = strField(r, 'title') ?? strField(r, 'section_path') ?? '(memory)'
                  const filePath = strField(r, 'file_path')
                  const summary = strField(r, 'summary')
                  return (
                    <ResultCard
                      key={i}
                      title={title}
                      snippet={summary}
                      onClick={filePath ? () => onOpenFile(filePath) : undefined}
                    />
                  )
                })}
              </ResultList>
            )}
      </Section>
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────
// MESSAGING + TASK CONTROL
// ─────────────────────────────────────────────────────────────────────

const SendMessageRenderer: ActionRenderer = ({ inputObj }) => {
  const message = strField(inputObj, 'message') ?? ''
  const waitForReply = boolField(inputObj, 'wait_for_user_reply')

  return (
    <Section label="Message">
      {message
        ? <div style={{ whiteSpace: 'pre-wrap' }}>{message}</div>
        : <Pending label="Composing…" />}
      {waitForReply && <WaitForReplyPill />}
    </Section>
  )
}

const SendMessageWithAttachmentRenderer: ActionRenderer = ({ inputObj, onOpenFile }) => {
  const message = strField(inputObj, 'message') ?? ''
  const waitForReply = boolField(inputObj, 'wait_for_user_reply')
  const filePaths = (arrField(inputObj, 'file_paths') ?? [])
    .filter((p): p is string => typeof p === 'string')

  return (
    <>
      <Section label="Message">
        {message
          ? <div style={{ whiteSpace: 'pre-wrap' }}>{message}</div>
          : <Pending label="Composing…" />}
        {waitForReply && <WaitForReplyPill />}
      </Section>
      <Section label="Attachments">
        {filePaths.length === 0
          ? <Pending label="(none yet)" />
          : (
            <div className={primStyles.resultList}>
              {filePaths.map((p, i) => <FilePathChip key={i} path={p} onOpen={onOpenFile} />)}
            </div>
          )}
      </Section>
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────
// UPDATE TODOS
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

const UpdateTodosRenderer: ActionRenderer = ({ inputObj }) => {
  const todos = extractTodos(inputObj)
  if (!todos) return <Section label="Todos"><Pending label="(no todos)" /></Section>
  return (
    <Section label="Todos">
      <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        {todos.map((t, i) => {
          const done = t.status === 'completed'
          const inProgress = t.status === 'in_progress'
          return (
            <li key={i} style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 'var(--space-2)',
              padding: 0,
              color: done ? 'var(--text-muted)' : 'var(--text-primary)',
              textDecoration: done ? 'line-through' : 'none',
              fontWeight: inProgress ? 'var(--font-medium)' : 'var(--font-normal)',
              fontSize: 'var(--text-base)',
            }}>
              <span style={{
                display: 'inline-flex',
                alignItems: 'center',
                marginTop: 2,
                color: inProgress ? 'var(--color-primary)' : 'var(--text-muted)',
              }}>
                {done ? <CheckSquare size={16} /> : <Square size={16} />}
              </span>
              <span style={{ flex: 1, wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>{t.content}</span>
            </li>
          )
        })}
      </ul>
    </Section>
  )
}

// ─────────────────────────────────────────────────────────────────────
// REGISTRY
// ─────────────────────────────────────────────────────────────────────

/** Canonical list of every action name the Tasks panel renderer knows about.
 *  This is the SOURCE OF TRUTH for "actions with custom rendering" across
 *  the app — the mascot's speech-bubble formatter registry (in
 *  mascotFormatters.ts) is typed against `SupportedActionName` so it must
 *  cover the same set. If you add a new renderer below, add its name here
 *  too and the compiler will force you to add the matching mascot formatter
 *  (and vice versa). That prevents the two display systems from drifting. */
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

const REGISTRY: Record<SupportedActionName, ActionRenderer> = {
  // file ops
  stream_edit: StreamEditRenderer,
  read_file: ReadFileRenderer,
  find_files: FindFilesRenderer,
  list_folder: ListFolderRenderer,
  convert_to_pdf: ConvertToPdfRenderer,
  convert_from_pdf: ConvertToPdfRenderer,
  read_pdf: ReadPdfRenderer,
  convert_to_markdown: ConvertToMarkdownRenderer,
  // code execution
  run_python: RunPythonRenderer,
  run_shell: RunShellRenderer,
  // web
  web_search: WebSearchRenderer,
  web_fetch: WebFetchRenderer,
  http_request: HttpRequestRenderer,
  // media
  generate_image: GenerateImageRenderer,
  describe_image: DescribeImageRenderer,
  perform_ocr: PerformOcrRenderer,
  understand_video: UnderstandVideoRenderer,
  // search
  grep_files: GrepFilesRenderer,
  memory_search: MemorySearchRenderer,
  // messaging
  send_message: SendMessageRenderer,
  send_message_with_attachment: SendMessageWithAttachmentRenderer,
  // todos
  update_todos: UpdateTodosRenderer,
}

/** Look up a renderer by action name. Name comparison is loose — names
 *  may arrive as snake_case (canonical) or with spaces/dashes from skill
 *  metadata, so we normalize first. Returns null for unknown names. */
export function getActionRenderer(name: string | undefined): ActionRenderer | null {
  if (!name) return null
  const normalized = normalizeActionName(name)
  return isSupportedActionName(normalized) ? REGISTRY[normalized] : null
}

// Convenience: parse both input and output as dicts. Returned null on parse
// failure so callers can fall back to the generic ContentDisplay.
export function parseIO(item: ActionItem) {
  return {
    inputObj: parseDict(item.input),
    outputObj: parseDict(item.output),
  }
}
