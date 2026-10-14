import type {
  DeviceController,
  DeviceId,
  HsvColor,
  LightingDevice,
  LightingPatch,
  OperationScenario,
} from '../features/devices/types'
import { OperationError } from '../features/devices/types'

export interface MockControllerOptions {
  delayMs?: number
  delayScenarioMs?: number
}

const initialDevices: LightingDevice[] = [
  {
    deviceId: 'mock-desk-lamp',
    name: 'Luz Mesa',
    kind: 'bulb',
    capabilities: { power: true, rgb: true, white: true, temperature: true },
    connection: 'online',
    state: { enabled: true, mode: 'rgb', hsv: { hue: 194, saturation: 77, value: 82 }, whiteBrightness: 64, whiteTemperature: 48, quality: 'confirmed', knowledge: { power: 'observed', workMode: 'observed', whiteBrightness: 'observed', colorTemperature: 'observed', hsv: 'observed', colorValue: 'observed', scene: 'unknown' } },
  },
  {
    deviceId: 'mock-led-strip',
    name: 'Fita LED',
    kind: 'led-strip',
    capabilities: { power: true, rgb: true, white: false, temperature: false },
    connection: 'online',
    state: { enabled: true, mode: 'rgb', hsv: { hue: 268, saturation: 88, value: 70 }, whiteBrightness: 0, whiteTemperature: 0, quality: 'confirmed', knowledge: { power: 'observed', workMode: 'observed', whiteBrightness: 'observed', colorTemperature: 'observed', hsv: 'observed', colorValue: 'observed', scene: 'unknown' } },
  },
]

function copyDevice(device: LightingDevice): LightingDevice {
  return { ...device, capabilities: { ...device.capabilities }, state: { ...device.state, hsv: { ...device.state.hsv } } }
}

function wait(duration: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, duration))
}

function isOffline(device: LightingDevice): boolean {
  return device.connection === 'offline'
}

type LightingField = 'enabled' | 'mode' | 'whiteBrightness' | 'whiteTemperature' | `hsv.${keyof HsvColor}`

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

function applyField(device: LightingDevice, patch: LightingPatch, field: LightingField): void {
  if (field.startsWith('hsv.')) {
    const channel = field.slice(4) as keyof HsvColor
    const value = patch.hsv?.[channel]
    if (value !== undefined) device.state.hsv[channel] = value
  } else {
    const value = field === 'enabled'
      ? patch.enabled
      : field === 'mode'
        ? patch.mode
        : field === 'whiteBrightness'
          ? patch.whiteBrightness
          : patch.whiteTemperature
    if (value !== undefined) Object.assign(device.state, { [field]: value })
  }
}

export function createMockDevices(): LightingDevice[] {
  return initialDevices.map(copyDevice)
}

export function createMockDeviceController(options: MockControllerOptions = {}): DeviceController {
  const devices = new Map(createMockDevices().map((device) => [device.deviceId, device]))
  const latestSequenceByField = new Map<DeviceId, Map<LightingField, number>>()
  let sequence = 0
  const baseDelay = options.delayMs ?? 420
  const delayedOperation = options.delayScenarioMs ?? 1400

  return {
    mode: 'mock' as const,
    async list() {
      return [...devices.values()].map(copyDevice)
    },
    async refresh(deviceId: DeviceId) {
      const device = devices.get(deviceId)
      if (!device) throw new OperationError('DEVICE_ERROR')
      return copyDevice(device)
    },
    async command(deviceId: DeviceId, patch: LightingPatch, scenario: OperationScenario = 'success') {
      const current = devices.get(deviceId)
      if (!current) throw new OperationError('DEVICE_ERROR')
      if ((patch.whiteBrightness !== undefined && !current.capabilities.white)
        || (patch.whiteTemperature !== undefined && !current.capabilities.temperature)
        || (patch.hsv !== undefined && !current.capabilities.rgb)
        || (patch.enabled !== undefined && !current.capabilities.power)) {
        throw new OperationError('UNSUPPORTED_CAPABILITY')
      }

      const operationId = ++sequence
      const fields = fieldsOf(patch)
      let latestByField = latestSequenceByField.get(deviceId)
      if (!latestByField) {
        latestByField = new Map()
        latestSequenceByField.set(deviceId, latestByField)
      }
      for (const field of fields) latestByField.set(field, operationId)
      if (scenario === 'offline') {
        current.connection = 'offline'
        current.state.quality = 'offline'
        throw new OperationError('DEVICE_OFFLINE')
      }
      if (isOffline(current)) throw new OperationError('DEVICE_OFFLINE')

      await wait(scenario === 'delay' ? delayedOperation : baseDelay)
      if (isOffline(current)) throw new OperationError('DEVICE_OFFLINE')
      if (scenario === 'canceled') throw new OperationError('COMMAND_CANCELED')
      if (scenario === 'error') throw new OperationError('DEVICE_ERROR')

      for (const field of fields) {
        if (latestByField.get(field) === operationId) applyField(current, patch, field)
      }
      if (current.state.quality !== 'unknown') current.state.quality = 'confirmed'
      return copyDevice(current)
    },
  }
}
