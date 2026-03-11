import React, { useMemo, useState } from 'react'
import { Code2, GitCommit, FilePlus, FileEdit, FileMinus, ChevronDown, ChevronRight } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useDynamicTabs } from '../../hooks/useDynamicTabs'
import { CodeTabData } from '../../types/dynamicTabs'
import { MarkdownContent } from '../ui'
import styles from './DynamicTab.module.css'

interface CodeTabProps {
  tabId: string
}

// ─── Diff Parser ─────────────────────────────────────────────────────

interface ParsedFile {
  path: string
  status: 'added' | 'deleted' | 'modified' | 'renamed'
  oldPath?: string
  hunks: ParsedHunk[]
  additions: number
  deletions: number
}

interface ParsedHunk {
  header: string
  lines: DiffLine[]
}

interface DiffLine {
  type: 'add' | 'delete' | 'context' | 'header'
  content: string
  oldNum?: number
  newNum?: number
}

function parseUnifiedDiff(raw: string): ParsedFile[] {
  const files: ParsedFile[] = []
  const lines = raw.split('\n')
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Look for diff --git header
    if (!line.startsWith('diff --git ')) {
      i++
      continue
    }

    // Extract file path from diff --git a/path b/path
    const match = line.match(/^diff --git a\/(.+?) b\/(.+)$/)
    const oldPath = match?.[1] ?? ''
    const newPath = match?.[2] ?? ''
    i++

    // Detect file status from the following lines
    let status: ParsedFile['status'] = 'modified'
    // Skip mode lines, index lines, similarity lines
    while (i < lines.length && !lines[i].startsWith('--- ') && !lines[i].startsWith('diff --git ') && !lines[i].startsWith('@@')) {
      if (lines[i].startsWith('new file')) status = 'added'
      else if (lines[i].startsWith('deleted file')) status = 'deleted'
      else if (lines[i].startsWith('rename from') || lines[i].startsWith('similarity index')) status = 'renamed'
      i++
    }

    // Skip --- and +++ lines
    if (i < lines.length && lines[i].startsWith('--- ')) i++
    if (i < lines.length && lines[i].startsWith('+++ ')) i++

    const hunks: ParsedHunk[] = []
    let additions = 0
    let deletions = 0

    // Parse hunks
    while (i < lines.length && !lines[i].startsWith('diff --git ')) {
      if (lines[i].startsWith('@@')) {
        const hunkHeader = lines[i]
        const hunkMatch = hunkHeader.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/)
        let oldNum = hunkMatch ? parseInt(hunkMatch[1]) : 1
        let newNum = hunkMatch ? parseInt(hunkMatch[2]) : 1
        i++

        const hunkLines: DiffLine[] = []

        while (i < lines.length && !lines[i].startsWith('@@') && !lines[i].startsWith('diff --git ')) {
          const l = lines[i]
          if (l.startsWith('+')) {
            hunkLines.push({ type: 'add', content: l.substring(1), newNum })
            newNum++
            additions++
          } else if (l.startsWith('-')) {
            hunkLines.push({ type: 'delete', content: l.substring(1), oldNum })
            oldNum++
            deletions++
          } else if (l.startsWith(' ') || l === '') {
            hunkLines.push({ type: 'context', content: l.substring(1), oldNum, newNum })
            oldNum++
            newNum++
          } else if (l.startsWith('\\')) {
            // "\ No newline at end of file" — skip
          } else {
            // Unknown line, treat as context
            hunkLines.push({ type: 'context', content: l, oldNum, newNum })
            oldNum++
            newNum++
          }
          i++
        }

        hunks.push({ header: hunkHeader, lines: hunkLines })
      } else {
        i++
      }
    }

    files.push({
      path: newPath,
      status,
      oldPath: status === 'renamed' ? oldPath : undefined,
      hunks,
      additions,
      deletions,
    })
  }

  return files
}

// ─── Sub-components ──────────────────────────────────────────────────

const FILE_STATUS_ICONS: Record<ParsedFile['status'], React.ReactNode> = {
  added: <FilePlus size={14} className={styles.statusAdded} />,
  modified: <FileEdit size={14} className={styles.statusModified} />,
  deleted: <FileMinus size={14} className={styles.statusDeleted} />,
  renamed: <FileEdit size={14} className={styles.statusModified} />,
}

function DiffFileBlock({ file, defaultExpanded }: { file: ParsedFile; defaultExpanded: boolean }) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  return (
    <div className={styles.diffBlock}>
      <button className={styles.diffHeader} onClick={() => setExpanded(!expanded)}>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {FILE_STATUS_ICONS[file.status]}
        <span className={styles.diffFilePath}>{file.path}</span>
        <span className={styles.diffStats}>
          {file.additions > 0 && <span className={styles.statusAdded}>+{file.additions}</span>}
          {file.deletions > 0 && <span className={styles.statusDeleted}>-{file.deletions}</span>}
        </span>
      </button>
      {expanded && (
        <div className={styles.diffBody}>
          {file.hunks.map((hunk, j) => (
            <div key={j}>
              <div className={styles.hunkHeader}>{hunk.header}</div>
              <table className={styles.diffTable}>
                <tbody>
                  {hunk.lines.map((line, k) => (
                    <tr key={k} className={styles[`diffLine${line.type.charAt(0).toUpperCase() + line.type.slice(1)}`]}>
                      <td className={styles.lineNum}>{line.type !== 'add' ? line.oldNum : ''}</td>
                      <td className={styles.lineNum}>{line.type !== 'delete' ? line.newNum : ''}</td>
                      <td className={styles.linePrefix}>
                        {line.type === 'add' ? '+' : line.type === 'delete' ? '-' : ' '}
                      </td>
                      <td className={styles.lineContent}>{line.content}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Main Component ──────────────────────────────────────────────────

export const CodeTab = React.memo(function CodeTab({ tabId }: CodeTabProps) {
  const { tabData, getTabById } = useDynamicTabs()
  const { actions } = useWebSocket()
  const tab = getTabById(tabId)
  const data = tabData[tabId] as CodeTabData | undefined

  const taskActions = tab?.taskId
    ? actions.filter(a => a.parentId === tab.taskId || a.id === tab.taskId)
    : []

  const parsedFiles = useMemo(() => {
    if (!data?.rawDiff) return []
    return parseUnifiedDiff(data.rawDiff)
  }, [data?.rawDiff])

  const totalStats = useMemo(() => {
    return parsedFiles.reduce(
      (acc, f) => ({ additions: acc.additions + f.additions, deletions: acc.deletions + f.deletions }),
      { additions: 0, deletions: 0 }
    )
  }, [parsedFiles])

  const hasData = data && (data.rawDiff || data.commits?.length || data.summary)

  if (!hasData) {
    return (
      <div className={styles.tabContainer}>
        {taskActions.length > 0 ? (
          <div className={styles.taskContent}>
            <div className={styles.taskHeader}>
              <Code2 size={20} />
              <h3>Code Changes</h3>
              {tab?.taskId && <span className={styles.taskBadge}>Task: {taskActions[0]?.name ?? tab.taskId}</span>}
            </div>
            <div className={styles.actionList}>
              {taskActions.map(action => (
                <div key={action.id} className={`${styles.actionItem} ${styles[action.status]}`}>
                  <span className={styles.actionStatus}>{action.status}</span>
                  <span className={styles.actionName}>{action.name}</span>
                  {action.output && (
                    <div className={styles.actionOutput}>
                      <MarkdownContent content={action.output} />
                    </div>
                  )}
                </div>
              ))}
            </div>
            <p className={styles.waitingText}>Waiting for code analysis data...</p>
          </div>
        ) : (
          <div className={styles.placeholder}>
            <Code2 size={48} strokeWidth={1.5} />
            <h2>Code Viewer</h2>
            <p>Code diffs and commit history will appear here when a code-related task runs.</p>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={styles.tabContainer}>
      <div className={styles.taskContent}>
        <div className={styles.taskHeader}>
          <Code2 size={20} />
          <h3>{tab?.label ?? 'Code Changes'}</h3>
        </div>

        {data.summary && (
          <div className={styles.summarySection}>
            <MarkdownContent content={data.summary} />
          </div>
        )}

        {parsedFiles.length > 0 && (
          <div className={styles.dataSection}>
            <div className={styles.diffSummaryBar}>
              <span>{parsedFiles.length} file{parsedFiles.length !== 1 ? 's' : ''} changed</span>
              {totalStats.additions > 0 && <span className={styles.statusAdded}>+{totalStats.additions}</span>}
              {totalStats.deletions > 0 && <span className={styles.statusDeleted}>-{totalStats.deletions}</span>}
            </div>
            {parsedFiles.map((file, i) => (
              <DiffFileBlock key={file.path + i} file={file} defaultExpanded={parsedFiles.length <= 8} />
            ))}
          </div>
        )}

        {data.commits && data.commits.length > 0 && (
          <div className={styles.dataSection}>
            <h4>Commits</h4>
            <div className={styles.commitList}>
              {data.commits.map((commit, i) => (
                <div key={i} className={styles.commitItem}>
                  <GitCommit size={14} />
                  <span className={styles.commitHash}>{commit.hash.substring(0, 7)}</span>
                  <span className={styles.commitMsg}>{commit.message}</span>
                  <span className={styles.commitAuthor}>{commit.author}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
})
