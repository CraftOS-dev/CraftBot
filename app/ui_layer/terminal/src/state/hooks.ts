import { useDispatch, useSelector, type TypedUseSelectorHook } from 'react-redux'
import { getSocketClient } from '../../../browser/frontend/src/store/socket/socketInstance'
import type { AppDispatch, RootState } from './store'

export const useAppDispatch: () => AppDispatch = useDispatch
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector

/** Send one message to the backend (`{type, ...fields}`), queued while offline. */
export function send(type: string, fields: Record<string, unknown> = {}): void {
  getSocketClient().send(type, fields)
}
