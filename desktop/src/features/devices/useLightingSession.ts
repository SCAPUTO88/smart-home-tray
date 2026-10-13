import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  DeviceController,
  DeviceId,
  DeviceViewState,
  LightingDevice,
  LightingPatch,
  OperationScenario,
} from './types'
import { OperationError } from './types'

function initialView(device: LightingDevice): DeviceViewState {
  const confirmed = { ...device.state, hsv: { ...device.state.hsv } }
  return { requested: null, preview: { ...confirmed, hsv: { ...confirmed.hsv } }, pendingOperationId: null, confirmed, error: null, status: 'idle' }
}

function previewWithPatch(state: DeviceViewState['preview'], patch: LightingPatch): DeviceViewState['preview'] {
  return { ...state, ...patch, hsv: patch.hsv ? { ...state.hsv, ...patch.hsv } : state.hsv, quality: 'pending' }
}

export function useLightingSession(controller: DeviceController) {
  const [devices, setDevices] = useState<LightingDevice[]>([])
  const [views, setViews] = useState<Record<DeviceId, DeviceViewState>>({})
  const [selectedDeviceId, setSelectedDeviceId] = useState<DeviceId | null>(null)
  const sequenceByDevice = useRef<Record<DeviceId, number>>({})

  useEffect(() => {
    let active = true
    void controller.list().then((catalog) => {
      if (!active) return
      setDevices(catalog)
      setViews(Object.fromEntries(catalog.map((device) => [device.deviceId, initialView(device)])))
      setSelectedDeviceId((current) => current ?? catalog[0]?.deviceId ?? null)
    })
    return () => { active = false }
  }, [controller])

  const issue = useCallback((deviceId: DeviceId, patch: LightingPatch, scenario: OperationScenario) => {
    const operationId = (sequenceByDevice.current[deviceId] ?? 0) + 1
    sequenceByDevice.current[deviceId] = operationId
    setViews((current) => {
      const view = current[deviceId]
      if (!view) return current
      return { ...current, [deviceId]: { ...view, requested: patch, preview: previewWithPatch(view.preview, patch), pendingOperationId: operationId, error: null, status: 'pending' } }
    })

    void controller.command(deviceId, patch, scenario).then((device) => {
      if (sequenceByDevice.current[deviceId] !== operationId) return
      setDevices((current) => current.map((item) => item.deviceId === deviceId ? device : item))
      setViews((current) => {
        const view = current[deviceId]
        if (!view || view.pendingOperationId !== operationId) return current
        const confirmed = { ...device.state, hsv: { ...device.state.hsv } }
        return { ...current, [deviceId]: { requested: patch, preview: { ...confirmed, hsv: { ...confirmed.hsv } }, pendingOperationId: null, confirmed, error: null, status: 'confirmed' } }
      })
    }).catch((error: unknown) => {
      if (sequenceByDevice.current[deviceId] !== operationId) return
      const code = error instanceof OperationError ? error.code : 'DEVICE_ERROR'
      const status = code === 'COMMAND_CANCELED' ? 'canceled' : code === 'DEVICE_OFFLINE' ? 'offline' : 'error'
      const message = status === 'canceled' ? null : status === 'offline' ? 'O dispositivo está offline' : 'Não foi possível atualizar'
      if (status === 'offline') {
        setDevices((current) => current.map((item) => item.deviceId === deviceId ? { ...item, connection: 'offline', state: { ...item.state, quality: 'offline' } } : item))
      }
      setViews((current) => {
        const view = current[deviceId]
        if (!view || view.pendingOperationId !== operationId) return current
        const confirmed = status === 'offline' ? { ...view.confirmed, quality: 'offline' as const } : view.confirmed
        const preview = status === 'offline' ? { ...view.preview, quality: 'offline' as const } : view.preview
        return { ...current, [deviceId]: { ...view, pendingOperationId: null, confirmed, preview, error: message, status } }
      })
    })
  }, [controller])

  const selectedDevice = devices.find((device) => device.deviceId === selectedDeviceId) ?? null
  const selectedView = selectedDeviceId ? views[selectedDeviceId] ?? null : null

  return { devices, selectedDevice, selectedView, selectedDeviceId, selectDevice: setSelectedDeviceId, issue }
}
