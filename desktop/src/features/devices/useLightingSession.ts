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

type LightingField = 'enabled' | 'mode' | 'whiteBrightness' | 'whiteTemperature' | `hsv.${'hue' | 'saturation' | 'value'}`
type PendingOperation = DeviceViewState['pendingOperations'][number]
type LatestByField = Partial<Record<LightingField, number>>
interface OperationOutcome { status: DeviceViewState['status']; error: string | null }
const allFields: LightingField[] = ['enabled', 'mode', 'whiteBrightness', 'whiteTemperature', 'hsv.hue', 'hsv.saturation', 'hsv.value']

function initialView(device: LightingDevice): DeviceViewState {
  const confirmed = { ...device.state, hsv: { ...device.state.hsv } }
  return { requested: null, preview: { ...confirmed, hsv: { ...confirmed.hsv } }, pendingOperations: [], confirmed, error: null, status: 'idle' }
}

function fieldsOf(patch: LightingPatch): LightingField[] {
  const fields: LightingField[] = []
  if (patch.enabled !== undefined) fields.push('enabled')
  if (patch.mode !== undefined) fields.push('mode')
  if (patch.whiteBrightness !== undefined) fields.push('whiteBrightness')
  if (patch.whiteTemperature !== undefined) fields.push('whiteTemperature')
  if (patch.hsv) {
    if (patch.hsv.hue !== undefined) fields.push('hsv.hue')
    if (patch.hsv.saturation !== undefined) fields.push('hsv.saturation')
    if (patch.hsv.value !== undefined) fields.push('hsv.value')
  }
  return fields
}

function fieldValue(patch: LightingPatch, field: LightingField): unknown {
  if (field.startsWith('hsv.')) return patch.hsv?.[field.slice(4) as 'hue' | 'saturation' | 'value']
  switch (field) {
    case 'enabled': return patch.enabled
    case 'mode': return patch.mode
    case 'whiteBrightness': return patch.whiteBrightness
    case 'whiteTemperature': return patch.whiteTemperature
  }
}

function setField(patch: LightingPatch, field: LightingField, value: unknown): LightingPatch {
  if (field.startsWith('hsv.')) {
    const channel = field.slice(4) as 'hue' | 'saturation' | 'value'
    return { ...patch, hsv: { ...patch.hsv, [channel]: value as number } }
  }
  return { ...patch, [field]: value }
}

function mergePatch(base: LightingPatch | null, update: LightingPatch): LightingPatch {
  let merged = { ...base } as LightingPatch
  for (const field of fieldsOf(update)) merged = setField(merged, field, fieldValue(update, field))
  return merged
}

function applyPatch(state: DeviceViewState['preview'], patch: LightingPatch, quality = state.quality): DeviceViewState['preview'] {
  return {
    ...state,
    ...patch,
    hsv: patch.hsv ? { ...state.hsv, ...patch.hsv } : state.hsv,
    quality,
  }
}

function activeOperations(operations: PendingOperation[], latest: LatestByField): PendingOperation[] {
  return operations.filter((operation) => fieldsOf(operation.patch).some((field) => latest[field] === operation.operationId))
}

function visiblePreview(confirmed: DeviceViewState['confirmed'], operations: PendingOperation[], latest: LatestByField) {
  let preview = { ...confirmed, hsv: { ...confirmed.hsv } }
  for (const operation of operations) {
    for (const field of fieldsOf(operation.patch)) {
      if (latest[field] === operation.operationId) {
        preview = applyPatch(preview, setField({}, field, fieldValue(operation.patch, field)), 'pending')
      }
    }
  }
  return preview
}

function mergeReadback(confirmed: DeviceViewState['confirmed'], response: LightingDevice, acceptedFields: LightingField[]) {
  let next = { ...confirmed, hsv: { ...confirmed.hsv } }
  for (const field of acceptedFields) next = applyPatch(next, setField({}, field, fieldValue({
    enabled: response.state.enabled,
    mode: response.state.mode,
    whiteBrightness: response.state.whiteBrightness,
    whiteTemperature: response.state.whiteTemperature,
    hsv: response.state.hsv,
  }, field)), response.state.quality)
  // Keep quality from the readback verbatim; a successful command cannot invent a known device state.
  return next
}

export function useLightingSession(controller: DeviceController) {
  const [devices, setDevices] = useState<LightingDevice[]>([])
  const [views, setViews] = useState<Record<DeviceId, DeviceViewState>>({})
  const [selectedDeviceId, setSelectedDeviceId] = useState<DeviceId | null>(null)
  const sequenceByDevice = useRef<Record<DeviceId, number>>({})
  const latestOperationByDevice = useRef<Record<DeviceId, number>>({})
  const latestByField = useRef<Record<DeviceId, LatestByField>>({})
  const latestOutcomeByDevice = useRef<Record<DeviceId, OperationOutcome>>({})

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
    latestOperationByDevice.current[deviceId] = operationId
    latestOutcomeByDevice.current[deviceId] = { status: 'pending', error: null }
    const latest = latestByField.current[deviceId] ?? {}
    for (const field of fieldsOf(patch)) latest[field] = operationId
    latestByField.current[deviceId] = latest
    const operation: PendingOperation = { operationId, patch }

    setViews((current) => {
      const view = current[deviceId]
      if (!view) return current
      const pendingOperations = [...view.pendingOperations, operation]
      const active = activeOperations(pendingOperations, latest)
      return { ...current, [deviceId]: {
        ...view,
        requested: mergePatch(view.requested, patch),
        preview: visiblePreview(view.confirmed, pendingOperations, latest),
        pendingOperations,
        error: null,
        status: active.length ? 'pending' : view.status,
      } }
    })

    let command: Promise<LightingDevice>
    try {
      command = controller.command(deviceId, patch, scenario)
    } catch (error) {
      command = Promise.reject(error)
    }
    void command.then((device) => {
      if (latestOperationByDevice.current[deviceId] === operationId) {
        latestOutcomeByDevice.current[deviceId] = { status: 'confirmed', error: null }
      }
      setDevices((current) => current.map((item) => {
        if (item.deviceId !== deviceId) return item
        const acceptedFields = fieldsOf(patch).filter((field) => latestByField.current[deviceId]?.[field] === operationId)
        if (!acceptedFields.length) return item
        const state = mergeReadback(initialView(item).confirmed, device, acceptedFields)
        return { ...item, connection: device.connection, state }
      }))
      setViews((current) => {
        const view = current[deviceId]
        if (!view) return current
        const pendingOperations = view.pendingOperations.filter((item) => item.operationId !== operationId)
        const acceptedFields = fieldsOf(patch).filter((field) => latestByField.current[deviceId]?.[field] === operationId)
        const confirmed = acceptedFields.length ? mergeReadback(view.confirmed, device, acceptedFields) : view.confirmed
        const active = activeOperations(pendingOperations, latestByField.current[deviceId] ?? {})
        const outcome = latestOutcomeByDevice.current[deviceId]
        const status = active.length ? 'pending' : outcome?.status ?? view.status
        return { ...current, [deviceId]: {
          ...view,
          confirmed,
          preview: visiblePreview(confirmed, pendingOperations, latestByField.current[deviceId] ?? {}),
          pendingOperations,
          error: outcome?.error ?? null,
          status,
        } }
      })
    }).catch((error: unknown) => {
      const code = error instanceof OperationError ? error.code : 'DEVICE_ERROR'
      const status = code === 'COMMAND_CANCELED' ? 'canceled' : code === 'DEVICE_OFFLINE' ? 'offline' : 'error'
      const isLatestOperation = latestOperationByDevice.current[deviceId] === operationId
      const message = status === 'canceled' ? 'Operação cancelada' : status === 'offline' ? 'O dispositivo está offline' : 'Não foi possível atualizar'

      if (isLatestOperation) {
        latestOutcomeByDevice.current[deviceId] = { status, error: message }
      }

      if (status === 'offline' && isLatestOperation) {
        const latest = latestByField.current[deviceId] ?? {}
        for (const field of allFields) latest[field] = operationId
        latestByField.current[deviceId] = latest
        setDevices((current) => latestOperationByDevice.current[deviceId] !== operationId
          ? current
          : current.map((item) => item.deviceId === deviceId
            ? { ...item, connection: 'offline', state: { ...item.state, quality: 'offline' } }
            : item))
      }

      setViews((current) => {
        const view = current[deviceId]
        if (!view) return current
        const isLatestNow = latestOperationByDevice.current[deviceId] === operationId
        const pendingOperations = status === 'offline' && isLatestNow
          ? []
          : view.pendingOperations.filter((item) => item.operationId !== operationId)
        const latest = latestByField.current[deviceId] ?? {}
        const active = activeOperations(pendingOperations, latest)
        const confirmed = status === 'offline' && isLatestNow
          ? { ...view.confirmed, quality: 'offline' as const }
          : view.confirmed
        const outcome = latestOutcomeByDevice.current[deviceId]
        const nextStatus = active.length ? 'pending' : outcome?.status ?? view.status
        return { ...current, [deviceId]: {
          ...view,
          confirmed,
          preview: visiblePreview(confirmed, pendingOperations, latest),
          pendingOperations,
          error: outcome?.error ?? null,
          status: nextStatus,
        } }
      })
    })
  }, [controller])

  const selectedDevice = devices.find((device) => device.deviceId === selectedDeviceId) ?? null
  const selectedView = selectedDeviceId ? views[selectedDeviceId] ?? null : null

  return { devices, selectedDevice, selectedView, selectedDeviceId, selectDevice: setSelectedDeviceId, issue }
}
