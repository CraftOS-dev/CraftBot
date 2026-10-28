import { describe, expect, it } from 'vitest'
import { bars, compactNumber, meter, sparkline } from '../../src/ui/charts'
import { width } from '../../src/text/width'
import { fitRow, joinColumns, rowText, seg, stackSections } from '../../src/screens/dataRows'
import { hourAxis, percent, recordTokens, splitTokens, startSeries, stepPeriod, uptimeParts } from '../../src/screens/dataDashboard'
import {
  adjacency,
  buildFileTree,
  countKinds,
  flattenFileTree,
  itemOfNode,
  matchesQuery,
  neighbourTree,
  sortNodes,
  withoutCoreFiles,
} from '../../src/screens/dataMemory'
import { formatSize, joinPath, parentPath, previewLines, renameCaret, resolveLocalPath, sanitizeText, uniqueName } from '../../src/screens/dataFiles'
import type { MemoryGraph, MemoryGraphNode, MemoryItem } from '../../../browser/frontend/src/store/slices/memorySettingsSlice'

describe('charts.sparkline', () => {
  it('draws one cell per value on a scale from zero', () => {
    expect(sparkline([0, 4, 8], 10)).toBe('▁▅█')
    expect(sparkline([5, 5, 5], 10)).toBe('███')
  })

  it('keeps zero distinct from a small value', () => {
    const line = sparkline([0, 1, 1000], 10)
    expect(line[0]).toBe('▁')
    expect(line[1]).toBe('▂')
  })

  it('shows the newest values when there are more than the width', () => {
    expect(sparkline([9, 9, 9, 0, 0], 2)).toBe('▁▁')
  })

  it('treats bad values as zero and honours a shared max', () => {
    expect(sparkline([Number.NaN, -3, 2], 5, { max: 8 })).toBe('▁▁▃')
    expect(sparkline([], 5)).toBe('')
    expect(sparkline([1], 0)).toBe('')
  })

  it('falls back to ASCII marks', () => {
    expect(sparkline([0, 8], 2, { ascii: true })).toBe('_#')
  })
})

describe('charts.bars', () => {
  it('returns height rows of exactly width cells', () => {
    const rows = bars([1, 2, 3, 4], 8, 3)
    expect(rows).toHaveLength(3)
    for (const row of rows) expect(width(row)).toBe(8)
  })

  it('fills the tallest bar to the top and leaves zeros empty', () => {
    const rows = bars([0, 4], 2, 2)
    expect(rows[0]).toBe(' █')
    expect(rows[1]).toBe(' █')
  })

  it('uses eighth blocks for the top cell and shows any value above zero', () => {
    const rows = bars([1, 16], 2, 2)
    expect(rows[1][0]).toBe('▁')
    expect(rows[0][0]).toBe(' ')
  })

  it('sums adjacent values when there are more values than cells', () => {
    const rows = bars([1, 1, 0, 0], 2, 1)
    expect(rows[0]).toBe('█ ')
  })

  it('puts a gap between wide columns', () => {
    const [row] = bars([1, 1], 6, 1)
    expect(row).toBe('██ ██ ')
  })

  it('handles empty input', () => {
    expect(bars([], 4, 2)).toEqual(['    ', '    '])
    expect(bars([1], 0, 2)).toEqual([])
  })
})

describe('charts.meter', () => {
  it('fills a share of the width', () => {
    expect(meter(0.5, 10)).toBe('█████░░░░░')
    expect(meter(0, 4)).toBe('░░░░')
    expect(meter(1, 4)).toBe('████')
  })

  it('never hides a tiny value or rounds almost full to full', () => {
    expect(meter(0.01, 10)).toBe('█░░░░░░░░░')
    expect(meter(0.99, 10)).toBe('█████████░')
  })

  it('clamps and survives bad input', () => {
    expect(meter(3, 3)).toBe('███')
    expect(meter(Number.NaN, 3)).toBe('░░░')
    expect(meter(0.5, 0)).toBe('')
    expect(meter(0.5, 4, { ascii: true })).toBe('##..')
  })
})

describe('charts.compactNumber', () => {
  it('abbreviates large counts', () => {
    expect(compactNumber(999)).toBe('999')
    expect(compactNumber(1532)).toBe('1.5k')
    expect(compactNumber(12_400)).toBe('12.4k')
    expect(compactNumber(250_000)).toBe('250k')
    expect(compactNumber(1_532_532)).toBe('1.5M')
    expect(compactNumber(999_960)).toBe('1M')
    expect(compactNumber(2_100_000_000)).toBe('2.1B')
    expect(compactNumber(-1500)).toBe('-1.5k')
    expect(compactNumber(Number.NaN)).toBe('0')
  })
})

describe('dataRows', () => {
  it('fits a row to an exact width', () => {
    const row = fitRow([seg('hello '), seg('world')], 8)
    expect(width(rowText(row))).toBe(8)
    expect(rowText(fitRow([seg('ab')], 5))).toBe('ab   ')
  })

  it('measures wide characters in cells', () => {
    const row = fitRow([seg('日本語テキスト')], 7)
    expect(width(rowText(row))).toBe(7)
  })

  it('lays two columns side by side', () => {
    const rows = joinColumns([[seg('a')], [seg('b')]], [[seg('x')]], 3, 2, 3)
    expect(rows.map(rowText)).toEqual(['a    x  ', 'b       '])
  })

  it('stacks sections with a blank row between them', () => {
    const rows = stackSections([[[seg('one')]], [[seg('two')]]])
    expect(rows.map(rowText)).toEqual(['one', '', 'two'])
  })
})

describe('dataDashboard', () => {
  it('cycles through the periods', () => {
    expect(stepPeriod('total', 1)).toBe('1h')
    expect(stepPeriod('1h', -1)).toBe('total')
    expect(stepPeriod('1d', 1)).toBe('1w')
  })

  it('splits tokens like the browser widget', () => {
    const split = splitTokens({ input: 100, output: 20, cached: 60, total: 120 })
    expect(split).toEqual({ input: 40, output: 20, cached: 60, base: 120, total: 60 })
    expect(percent(split.cached, split.base)).toBe(50)
    expect(percent(1, 0)).toBe(0)
  })

  it('breaks uptime into parts', () => {
    expect(uptimeParts(90061)).toEqual({ days: 1, hours: 1, minutes: 1 })
    expect(uptimeParts(-5)).toEqual({ days: 0, hours: 0, minutes: 0 })
  })

  it('buckets the growth of cumulative token totals', () => {
    let s = startSeries(10_000, 100_000)
    s = recordTokens(s, 500, 101_000, 10)
    expect(s.buckets).toEqual([0])
    s = recordTokens(s, 800, 103_000, 10)
    expect(s.buckets).toEqual([300])
    s = recordTokens(s, 900, 125_000, 10)
    expect(s.buckets).toEqual([300, 0, 100])
    // A restarted backend starts a new baseline.
    s = recordTokens(s, 50, 126_000, 10)
    expect(s.buckets).toEqual([300, 0, 100])
    expect(s.lastTotal).toBe(50)
  })

  it('keeps at most maxBuckets', () => {
    let s = startSeries(1000, 0)
    s = recordTokens(s, 0, 0, 3)
    s = recordTokens(s, 10, 5500, 3)
    expect(s.buckets).toEqual([0, 0, 10])
    expect(s.start).toBe(3000)
  })

  it('labels the hours under the bars', () => {
    expect(hourAxis(24)).toBe('0     6     12    18    ')
    expect(hourAxis(48).startsWith('0           6')).toBe(true)
    expect(width(hourAxis(30))).toBe(30)
  })
})

const node = (n: Partial<MemoryGraphNode> & { id: string }): MemoryGraphNode => ({
  kind: 'item',
  label: n.id,
  community: 0,
  ...n,
})

const graph: MemoryGraph = {
  nodes: [
    node({ id: 'i:1', label: 'likes tea', category: 'preference', timestamp: '2026-10-01', source: 'memory' }),
    node({ id: 'i:2', label: 'met Bob', category: 'event', timestamp: '2026-10-05', source: 'memory' }),
    node({ id: 'e:bob', kind: 'entity', label: 'Bob', size: 2 }),
    node({ id: 'e:tea', kind: 'entity', label: 'Tea', size: 1 }),
    node({ id: 'f:AGENT.md', kind: 'file', label: 'AGENT.md', size: 1 }),
    node({ id: 'c:1', label: 'section text', source: 'file', file: 'AGENT.md', section: 'Intro' }),
  ],
  edges: [
    { source: 'i:2', target: 'e:bob', status: 'confirmed' },
    { source: 'i:1', target: 'e:tea', status: 'pending' },
    { source: 'i:1', target: 'e:bob', status: 'confirmed' },
    { source: 'f:AGENT.md', target: 'c:1' },
  ],
  stats: {},
}

describe('dataMemory', () => {
  it('orders memories newest first, then entities, files and sections', () => {
    expect(sortNodes(graph.nodes).map(n => n.id)).toEqual(['i:2', 'i:1', 'e:bob', 'e:tea', 'f:AGENT.md', 'c:1'])
  })

  it('hides default files and their sections but keeps MEMORY.md', () => {
    const files = [
      { path: 'AGENT.md', core: true, exists: true, chunk_count: 1, indexed_at: '' },
      { path: 'MEMORY.md', core: true, exists: true, chunk_count: 1, indexed_at: '' },
    ]
    const shown = withoutCoreFiles(graph, files, true)
    expect(shown?.nodes.map(n => n.id)).not.toContain('f:AGENT.md')
    expect(shown?.nodes.map(n => n.id)).not.toContain('c:1')
    expect(shown?.edges).toHaveLength(3)
    expect(withoutCoreFiles(graph, files, false)).toBe(graph)
    expect(countKinds(shown)).toEqual({ memories: 2, entities: 2, files: 0 })
  })

  it('searches text, category, sections and linked names', () => {
    const item: MemoryItem = { id: '1', timestamp: '', category: 'preference', content: 'likes tea', entities: ['Tea Shop'], raw: '' }
    expect(matchesQuery(graph.nodes[0], 'shop', item)).toBe(true)
    expect(matchesQuery(graph.nodes[0], 'PREFER', null)).toBe(true)
    expect(matchesQuery(graph.nodes[5], 'intro', null)).toBe(true)
    expect(matchesQuery(graph.nodes[0], 'coffee', item)).toBe(false)
    expect(itemOfNode(graph.nodes[0], [item])).toBe(item)
    expect(itemOfNode(graph.nodes[5], [item])).toBeNull()
  })

  it('builds the neighbour tree without walking back up its path', () => {
    const adj = adjacency(graph)
    const byId = new Map(graph.nodes.map(n => [n.id, n]))
    const closed = neighbourTree('e:bob', adj, byId, new Set())
    expect(closed.map(r => r.id)).toEqual(['i:2', 'i:1'])
    expect(closed[1].childCount).toBe(1)
    expect(closed[1].prefix).toBe('└ ')
    const open = neighbourTree('e:bob', adj, byId, new Set(['e:bob>i:1']))
    expect(open.map(r => `${r.prefix}${r.id}`)).toEqual(['├ i:2', '└ i:1', '  └ e:tea'])
    const limited = neighbourTree('e:bob', adj, byId, new Set(), 1)
    expect(limited.map(r => r.id ?? `+${r.more}`)).toEqual(['i:2', '+1'])
  })

  it('merges indexed files and candidates into a folder tree', () => {
    const root = buildFileTree(
      [{ path: 'AGENT.md', core: true, exists: true, chunk_count: 3, indexed_at: '' }],
      [{ path: 'workspace/notes/a.md', size: 2048 }, { path: 'workspace/b.md', size: 10 }],
    )
    const closed = flattenFileTree(root, new Set())
    expect(closed.map(r => (r.type === 'folder' ? `${r.name}/ ${r.indexed}/${r.total}` : r.file.name))).toEqual(['workspace/ 0/2', 'AGENT.md'])
    const open = flattenFileTree(root, new Set(['workspace', 'workspace/notes']))
    expect(open.map(r => (r.type === 'folder' ? `${r.depth}:${r.name}/` : `${r.depth}:${r.file.name}`))).toEqual([
      '0:workspace/',
      '1:notes/',
      '2:a.md',
      '1:b.md',
      '0:AGENT.md',
    ])
  })
})

describe('dataFiles', () => {
  it('names pasted copies like the browser', () => {
    const names = new Set(['a.txt', 'a_copy.txt', 'notes'])
    expect(uniqueName('b.txt', names)).toBe('b.txt')
    expect(uniqueName('a.txt', names)).toBe('a_copy2.txt')
    expect(uniqueName('notes', names)).toBe('notes_copy')
    expect(uniqueName('.env', new Set(['.env']))).toBe('.env_copy')
  })

  it('handles workspace paths', () => {
    expect(parentPath('a/b/c.txt')).toBe('a/b')
    expect(parentPath('c.txt')).toBe('')
    expect(parentPath('a\\b')).toBe('a')
    expect(joinPath('', 'x')).toBe('x')
    expect(joinPath('a', 'x')).toBe('a/x')
  })

  it('puts the rename caret before the extension', () => {
    expect(renameCaret('report.final.md')).toBe(12)
    expect(renameCaret('Makefile')).toBe(8)
    expect(renameCaret('.gitignore')).toBe(10)
  })

  it('formats sizes', () => {
    expect(formatSize(512)).toBe('512 B')
    expect(formatSize(1536)).toBe('1.5 KB')
    expect(formatSize(5 * 1024 * 1024)).toBe('5.0 MB')
    expect(formatSize(undefined)).toBe('-')
  })

  it('resolves typed and dropped local paths', () => {
    const cwd = process.platform === 'win32' ? 'C:\\work' : '/work'
    const home = process.platform === 'win32' ? 'C:\\Users\\me' : '/home/me'
    expect(resolveLocalPath('"notes.txt"', cwd, home)).toMatch(/work[\\/]notes\.txt$/)
    expect(resolveLocalPath('~/a.txt', cwd, home)).toMatch(/me[\\/]a\.txt$/)
    expect(resolveLocalPath('   ', cwd, home)).toBe('')
  })

  it('strips terminal escapes and control characters from previews', () => {
    expect(sanitizeText('a\u001b[31mred\u001b[0m\r\nb\u0007\tc')).toBe('ared\nb    c')
    expect(sanitizeText('x\u001b]0;title\u0007y')).toBe('xy')
    expect(previewLines('one\ntwo\n', 10)).toEqual(['one', 'two'])
    expect(previewLines('abcdefghij', 4)).toEqual(['abcd', 'efgh', 'ij'])
    const wrapped = previewLines('  indented words here', 10)
    expect(wrapped[0]).toBe('  indented')
    for (const line of wrapped.slice(1)) expect(line.startsWith(' ')).toBe(false)
    for (const line of wrapped) expect(width(line)).toBeLessThanOrEqual(10)
  })
})
