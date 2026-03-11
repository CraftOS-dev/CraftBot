import { useContext } from 'react'
import { useNavigate } from 'react-router-dom'
import { DynamicTabContext } from '../contexts/DynamicTabContext'
import { DynamicTabType } from '../types/dynamicTabs'

export function useDynamicTabs() {
  const context = useContext(DynamicTabContext)
  if (!context) {
    throw new Error('useDynamicTabs must be used within a DynamicTabProvider')
  }
  return context
}

/**
 * Hook that provides tab creation with automatic navigation.
 */
export function useCreateAndNavigateTab() {
  const { createTab } = useDynamicTabs()
  const navigate = useNavigate()

  return (type: DynamicTabType, label?: string) => {
    const tab = createTab(type, label)
    navigate(tab.path)
    return tab
  }
}
