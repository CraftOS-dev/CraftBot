import type { LucideIcon } from 'lucide-react'
import {
  Box, LayoutDashboard, SquareKanban, ListTodo, Calendar, Clock, Newspaper,
  BookOpen, BarChart3, PieChart, Wallet, ShoppingCart, Package, Users,
  MessageSquare, Mail, Music, Camera, Gamepad2, Utensils, Dumbbell, Plane,
  Home, Star, Heart, Zap, Globe, Briefcase,
} from 'lucide-react'

/**
 * Curated icon set for Living UI projects. The project's `icon` field is
 * either "lucide:<Name>" (picked from this set) or "file:<relpath>"
 * (uploaded, served by GET /api/living-ui/icon/<projectId>). Anything else
 * (or nothing) falls back to the classic cube.
 */
export const LIVING_UI_ICONS: Record<string, LucideIcon> = {
  LayoutDashboard, SquareKanban, ListTodo, Calendar, Clock, Newspaper,
  BookOpen, BarChart3, PieChart, Wallet, ShoppingCart, Package, Users,
  MessageSquare, Mail, Music, Camera, Gamepad2, Utensils, Dumbbell, Plane,
  Home, Star, Heart, Zap, Globe, Briefcase,
}

interface LivingUIIconProps {
  icon?: string | null
  projectId: string
  size?: number
  className?: string
}

export function LivingUIIcon({ icon, projectId, size = 13, className }: LivingUIIconProps) {
  if (icon?.startsWith('lucide:')) {
    const Cmp = LIVING_UI_ICONS[icon.slice(7)]
    if (Cmp) return <Cmp size={size} className={className} />
  }
  if (icon?.startsWith('file:')) {
    return (
      <img
        src={`/api/living-ui/icon/${projectId}`}
        alt=""
        width={size}
        height={size}
        className={className}
        style={{ objectFit: 'contain', borderRadius: 2 }}
      />
    )
  }
  return <Box size={size} className={className} />
}
