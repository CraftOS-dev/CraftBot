import React from 'react'
import { Code2, TrendingUp, CalendarRange, LayoutPanelLeft } from 'lucide-react'

const TAB_ICONS: Record<string, React.ReactNode> = {
  Code2: <Code2 size={16} />,
  TrendingUp: <TrendingUp size={16} />,
  CalendarRange: <CalendarRange size={16} />,
  LayoutPanelLeft: <LayoutPanelLeft size={16} />,
}

export function getTabIcon(iconName: string): React.ReactNode {
  return TAB_ICONS[iconName] ?? <LayoutPanelLeft size={16} />
}
