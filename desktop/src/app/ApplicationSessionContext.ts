import { createContext, useContext } from 'react'
import type { DeviceController } from '../features/devices/types'
import type { useLightingSession } from '../features/devices/useLightingSession'
import type { RecoveryIntegration } from '../features/recovery/reconciliation'
import type { RecoveryPresentation } from '../features/recovery/recoveryPresentation'

export interface ReadyApplicationSession {
  status: 'ready'
  controller: DeviceController
  recovery?: RecoveryIntegration
  presentation?: RecoveryPresentation
  session: ReturnType<typeof useLightingSession>
}

export type ApplicationSessionState = ReadyApplicationSession | { status: 'loading' } | { status: 'error'; message: string }

export const ApplicationSessionContext = createContext<ApplicationSessionState | null>(null)

export function useApplicationSession(): ApplicationSessionState | null {
  return useContext(ApplicationSessionContext)
}
