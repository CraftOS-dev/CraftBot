import type { ReactNode } from 'react';
import { cn } from '../lib/cn.ts';

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  className?: string | undefined;
}

export interface TableProps<T> {
  columns: Array<Column<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  emptyMessage?: string | undefined;
  className?: string | undefined;
}

/** Typed data table with a built-in empty state (spec: empty states required). */
export function Table<T>({
  columns,
  rows,
  rowKey,
  emptyMessage = 'Nothing here yet.',
  className,
}: TableProps<T>): React.JSX.Element {
  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center gap-1 px-6 py-10 text-center">
        <p className="text-sm text-[var(--lui-muted)]">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className={cn('w-full overflow-x-auto', className)}>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-[var(--lui-border)] text-left">
            {columns.map((col) => (
              <th key={col.key} className={cn('px-4 py-2.5 font-medium text-[var(--lui-muted)]', col.className)}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className="border-b border-[var(--lui-border)] last:border-0 hover:bg-[var(--lui-border)]/20"
            >
              {columns.map((col) => (
                <td key={col.key} className={cn('px-4 py-2.5', col.className)}>
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
