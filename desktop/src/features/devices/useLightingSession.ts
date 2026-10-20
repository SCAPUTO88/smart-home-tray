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
import type { RecoveryIntegration } from '../recovery/reconciliation'
import type { PrepareOutcome, ConfirmOutcome } from '../recovery/ManualRecoveryController'
import { parseBridgeError } from './publicDeviceMapper'

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
  const knowledge = { ...confirmed.knowledge }
  for (const field of acceptedFields) next = applyPatch(next, setField({}, field, fieldValue({
    enabled: response.state.enabled,
    mode: response.state.mode,
    whiteBrightness: response.state.whiteBrightness,
    whiteTemperature: response.state.whiteTemperature,
    hsv: response.state.hsv,
  }, field)), response.state.quality)
  for (const field of acceptedFields) {
    switch (field) {
      case 'enabled': knowledge.power = response.state.knowledge.power; break
      case 'mode': knowledge.workMode = response.state.knowledge.workMode; break
      case 'whiteBrightness': knowledge.whiteBrightness = response.state.knowledge.whiteBrightness; break
      case 'whiteTemperature': knowledge.colorTemperature = response.state.knowledge.colorTemperature; break
      default:
        knowledge.hsv = response.state.knowledge.hsv
        knowledge.colorValue = response.state.knowledge.colorValue
    }
  }
  // Keep quality from the readback verbatim; a successful command cannot invent a known device state.
  return { ...next, knowledge }
}

export function useLightingSession(controller: DeviceController, recovery?: RecoveryIntegration) {
  const [devices, setDevices] = useState<LightingDevice[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [views, setViews] = useState<Record<DeviceId, DeviceViewState>>({})
  const [selectedDeviceId, setSelectedDeviceId] = useState<DeviceId | null>(null)
  const sequenceByDevice = useRef<Record<DeviceId, number>>({})
  const latestOperationByDevice = useRef<Record<DeviceId, number>>({})
  const latestByField = useRef<Record<DeviceId, LatestByField>>({})
  const latestOutcomeByDevice = useRef<Record<DeviceId, OperationOutcome>>({})
  const refreshSequence = useRef<Record<DeviceId, number>>({})
  const activeRefresh = useRef<Record<DeviceId, boolean>>({})
  const mounted = useRef(true)
  const lifetime = useRef(0)
  const appliedRevision = useRef<Record<DeviceId, number>>({})
  const recoverySequence = useRef<Record<DeviceId, number>>({})
  const recoveryCommandFloor = useRef<Record<DeviceId, number>>({})
  const recoveryRefreshFloor = useRef<Record<DeviceId, number>>({})
  const proposals = useRef(new Map<string, DeviceId>())
  const [refreshing, setRefreshing] = useState<Record<DeviceId, boolean>>({})
  const [refreshErrors, setRefreshErrors] = useState<Record<DeviceId, string | null>>({})

  useEffect(() => {
    let active = true
    const sessionProposals = proposals.current
    mounted.current = true
    lifetime.current += 1
    activeRefresh.current = {}
    void controller.list().then((catalog) => {
      if (!active) return
      setLoadError(null)
      setDevices(catalog)
      setViews(Object.fromEntries(catalog.map((device) => [device.deviceId, initialView(device)])))
      setSelectedDeviceId((current) => current ?? catalog[0]?.deviceId ?? null)
    }).catch(() => { if (active) setLoadError("Não foi possível carregar os dispositivos") })
    return () => { active = false; mounted.current = false; lifetime.current += 1; sessionProposals.clear() }
  }, [controller, recovery?.controller, recovery?.reconciliation])

  const issue = useCallback((deviceId: DeviceId, patch: LightingPatch, scenario: OperationScenario) => {
    const epoch = lifetime.current
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
      if (!mounted.current || epoch !== lifetime.current) return
      if (operationId <= (recoveryCommandFloor.current[deviceId] ?? 0)) throw new OperationError('COMMAND_CANCELED')
      if (fieldsOf(patch).some((field) => latestByField.current[deviceId]?.[field] === operationId)) appliedRevision.current[deviceId] = (appliedRevision.current[deviceId] ?? 0) + 1
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
      if (!mounted.current || epoch !== lifetime.current) return
      const code = operationId <= (recoveryCommandFloor.current[deviceId] ?? 0) ? 'COMMAND_CANCELED' : error instanceof OperationError ? error.code : 'DEVICE_ERROR'
      const status = code === 'COMMAND_CANCELED' ? 'canceled' : code === 'DEVICE_OFFLINE' ? 'offline' : 'error'
      const isLatestOperation = latestOperationByDevice.current[deviceId] === operationId
      const message = status === 'canceled' ? 'Operação cancelada' : status === 'offline' ? 'O dispositivo está offline' : 'Não foi possível atualizar'

      if (isLatestOperation) {
        latestOutcomeByDevice.current[deviceId] = { status, error: message }
      }

      if (status === 'offline' && isLatestOperation) {
        appliedRevision.current[deviceId] = (appliedRevision.current[deviceId] ?? 0) + 1
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

  const refreshDevice = useCallback(async (deviceId: DeviceId) => {
    const epoch = lifetime.current
    if (!controller.refresh || activeRefresh.current[deviceId] || (views[deviceId]?.pendingOperations.length ?? 0) > 0) return
    activeRefresh.current[deviceId] = true
    const version = latestOperationByDevice.current[deviceId] ?? 0
    const requestId = (refreshSequence.current[deviceId] ?? 0) + 1
    refreshSequence.current[deviceId] = requestId
    setRefreshing((current) => ({ ...current, [deviceId]: true }))
    setRefreshErrors((current) => ({ ...current, [deviceId]: null }))
    try {
      const device = await controller.refresh(deviceId)
      if (!mounted.current || epoch !== lifetime.current || requestId <= (recoveryRefreshFloor.current[deviceId] ?? 0) || refreshSequence.current[deviceId] !== requestId || (latestOperationByDevice.current[deviceId] ?? 0) !== version) return
      appliedRevision.current[deviceId] = (appliedRevision.current[deviceId] ?? 0) + 1
      setDevices((current) => current.map((item) => item.deviceId === deviceId ? device : item))
      setViews((current) => {
        const view = current[deviceId]
        if (!view || view.pendingOperations.length) return current
        const confirmed = { ...device.state, hsv: { ...device.state.hsv }, knowledge: { ...device.state.knowledge } }
        return { ...current, [deviceId]: { ...view, confirmed, preview: confirmed, error: null, status: 'idle' } }
      })
    } catch (error) {
      if (!mounted.current || epoch !== lifetime.current || requestId <= (recoveryRefreshFloor.current[deviceId] ?? 0) || refreshSequence.current[deviceId] !== requestId || (latestOperationByDevice.current[deviceId] ?? 0) !== version) return
      if (error instanceof OperationError && error.code === 'COMMAND_CANCELED') return
      const offline = error instanceof OperationError && (error.code === 'DEVICE_OFFLINE' || error.code === 'TIMEOUT' || error.code === 'AUTH_FAILED')
      if (offline) appliedRevision.current[deviceId] = (appliedRevision.current[deviceId] ?? 0) + 1
      if (offline) setDevices((current) => current.map((item) => item.deviceId === deviceId ? { ...item, connection: 'offline', state: { ...item.state, quality: 'offline', knowledge: Object.fromEntries(Object.entries(item.state.knowledge).map(([key, value]) => [key, value === 'observed' ? 'stale' : value])) as typeof item.state.knowledge } } : item))
      if (offline) setViews((current) => {
        const view = current[deviceId]
        if (!view) return current
        const stale = (state: typeof view.confirmed) => ({ ...state, quality: 'offline' as const, knowledge: Object.fromEntries(Object.entries(state.knowledge).map(([key, value]) => [key, value === 'observed' ? 'stale' : value])) as typeof state.knowledge })
        const confirmed = stale(view.confirmed)
        const preview = stale(view.preview)
        return { ...current, [deviceId]: { ...view, confirmed, preview } }
      })
      setRefreshErrors((current) => ({ ...current, [deviceId]: offline ? 'Device offline; previous reading preserved' : 'Unable to refresh device state' }))
    } finally {
      if (epoch === lifetime.current) activeRefresh.current[deviceId] = false
      if (mounted.current && epoch === lifetime.current && refreshSequence.current[deviceId] === requestId) setRefreshing((current) => ({ ...current, [deviceId]: false }))
    }
  }, [controller, views])

  const prepareRecovery = useCallback(async (deviceId: DeviceId): Promise<PrepareOutcome> => {
    if (!recovery || !mounted.current) return { kind: 'rejected', code: 'INVALID_INPUT' }
    const epoch = lifetime.current
    let outcome: PrepareOutcome
    try { outcome = await recovery.controller.prepare(deviceId) }
    catch (error) { outcome = { kind: 'bridge-error', code: parseBridgeError(error).code } }
    if (mounted.current && epoch === lifetime.current && outcome.kind === 'terminal' && outcome.result.status === 'PROPOSAL_READY') {
      for (const [id, device] of proposals.current) if (device === deviceId) proposals.current.delete(id)
      proposals.current.set(outcome.result.proposalId, deviceId)
    }
    return outcome
  }, [recovery])

  const confirmRecovery = useCallback(async (proposalId: string): Promise<ConfirmOutcome> => {
    const deviceId = proposals.current.get(proposalId)
    if (!recovery || !mounted.current || !deviceId) return { kind: 'rejected', code: 'PROPOSAL_UNAVAILABLE' }
    proposals.current.delete(proposalId)
    const epoch = lifetime.current
    const generation = (recoverySequence.current[deviceId] ?? 0) + 1
    recoverySequence.current[deviceId] = generation
    const command = latestOperationByDevice.current[deviceId] ?? 0
    const refresh = refreshSequence.current[deviceId] ?? 0
    const revision = appliedRevision.current[deviceId] ?? 0
    let token
    try { token = recovery.reconciliation.beginRecoveryConfirmation(deviceId) }
    catch { return { kind: 'rejected', code: 'PROPOSAL_UNAVAILABLE' } }
    let outcome: ConfirmOutcome
    try { outcome = await recovery.controller.confirm(proposalId) }
    catch (error) { outcome = { kind: 'indeterminate', code: parseBridgeError(error).code } }
    const adopted = outcome.kind === 'terminal' && outcome.result.recovery.status === 'ADOPTED'
    // Unknown commit outcome also makes the previous baseline unsafe, without asserting adoption.
    const device = adopted || outcome.kind === 'indeterminate'
      ? recovery.reconciliation.reconcileRecovery(token, outcome.kind === 'terminal' ? outcome.result.readback : undefined)
      : undefined
    // Reconcile controller caches even after unmount; never claim that unmount canceled the backend.
    if (!mounted.current || epoch !== lifetime.current || recoverySequence.current[deviceId] !== generation) return outcome
    if (outcome.kind === 'terminal' && outcome.result.recovery.status === 'BUSY') proposals.current.set(proposalId, deviceId)
    if (!adopted && outcome.kind !== 'indeterminate') return outcome
    recoveryCommandFloor.current[deviceId] = Math.max(recoveryCommandFloor.current[deviceId] ?? 0, command)
    recoveryRefreshFloor.current[deviceId] = Math.max(recoveryRefreshFloor.current[deviceId] ?? 0, refresh)
    if (!device || (appliedRevision.current[deviceId] ?? 0) !== revision) return outcome
    appliedRevision.current[deviceId] = revision + 1
    setDevices((current) => current.map((item) => item.deviceId === deviceId ? device : item))
    setViews((current) => {
      const view = current[deviceId]
      if (!view) return current
      const confirmed = { ...device.state, hsv: { ...device.state.hsv }, knowledge: { ...device.state.knowledge } }
      return { ...current, [deviceId]: { ...view, confirmed,
        preview: visiblePreview(confirmed, view.pendingOperations, latestByField.current[deviceId] ?? {}),
        status: view.pendingOperations.length ? 'pending' : 'idle', error: null } }
    })
    return outcome
  }, [recovery])

  const selectedDevice = devices.find((device) => device.deviceId === selectedDeviceId) ?? null
  const selectedView = selectedDeviceId ? views[selectedDeviceId] ?? null : null

  return { devices, selectedDevice, selectedView, selectedDeviceId, selectDevice: setSelectedDeviceId, issue, loadError, refreshDevice, refreshing, refreshError: selectedDeviceId ? refreshErrors[selectedDeviceId] ?? null : null,
    prepareRecovery, confirmRecovery, recoveryEligibility: (deviceId: string) => recovery?.reconciliation.eligibility(deviceId) ?? { status: 'UNKNOWN' as const, protocolVersion: null } }
}
