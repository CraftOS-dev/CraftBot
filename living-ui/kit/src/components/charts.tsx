/**
 * Tiny dependency-free charts — visualize aggregates without a chart library.
 *
 *   <Sparkline values={[3, 5, 4, 8, 7, 11]} />
 *   <MiniBarChart data={[{ label: 'todo', value: 4 }, { label: 'done', value: 9 }]} />
 *
 * Colors default to the accent token; pass any CSS color to vary dashboards.
 */
import { cn } from '../lib/cn.ts';

export interface SparklineProps {
  values: number[];
  width?: number | undefined;
  height?: number | undefined;
  color?: string | undefined;
  className?: string | undefined;
}

export function Sparkline({
  values,
  width = 120,
  height = 32,
  color = 'var(--lui-accent)',
  className,
}: SparklineProps): React.JSX.Element | null {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  const pad = 2;
  const points = values
    .map((v, i) => {
      const x = i * step;
      const y = pad + (1 - (v - min) / span) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn('block h-auto max-w-full overflow-visible', className)}
      aria-hidden
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
  );
}

export interface MiniBarChartDatum {
  label: string;
  value: number;
  /** Per-bar color override. */
  color?: string | undefined;
}

export interface MiniBarChartProps {
  data: ReadonlyArray<MiniBarChartDatum>;
  /** Chart height in px, excluding labels (default 96). */
  height?: number | undefined;
  color?: string | undefined;
  className?: string | undefined;
}

export function MiniBarChart({
  data,
  height = 96,
  color = 'var(--lui-accent)',
  className,
}: MiniBarChartProps): React.JSX.Element | null {
  if (data.length === 0) return null;
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className={cn('flex items-end gap-2', className)}>
      {data.map((d) => (
        <div
          key={d.label}
          title={`${d.label}: ${d.value}`}
          className="flex min-w-0 flex-1 flex-col items-center gap-1"
        >
          <span className="text-xs text-[var(--lui-muted)]">{d.value}</span>
          <div
            className="w-full rounded-t-[var(--lui-radius)] transition-all"
            style={{
              height: Math.max(2, (d.value / max) * height),
              backgroundColor: d.color ?? color,
            }}
          />
          <span className="max-w-full truncate text-xs text-[var(--lui-muted)]">{d.label}</span>
        </div>
      ))}
    </div>
  );
}
