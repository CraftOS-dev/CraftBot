/**
 * Living UI kit — PUBLIC API (spec K6).
 * Anything exported here is the contract (append-only within a major version).
 * Anything not exported is internal and may change without notice.
 */

// Shell & feedback
export { Shell } from './shell/Shell.tsx';
export { toast, Toaster } from './shell/toast.tsx';

// Data layer
export { getPbClient, setPbClient, PbClient } from './pb/client.ts';
export type { NormalizedPbError } from './pb/client.ts';
export { useCollection, useRecord } from './pb/hooks.ts';
export type { CollectionQuery, CollectionState, RecordState } from './pb/hooks.ts';

// Auth (multi-user mode)
export { useAuth } from './pb/auth.ts';
export type { AuthState } from './pb/auth.ts';
export { LoginGate } from './components/LoginGate.tsx';

// Theme
export { ThemeBridge } from './theme/bridge.ts';
export type { ThemeMode } from './theme/bridge.ts';

// Components (shadcn-conventional APIs as of kit 0.4.0)
export { Button } from './components/Button.tsx';
export type { ButtonProps } from './components/Button.tsx';
export { Input } from './components/Input.tsx';
export type { InputProps } from './components/Input.tsx';
export {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
  CardBody, // kit ≤0.3 alias of CardContent
} from './components/Card.tsx';
export type { CardHeaderProps } from './components/Card.tsx';
export { Badge } from './components/Badge.tsx';
export type { BadgeProps } from './components/Badge.tsx';
export { Progress } from './components/Progress.tsx';
export type { ProgressProps } from './components/Progress.tsx';
export { Tabs, TabsList, TabsTrigger, TabsContent } from './components/Tabs.tsx';
export type { TabsProps, TabsTriggerProps, TabsContentProps } from './components/Tabs.tsx';
export { Dialog } from './components/Dialog.tsx';
export type { DialogProps } from './components/Dialog.tsx';
export { Table } from './components/Table.tsx';
export type { Column, TableProps } from './components/Table.tsx';

// Utilities
export { cn } from './lib/cn.ts';
