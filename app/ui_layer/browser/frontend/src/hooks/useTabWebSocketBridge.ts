import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWebSocket } from '../contexts/WebSocketContext'
import { useDynamicTabs } from './useDynamicTabs'
import { useToast } from '../contexts/ToastContext'
import { DynamicTabType, TabData } from '../types/dynamicTabs'

interface TabCreateMessage {
  type: 'tab_create'
  data: {
    tabType: DynamicTabType
    taskId: string
    label?: string
    initialData?: TabData
  }
}

interface TabDataMessage {
  type: 'tab_data'
  data: {
    taskId: string
    tabData: Partial<TabData>
    replace?: boolean // true = replace all data, false = merge (default)
  }
}

/**
 * Bridge between WebSocket messages and the Dynamic Tab system.
 * Listens for tab_create and tab_data messages from the backend
 * and routes them to the appropriate tab.
 */
export function useTabWebSocketBridge() {
  const { onRawMessage } = useWebSocket()
  const { createTab, setTabData, mergeTabData, getTabByTaskId } = useDynamicTabs()
  const { showToast } = useToast()
  const navigate = useNavigate()

  useEffect(() => {
    const unsubscribe = onRawMessage((msg) => {
      if (msg.type === 'tab_create') {
        const { tabType, taskId, label, initialData } = (msg as unknown as TabCreateMessage).data
        // Don't create duplicate tabs for the same task
        const existing = getTabByTaskId(taskId)
        if (existing) return

        const tab = createTab(tabType, label, taskId)
        if (initialData) {
          setTabData(tab.id, initialData)
        }
        showToast('info', `"${tab.label}" tab opened for task`)
        navigate(tab.path)
      }

      if (msg.type === 'tab_data') {
        const { taskId, tabData, replace } = (msg as unknown as TabDataMessage).data
        const tab = getTabByTaskId(taskId)
        if (!tab) return

        if (replace) {
          setTabData(tab.id, tabData as TabData)
        } else {
          mergeTabData(tab.id, tabData)
        }
      }
    })

    return unsubscribe
  }, [onRawMessage, createTab, setTabData, mergeTabData, getTabByTaskId, showToast, navigate])
}
