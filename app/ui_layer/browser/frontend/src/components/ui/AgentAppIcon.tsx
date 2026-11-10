import type { LucideIcon } from 'lucide-react'
import {
  Box, LayoutDashboard, SquareKanban, ListTodo, Calendar, Clock, Newspaper,
  BookOpen, BarChart3, PieChart, Wallet, ShoppingCart, Package, Users,
  MessageSquare, Mail, Music, Camera, Gamepad2, Utensils, Dumbbell, Plane,
  Home, Star, Heart, Zap, Globe, Briefcase,
} from 'lucide-react'

/** Curated icons for the app wizard and marketplace cards. */
export const AGENT_APP_ICONS: Record<string, LucideIcon> = {
  LayoutDashboard, SquareKanban, ListTodo, Calendar, Clock, Newspaper,
  BookOpen, BarChart3, PieChart, Wallet, ShoppingCart, Package, Users,
  MessageSquare, Mail, Music, Camera, Gamepad2, Utensils, Dumbbell, Plane,
  Home, Star, Heart, Zap, Globe, Briefcase,
}

interface AgentAppIconProps {
  icon?: string | null
  size?: number
  className?: string
}

export function AgentAppIcon({ icon, size = 13, className }: AgentAppIconProps) {
  if (icon?.startsWith('lucide:')) {
    const Cmp = AGENT_APP_ICONS[icon.slice(7)]
    if (Cmp) return <Cmp size={size} className={className} />
  }
  return <Box size={size} className={className} />
}
