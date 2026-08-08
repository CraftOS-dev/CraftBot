import {
  createContext,
  useContext,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
} from 'react';
import { cn } from '../lib/cn.ts';

/**
 * Tabs — shadcn-conventional composition, no Radix dependency:
 *
 *   <Tabs defaultValue="plan">
 *     <TabsList>
 *       <TabsTrigger value="plan">Plan</TabsTrigger>
 *       <TabsTrigger value="tests">Tests</TabsTrigger>
 *     </TabsList>
 *     <TabsContent value="plan">…</TabsContent>
 *     <TabsContent value="tests">…</TabsContent>
 *   </Tabs>
 *
 * Controlled (`value` + `onValueChange`) or uncontrolled (`defaultValue`).
 */

interface TabsCtx {
  value: string;
  setValue: (v: string) => void;
}

const Ctx = createContext<TabsCtx | null>(null);

function useTabsCtx(component: string): TabsCtx {
  const ctx = useContext(Ctx);
  if (ctx === null) throw new Error(`<${component}> must be used inside <Tabs>`);
  return ctx;
}

export interface TabsProps extends HTMLAttributes<HTMLDivElement> {
  defaultValue?: string | undefined;
  value?: string | undefined;
  onValueChange?: ((value: string) => void) | undefined;
}

export function Tabs({
  defaultValue,
  value,
  onValueChange,
  className,
  children,
  ...props
}: TabsProps): React.JSX.Element {
  const [inner, setInner] = useState(defaultValue ?? '');
  const current = value ?? inner;
  const setValue = (v: string): void => {
    if (value === undefined) setInner(v);
    onValueChange?.(v);
  };
  return (
    <div className={cn('flex flex-col gap-3', className)} {...props}>
      <Ctx.Provider value={{ value: current, setValue }}>{children}</Ctx.Provider>
    </div>
  );
}

export function TabsList({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return (
    <div
      role="tablist"
      className={cn(
        'inline-flex w-fit items-center gap-1 rounded-[var(--lui-radius)] bg-[var(--lui-border)]/40 p-1',
        className,
      )}
      {...props}
    />
  );
}

export interface TabsTriggerProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  value: string;
}

export function TabsTrigger({
  value,
  className,
  ...props
}: TabsTriggerProps): React.JSX.Element {
  const ctx = useTabsCtx('TabsTrigger');
  const active = ctx.value === value;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={() => ctx.setValue(value)}
      className={cn(
        'rounded-[calc(var(--lui-radius)-2px)] px-3 py-1.5 text-sm font-medium transition-colors',
        active
          ? 'bg-[var(--lui-surface)] text-[var(--lui-text)] shadow-sm'
          : 'text-[var(--lui-muted)] hover:text-[var(--lui-text)]',
        className,
      )}
      {...props}
    />
  );
}

export interface TabsContentProps extends HTMLAttributes<HTMLDivElement> {
  value: string;
}

export function TabsContent({
  value,
  className,
  children,
  ...props
}: TabsContentProps): React.JSX.Element | null {
  const ctx = useTabsCtx('TabsContent');
  if (ctx.value !== value) return null;
  return (
    <div role="tabpanel" className={cn(className)} {...props}>
      {children}
    </div>
  );
}
