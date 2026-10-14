import type { DeviceController, DeviceId, LightingDevice, LightingPatch, OperationScenario } from './types'
import { OperationError } from './types'
import { mapPublicDevice, parseBridgeError, type PublicDeviceStatus } from './publicDeviceMapper'

export type BridgeRequest =
  | { command: 'devices.list'; payload: Record<string, never> }
  | { command: 'device.power'; payload: { deviceId: string; enabled: boolean } }
  | { command: 'device.whiteBrightness' | 'device.colorTemperature'; payload: { deviceId: string; percent: number } }
  | { command: 'device.hsv'; payload: { deviceId: string; hue: number; saturation: number; value: number } }

export interface BridgeApi {
  list(): Promise<PublicDeviceStatus[]>
  command(request: Exclude<BridgeRequest, { command: 'devices.list' }>): Promise<PublicDeviceStatus>
}

type HsvChannel = 'hue' | 'saturation' | 'value'
interface Intent { id: number; value: number }
const hsvChannels: HsvChannel[] = ['hue', 'saturation', 'value']

export class TauriDeviceController implements DeviceController {
  readonly mode: 'fixture' | 'real'
  private readonly known = new Map<DeviceId, LightingDevice>()
  private readonly knownPublic = new Map<DeviceId, PublicDeviceStatus>()
  private readonly intents = new Map<DeviceId, Partial<Record<HsvChannel, Intent>>>()
  private sequence = 0
  private readonly bridge: BridgeApi

  constructor(bridge: BridgeApi, mode: 'fixture' | 'real' = 'fixture') { this.bridge = bridge; this.mode = mode }

  async list(): Promise<LightingDevice[]> {
    const statuses = await this.bridge.list()
    const devices = statuses.map(mapPublicDevice)
    for (const status of statuses) this.knownPublic.set(status.deviceId, status)
    for (const device of devices) this.known.set(device.deviceId, device)
    return devices
  }

  async command(deviceId: DeviceId, patch: LightingPatch, _scenario?: OperationScenario): Promise<LightingDevice> {
    const device = this.known.get(deviceId)
    const raw = this.knownPublic.get(deviceId)
    if (!device || !raw) throw new OperationError('DEVICE_ERROR')
    if ((patch.enabled !== undefined && !device.capabilities.power) || (patch.hsv && !device.capabilities.rgb) || (patch.whiteBrightness !== undefined && !device.capabilities.white) || (patch.whiteTemperature !== undefined && !device.capabilities.temperature)) throw new OperationError('UNSUPPORTED_CAPABILITY')

    const id = ++this.sequence
    const pending = { ...(this.intents.get(deviceId) ?? {}) }
    for (const channel of hsvChannels) {
      const value = patch.hsv?.[channel]
      if (value !== undefined) pending[channel] = { id, value }
    }

    let request: Exclude<BridgeRequest, { command: 'devices.list' }>
    if (patch.enabled !== undefined) request = { command: 'device.power', payload: { deviceId, enabled: patch.enabled } }
    else if (patch.whiteTemperature !== undefined) request = { command: 'device.colorTemperature', payload: { deviceId, percent: patch.whiteTemperature } }
    else if (patch.whiteBrightness !== undefined) request = { command: 'device.whiteBrightness', payload: { deviceId, percent: patch.whiteBrightness } }
    else if (patch.mode === 'white') {
      if (device.capabilities.white && raw.state.whiteBrightnessPercent !== null) request = { command: 'device.whiteBrightness', payload: { deviceId, percent: raw.state.whiteBrightnessPercent } }
      else if (device.capabilities.temperature && raw.state.colorTemperaturePercent !== null) request = { command: 'device.colorTemperature', payload: { deviceId, percent: raw.state.colorTemperaturePercent } }
      else throw new OperationError('DEVICE_ERROR')
    } else if (patch.mode === 'rgb' || patch.hsv) {
      if (!device.capabilities.rgb) throw new OperationError('UNSUPPORTED_CAPABILITY')
      const current = raw.state.hsv
      const hsv: Record<HsvChannel, number | undefined> = { hue: current?.hue, saturation: current?.saturation, value: current?.value }
      for (const channel of hsvChannels) hsv[channel] = pending[channel]?.value ?? hsv[channel]
      if (hsvChannels.some((channel) => !Number.isFinite(hsv[channel]))) throw new OperationError('DEVICE_ERROR')
      request = { command: 'device.hsv', payload: { deviceId, hue: hsv.hue!, saturation: hsv.saturation!, value: hsv.value! } }
    } else throw new OperationError('INVALID_INPUT')

    if (patch.hsv) this.intents.set(deviceId, pending)
    try {
      const status = await this.bridge.command(request)
      const response = mapPublicDevice(status)
      const latest = this.intents.get(deviceId) ?? {}
      for (const channel of hsvChannels) if (latest[channel]?.id === id) delete latest[channel]
      this.intents.set(deviceId, latest)
      this.known.set(deviceId, response)
      this.knownPublic.set(deviceId, status)
      return response
    } catch (error) {
      const latest = this.intents.get(deviceId) ?? {}
      for (const channel of hsvChannels) if (latest[channel]?.id === id) delete latest[channel]
      this.intents.set(deviceId, latest)
      throw parseBridgeError(error)
    }
  }
}
