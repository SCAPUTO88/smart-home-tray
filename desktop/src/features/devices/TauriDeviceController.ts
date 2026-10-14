import type { DeviceController, DeviceId, HsvColor, LightingDevice, LightingPatch, OperationScenario } from './types'
import { OperationError } from './types'
import { mapPublicDevice, parseBridgeError, type PublicDeviceStatus } from './publicDeviceMapper'

export type BridgeRequest =
  | { command: 'devices.list'; payload: Record<string, never> }
  | { command: 'device.power'; payload: { deviceId: string; enabled: boolean } }
  | { command: 'device.whiteBrightness' | 'device.colorTemperature'; payload: { deviceId: string; percent: number } }
  | { command: 'device.hsv'; payload: { deviceId: string; hue: number; saturation: number; value: number } }

export interface BridgeApi {
  list(): Promise<PublicDeviceStatus[]>
  status(deviceId: DeviceId): Promise<PublicDeviceStatus>
  command(request: Exclude<BridgeRequest, { command: 'devices.list' }>): Promise<PublicDeviceStatus>
}

const hsvChannels = ['hue', 'saturation', 'value'] as const

function hasObservedReadback(status: PublicDeviceStatus): boolean {
  return status.connection === 'online' && Object.values(status.state.knowledge).some((knowledge) => knowledge === 'observed')
}

function offlineStatus(status: PublicDeviceStatus): PublicDeviceStatus {
  const knowledge = Object.fromEntries(Object.entries(status.state.knowledge).map(([key, value]) => [key, value === 'observed' ? 'stale' : value])) as PublicDeviceStatus['state']['knowledge']
  return { ...status, connection: 'offline', state: { ...status.state, quality: 'offline', knowledge } }
}

export class TauriDeviceController implements DeviceController {
  readonly mode: 'fixture' | 'real'
  private readonly known = new Map<DeviceId, LightingDevice>()
  private readonly knownPublic = new Map<DeviceId, PublicDeviceStatus>()
  private readonly confirmedBase = new Map<DeviceId, PublicDeviceStatus>()
  private readonly latestResponse = new Map<DeviceId, number>()
  private readonly pendingHsv = new Map<DeviceId, Map<number, HsvColor>>()
  private sequence = 0
  private readonly pendingWrites = new Map<DeviceId, number>()
  private readonly refreshSequence = new Map<DeviceId, number>()
  private readonly bridge: BridgeApi

  constructor(bridge: BridgeApi, mode: 'fixture' | 'real' = 'fixture') { this.bridge = bridge; this.mode = mode }

  async list(): Promise<LightingDevice[]> {
    const catalog = await this.bridge.list()
    const statuses = this.mode === 'real'
      ? await Promise.all(catalog.map(async (entry) => {
        try {
          const status = await this.bridge.status(entry.deviceId)
          if (status.deviceId !== entry.deviceId) return entry
          mapPublicDevice(status)
          return status
        } catch (error) {
          const code = parseBridgeError(error).code
          return code === 'DEVICE_OFFLINE' || code === 'TIMEOUT' || code === 'AUTH_FAILED'
            ? offlineStatus(entry)
            : entry
        }
      }))
      : catalog

    this.known.clear()
    this.knownPublic.clear()
    this.confirmedBase.clear()
    this.pendingHsv.clear()
    this.latestResponse.clear()
    const devices = statuses.map(mapPublicDevice)
    for (const status of statuses) {
      const device = devices.find((item) => item.deviceId === status.deviceId)
      if (!device) continue
      this.knownPublic.set(status.deviceId, status)
      this.known.set(status.deviceId, device)
      if (hasObservedReadback(status)) this.confirmedBase.set(status.deviceId, status)
    }
    return devices
  }

  async refresh(deviceId: DeviceId): Promise<LightingDevice> {
    if ((this.pendingWrites.get(deviceId) ?? 0) > 0) throw new OperationError('COMMAND_CANCELED')
    const current = this.knownPublic.get(deviceId)
    if (!current) throw new OperationError('DEVICE_ERROR')
    const version = this.latestResponse.get(deviceId) ?? 0
    const refreshId = (this.refreshSequence.get(deviceId) ?? 0) + 1
    this.refreshSequence.set(deviceId, refreshId)
    try {
      const status = await this.bridge.status(deviceId)
      if (status.deviceId !== deviceId || (this.latestResponse.get(deviceId) ?? 0) !== version || this.refreshSequence.get(deviceId) !== refreshId || (this.pendingWrites.get(deviceId) ?? 0) > 0) throw new OperationError('COMMAND_CANCELED')
      const mapped = mapPublicDevice(status)
      this.knownPublic.set(deviceId, status)
      this.known.set(deviceId, mapped)
      if (status.connection === 'online') this.confirmedBase.set(deviceId, status)
      return mapped
    } catch (error) {
      const normalized = parseBridgeError(error)
      if (normalized.code === 'DEVICE_OFFLINE' || normalized.code === 'TIMEOUT' || normalized.code === 'AUTH_FAILED') {
        const offline = offlineStatus(current)
        this.knownPublic.set(deviceId, offline)
        this.known.set(deviceId, mapPublicDevice(offline))
      }
      throw normalized
    }
  }

  async command(deviceId: DeviceId, patch: LightingPatch, _scenario?: OperationScenario): Promise<LightingDevice> {
    const device = this.known.get(deviceId)
    const publicStatus = this.knownPublic.get(deviceId)
    if (!device || !publicStatus) throw new OperationError('DEVICE_ERROR')
    if (device.connection !== 'online') throw new OperationError('DEVICE_OFFLINE')
    if ((patch.enabled !== undefined && !device.capabilities.power) || (patch.hsv && !device.capabilities.rgb) || (patch.whiteBrightness !== undefined && !device.capabilities.white) || (patch.whiteTemperature !== undefined && !device.capabilities.temperature)) throw new OperationError('UNSUPPORTED_CAPABILITY')

    const id = ++this.sequence
    let request: Exclude<BridgeRequest, { command: 'devices.list' }>
    if (patch.enabled !== undefined) {
      const base = this.confirmedBase.get(deviceId)
      if (!base || base.state.power === null || base.state.knowledge.power !== 'observed') throw new OperationError('DEVICE_ERROR')
      request = { command: 'device.power', payload: { deviceId, enabled: patch.enabled } }
    } else if (patch.whiteTemperature !== undefined) request = { command: 'device.colorTemperature', payload: { deviceId, percent: patch.whiteTemperature } }
    else if (patch.whiteBrightness !== undefined) request = { command: 'device.whiteBrightness', payload: { deviceId, percent: patch.whiteBrightness } }
    else if (patch.mode === 'white') {
      if (!device.capabilities.white) throw new OperationError('UNSUPPORTED_CAPABILITY')
      const base = this.confirmedBase.get(deviceId)
      if (base?.state.whiteBrightnessPercent !== null && base?.state.whiteBrightnessPercent !== undefined && base.state.knowledge.whiteBrightness === 'observed') request = { command: 'device.whiteBrightness', payload: { deviceId, percent: base.state.whiteBrightnessPercent } }
      else if (base?.state.colorTemperaturePercent !== null && base?.state.colorTemperaturePercent !== undefined && base.state.knowledge.colorTemperature === 'observed') request = { command: 'device.colorTemperature', payload: { deviceId, percent: base.state.colorTemperaturePercent } }
      else throw new OperationError('DEVICE_ERROR')
    } else if (patch.mode === 'rgb' || patch.hsv) {
      if (!device.capabilities.rgb) throw new OperationError('UNSUPPORTED_CAPABILITY')
      const pending = this.pendingHsv.get(deviceId)
      const latestPending = pending && [...pending.entries()].sort(([left], [right]) => right - left)[0]?.[1]
      const base = this.confirmedBase.get(deviceId)
      const current = latestPending ?? (base?.state.hsv && base.state.knowledge.hsv === 'observed' ? { ...base.state.hsv } : undefined)
      if (!current || hsvChannels.some((channel) => !Number.isFinite(current[channel]))) throw new OperationError('DEVICE_ERROR')
      const hsv: HsvColor = { ...current }
      for (const channel of hsvChannels) {
        const value = patch.hsv?.[channel]
        if (value !== undefined) hsv[channel] = value
      }
      request = { command: 'device.hsv', payload: { deviceId, ...hsv } }
      const operations = pending ?? new Map<number, HsvColor>()
      operations.set(id, hsv)
      this.pendingHsv.set(deviceId, operations)
    } else throw new OperationError('INVALID_INPUT')

    this.pendingWrites.set(deviceId, (this.pendingWrites.get(deviceId) ?? 0) + 1)
    this.latestResponse.set(deviceId, id)
    try {
      const status = await this.bridge.command(request)
      if (status.deviceId !== deviceId) throw new OperationError('DEVICE_ERROR')
      const response = mapPublicDevice(status)
      const latest = this.latestResponse.get(deviceId) ?? 0
      if (id >= latest) {
        this.latestResponse.set(deviceId, id)
        this.known.set(deviceId, response)
        this.knownPublic.set(deviceId, status)
        if (hasObservedReadback(status)) this.confirmedBase.set(deviceId, status)
        const operations = this.pendingHsv.get(deviceId)
        if (operations) {
          for (const pendingId of operations.keys()) if (pendingId <= id) operations.delete(pendingId)
          if (operations.size === 0) this.pendingHsv.delete(deviceId)
        }
      }
      return response
    } catch (error) {
      const normalized = parseBridgeError(error)
      if (normalized.code === 'DEVICE_OFFLINE' || normalized.code === 'TIMEOUT' || normalized.code === 'AUTH_FAILED') {
        const current = this.knownPublic.get(deviceId)
        if (current) {
          const offline = offlineStatus(current)
          this.knownPublic.set(deviceId, offline)
          this.known.set(deviceId, mapPublicDevice(offline))
        }
      }
      this.pendingHsv.get(deviceId)?.delete(id)
      if (this.pendingHsv.get(deviceId)?.size === 0) this.pendingHsv.delete(deviceId)
      throw normalized
    } finally {
      const count = (this.pendingWrites.get(deviceId) ?? 1) - 1
      if (count > 0) this.pendingWrites.set(deviceId, count)
      else this.pendingWrites.delete(deviceId)
    }
  }
}
