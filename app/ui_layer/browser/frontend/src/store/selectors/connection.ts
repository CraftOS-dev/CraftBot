import type { RootState } from '../index'

export const selectConnected = (state: RootState): boolean => state.connection.connected
export const selectVersion = (state: RootState): string => state.connection.version
export const selectReconnectAttempt = (state: RootState): number => state.connection.reconnectAttempt
