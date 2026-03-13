import React, { ReactNode } from 'react'
import { TopBar } from './TopBar'
import { NavBar } from './NavBar'
import styles from './Layout.module.css'

interface LayoutProps {
  children: ReactNode
}

export function Layout({ children }: LayoutProps) {
  return (
    <div className={styles.layout}>
      <TopBar />
      <NavBar />
      <main className={styles.content}>
        {children}
      </main>
    </div>
  )
}
