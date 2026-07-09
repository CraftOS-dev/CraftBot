/**
 * Tiny dependency-free charts (SYSTEM-MANAGED — do not edit)
 *
 * Visualize the engine's /_stats results without a chart library:
 *
 *   // GET /api/cards/_stats?groupBy=status  ->  [{group, value}, ...]
 *   <MiniBarChart data={stats.map(s => ({ label: s.group, value: s.value }))} />
 *
 *   // trend over a numeric series
 *   <Sparkline values={[3, 5, 4, 8, 7, 11]} />
 *
 * Pass semantic colors (var(--color-info), var(--color-success), …) to
 * vary dashboards instead of leaving everything the accent color.
 */

export interface SparklineProps {
  values: number[]
  width?: number
  height?: number
  color?: string
}

export function Sparkline({
  values,
  width = 120,
  height = 32,
  color = 'var(--color-info)',
}: SparklineProps) {
  if (values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = width / (values.length - 1)
  const pad = 2
  const points = values
    .map((v, i) => {
      const x = i * step
      const y = pad + (1 - (v - min) / span) * (height - pad * 2)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: 'block', overflow: 'visible', maxWidth: '100%', height: 'auto' }}
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export interface MiniBarChartDatum {
  label: string
  value: number
  /** Per-bar color override. */
  color?: string
}

export interface MiniBarChartProps {
  data: MiniBarChartDatum[]
  /** Chart height in px, excluding labels (default 96). */
  height?: number
  color?: string
}

export function MiniBarChart({
  data,
  height = 96,
  color = 'var(--color-info)',
}: MiniBarChartProps) {
  if (data.length === 0) return null
  const max = Math.max(...data.map(d => d.value), 1)
  return (
    <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'flex-end' }}>
      {data.map(d => (
        <div
          key={d.label}
          title={`${d.label}: ${d.value}`}
          style={{
            flex: 1,
            minWidth: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 'var(--space-1)',
          }}
        >
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-secondary)' }}>
            {d.value}
          </span>
          <div
            style={{
              width: '100%',
              height: Math.max(2, (d.value / max) * height),
              backgroundColor: d.color ?? color,
              borderRadius: 'var(--radius-sm) var(--radius-sm) 0 0',
              transition: 'height var(--transition-slow)',
            }}
          />
          <span
            style={{
              maxWidth: '100%',
              fontSize: 'var(--font-size-xs)',
              color: 'var(--text-muted)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {d.label}
          </span>
        </div>
      ))}
    </div>
  )
}
