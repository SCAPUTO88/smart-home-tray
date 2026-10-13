import type {
  DeviceController,
  DeviceId,
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
    state: { enabled: true, mode: 'rgb', hsv: { hue: 194, saturation: 77, value: 82 }, whiteBrightness: 64, whiteTemperature: 48, quality: 'confirmed' },
  },
  {
    deviceId: 'mock-led-strip',
    name: 'Fita LED',
    kind: 'led-strip',
    capabilities: { power: true, rgb: true, white: false, temperature: false },
    connection: 'online',
    state: { enabled: true, mode: 'rgb', hsv: { hue: 268, saturation: 88, value: 70 }, whiteBrightness: 0, whiteTemperature: 0, quality: 'confirmed' },
  },
]

function copyDevice(device: LightingDevice): LightingDevice {
  return { ...device, capabilities: { ...device.capabilities }, state: { ...device.state, hsv: { ...device.state.hsv } } }
}

function wait(duration: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, duration))
}

export function createMockDevices(): LightingDevice[] {
  return initialDevices.map(copyDevice)
}

export function createMockDeviceController(options: MockControllerOptions = {}): DeviceController {
  const devices = new Map(createMockDevices().map((device) => [device.deviceId, device]))
  const latestSequence = new Map<DeviceId, number>()
  const baseDelay = options.delayMs ?? 420
  const delayedOperation = options.delayScenarioMs ?? 1400

  return {
    async list() {
      return [...devices.values()].map(copyDevice)
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

      const sequence = (latestSequence.get(deviceId) ?? 0) + 1
      latestSequence.set(deviceId, sequence)
      if (scenario === 'offline') {
        current.connection = 'offline'
        current.state.quality = 'offline'
        throw new OperationError('DEVICE_OFFLINE')
      }
      if (current.connection === 'offline') throw new OperationError('DEVICE_OFFLINE')

      await wait(scenario === 'delay' ? delayedOperation : baseDelay)
      if (latestSequence.get(deviceId) !== sequence) return copyDevice(current)
      if (scenario === 'canceled') throw new OperationError('COMMAND_CANCELED')
      if (scenario === 'error') throw new OperationError('DEVICE_ERROR')

      current.state = {
        ...current.state,
        ...patch,
        hsv: patch.hsv ? { ...patch.hsv } : current.state.hsv,
        quality: 'confirmed',
      }
      return copyDevice(current)
    },
  }
}
