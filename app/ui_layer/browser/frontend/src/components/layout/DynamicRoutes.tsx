import React, { lazy } from 'react'
import { Route } from 'react-router-dom'
import { DynamicTab, DynamicTabType } from '../../types/dynamicTabs'
import { DynamicTabLoader } from '../tabs/DynamicTabLoader'

const CodeTab = lazy(() => import('../tabs/CodeTab').then(m => ({ default: m.CodeTab })))
const StockTab = lazy(() => import('../tabs/StockTab').then(m => ({ default: m.StockTab })))
const PlannerTab = lazy(() => import('../tabs/PlannerTab').then(m => ({ default: m.PlannerTab })))
const CustomTab = lazy(() => import('../tabs/CustomTab').then(m => ({ default: m.CustomTab })))

const TAB_COMPONENTS: Record<DynamicTabType, React.LazyExoticComponent<React.ComponentType<{ tabId: string }>>> = {
  code: CodeTab,
  stock: StockTab,
  planner: PlannerTab,
  custom: CustomTab,
}

/**
 * Build Route elements for all active dynamic tabs + a fallback catch-all.
 * Returns an array of <Route> elements to spread inside <Routes>.
 */
export function buildDynamicRoutes(tabs: DynamicTab[]): React.ReactNode[] {
  const routes = tabs.map(tab => {
    const Component = TAB_COMPONENTS[tab.type] ?? CustomTab
    return <Route key={tab.id} path={tab.path} element={<Component tabId={tab.id} />} />
  })
  routes.push(
    <Route key="__dynamic_loader" path="/dynamic/:type/:id" element={<DynamicTabLoader />} />
  )
  return routes
}
