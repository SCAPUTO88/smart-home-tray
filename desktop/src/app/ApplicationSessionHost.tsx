import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { DeviceController } from '../features/devices/types'
import { useLightingSession } from '../features/devices/useLightingSession'
import { resolveDeviceIntegration, type DeviceIntegration } from '../features/devices/platformController'
import type { RecoveryIntegration } from '../features/recovery/reconciliation'
import { RecoveryPresentation } from '../features/recovery/recoveryPresentation'
import { sessionSourceId } from './sessionIdentity'
import { ApplicationSessionContext } from './ApplicationSessionContext'
import type { ApplicationSessionState, ReadyApplicationSession } from './ApplicationSessionContext'

interface ApplicationSessionHostProps {
  children: ReactNode
  controller?: DeviceController
  integration?: DeviceIntegration
  now?: () => number
}

export function ApplicationSessionHost({ children, controller: suppliedController, integration: suppliedIntegration, now }: ApplicationSessionHostProps) {
  const [resolvedIntegration, setResolvedIntegration] = useState<DeviceIntegration | null>(null)
  const [startupError, setStartupError] = useState(false)
  const resolution = useRef<Promise<DeviceIntegration> | null>(null)

  useEffect(() => {
    if (suppliedController || suppliedIntegration) return
    let active = true
    resolution.current ??= resolveDeviceIntegration()
    void resolution.current.then((integration) => {
      if (active) { setResolvedIntegration(integration); setStartupError(false) }
    }).catch(() => { if (active) setStartupError(true) })
    return () => { active = false }
  }, [suppliedController, suppliedIntegration])

  const activeSource = suppliedIntegration
    ? { identity: suppliedIntegration, controller: suppliedIntegration.lighting, recovery: suppliedIntegration.recovery }
    : suppliedController
      ? { identity: suppliedController, controller: suppliedController }
      : resolvedIntegration
        ? { identity: resolvedIntegration, controller: resolvedIntegration.lighting, recovery: resolvedIntegration.recovery }
        : null
  const state: ApplicationSessionState = !activeSource
    ? startupError ? { status: 'error', message: 'Não foi possível iniciar a integração selecionada' } : { status: 'loading' }
    : { status: 'loading' }

  return activeSource
    ? <ActiveApplicationSession key={sessionSourceId(activeSource.identity)} controller={activeSource.controller} recovery={activeSource.recovery} now={now}>{children}</ActiveApplicationSession>
    : <ApplicationSessionContext.Provider value={state}>{children}</ApplicationSessionContext.Provider>
}

function ActiveApplicationSession({ children, controller, recovery, now }: {
  children: ReactNode
  controller: DeviceController
  recovery?: RecoveryIntegration
  now?: () => number
}) {
  const session = useLightingSession(controller, recovery)
  const [presentation] = useState(() => recovery ? new RecoveryPresentation(now) : undefined)
  const value: ReadyApplicationSession = { status: 'ready', controller, recovery, presentation, session }
  return <ApplicationSessionContext.Provider value={value}>{children}</ApplicationSessionContext.Provider>
}
