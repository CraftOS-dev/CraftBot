import React from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  MessageSquare,
  ListTodo,
  LayoutDashboard,
  Monitor,
  FolderOpen,
  Settings
} from 'lucide-react'
import styles from './NavBar.module.css'

interface NavItem {
  id: string
  label: string
  icon: React.ReactNode
  path: string
}

const navItems: NavItem[] = [
  { id: 'chat', label: 'Chat', icon: <MessageSquare size={16} />, path: '/' },
  { id: 'tasks', label: 'Tasks', icon: <ListTodo size={16} />, path: '/tasks' },
  { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={16} />, path: '/dashboard' },
  // { id: 'screen', label: 'Screen', icon: <Monitor size={16} />, path: '/screen' },
  { id: 'workspace', label: 'Workspace', icon: <FolderOpen size={16} />, path: '/workspace' },
  { id: 'settings', label: 'Settings', icon: <Settings size={16} />, path: '/settings' },
]

export function NavBar() {
  const location = useLocation()
  const navigate = useNavigate()

  const isActive = (path: string) => {
    if (path === '/') {
      return location.pathname === '/'
    }
    return location.pathname.startsWith(path)
  }

  return (
    <nav className={styles.navBar}>
      <div className={styles.navItems}>
        {navItems.map(item => (
          <button
            key={item.id}
            className={`${styles.navItem} ${isActive(item.path) ? styles.active : ''}`}
            onClick={() => navigate(item.path)}
          >
            <span className={styles.icon}>{item.icon}</span>
            <span className={styles.label}>{item.label}</span>
          </button>
        ))}
      </div>
    </nav>
  )
}
