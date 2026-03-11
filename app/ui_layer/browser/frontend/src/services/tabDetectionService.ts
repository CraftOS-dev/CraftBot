// Tab Utility Service
// Provides helper functions for dynamic tab ID/path/label generation

import { DynamicTabType, TAB_TYPE_CONFIG } from '../types/dynamicTabs'

/**
 * Generate a unique tab ID.
 */
export function generateTabId(type: DynamicTabType): string {
  return `${type}-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`
}

/**
 * Generate a URL path for a dynamic tab.
 */
export function generateTabPath(type: DynamicTabType, id: string): string {
  return `/dynamic/${type}/${id}`
}

/**
 * Get default label for a tab type.
 */
export function getDefaultTabLabel(type: DynamicTabType): string {
  return TAB_TYPE_CONFIG[type]?.defaultLabel ?? 'Tab'
}

/**
 * Get default icon name for a tab type.
 */
export function getDefaultTabIcon(type: DynamicTabType): string {
  return TAB_TYPE_CONFIG[type]?.defaultIcon ?? 'LayoutPanelLeft'
}
