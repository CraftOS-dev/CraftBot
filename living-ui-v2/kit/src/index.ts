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
export { Select } from './components/Select.tsx';
export type { SelectOption, SelectProps } from './components/Select.tsx';
export { Textarea } from './components/Textarea.tsx';
export type { TextareaProps } from './components/Textarea.tsx';
export { Switch } from './components/Switch.tsx';
export type { SwitchProps } from './components/Switch.tsx';
export { Spinner } from './components/Spinner.tsx';
export type { SpinnerProps } from './components/Spinner.tsx';

// Form input presets (kit 0.5.0)
export { NumberInput, DateInput, SearchInput, TagInput } from './components/forms.tsx';
export type {
  NumberInputProps,
  DateInputProps,
  SearchInputProps,
  TagInputProps,
} from './components/forms.tsx';

// Schema-aware CRUD presets (kit 0.5.0)
export { EntityForm, EntityTable } from './components/entity.tsx';
export type {
  EntityField,
  EntityFieldType,
  EntityFormProps,
  EntityColumn,
  EntityTableProps,
} from './components/entity.tsx';

// Overlays & actions (kit 0.5.0)
export { ConfirmDialog, useConfirm } from './components/confirm.tsx';
export type { ConfirmDialogProps } from './components/confirm.tsx';
export { DropdownMenu } from './components/menu.tsx';
export type { DropdownMenuProps, DropdownMenuItem } from './components/menu.tsx';
export { Drawer } from './components/drawer.tsx';
export type { DrawerProps } from './components/drawer.tsx';
export { Tooltip } from './components/tooltip.tsx';
export type { TooltipProps } from './components/tooltip.tsx';

// Data display & interaction (kit 0.5.0)
export { Sparkline, MiniBarChart } from './components/charts.tsx';
export type {
  SparklineProps,
  MiniBarChartProps,
  MiniBarChartDatum,
} from './components/charts.tsx';
export { SortableList, reorderAndSave } from './components/dnd.tsx';
export type { SortableListProps } from './components/dnd.tsx';
export { FileUpload, ImageInput } from './components/upload.tsx';
export type { FileUploadProps, ImageInputProps, UploadedFile } from './components/upload.tsx';

// Hooks
export { useDebounce, useHotkey } from './lib/hooks.ts';

// Utilities
export { cn } from './lib/cn.ts';
