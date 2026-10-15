import { OperationError as OperationErrorClass, type DeviceKind, type LightingDevice, type StateQuality, type DeviceKnowledge } from './types'

export interface PublicDeviceStatus {
  deviceId: string; name: string; address: string; protocolVersion: number;
  capabilities: { power: boolean; whiteBrightness: boolean; colorValue: boolean; colorTemperature: boolean; scenes: boolean };
  connection: 'online' | 'offline' | 'unknown';
  state: { power: boolean | null; workMode: string | null; whiteBrightnessPercent: number | null; colorValuePercent: number | null; colorTemperaturePercent: number | null; hsv: { hue: number; saturation: number; value: number } | null; scene: string | null; quality: StateQuality; knowledge: DeviceKnowledge };
}

export function mapPublicDevice(status: PublicDeviceStatus): LightingDevice {
  const caps = status.capabilities
  const state = status.state
  const kind: DeviceKind = caps.whiteBrightness || caps.colorTemperature ? 'bulb' : 'led-strip'
  const hsv = state.hsv
  const white = caps.whiteBrightness || caps.colorTemperature
  const quality: StateQuality = status.connection === 'offline' ? 'offline' : status.connection !== 'online' ? 'unknown' : state.quality
  const mode = state.workMode === 'white' || (white && !caps.colorValue) ? 'white' : 'rgb'
  return {
    deviceId: status.deviceId, name: status.name, kind,
    capabilities: { power: caps.power, rgb: caps.colorValue, white, temperature: caps.colorTemperature },
    connection: status.connection,
    state: {
      enabled: state.power ?? false, mode,
      hsv: { hue: hsv?.hue ?? 0, saturation: hsv?.saturation ?? 0, value: hsv?.value ?? state.colorValuePercent ?? 0 },
      whiteBrightness: state.whiteBrightnessPercent ?? 0, whiteTemperature: state.colorTemperaturePercent ?? 0, quality,
      knowledge: state.knowledge,
    },
  }
}

export function parseBridgeError(value: unknown): import('./types').OperationError {
  const allowed = ['COMMAND_CANCELED', 'DEVICE_OFFLINE', 'DEVICE_ERROR', 'UNSUPPORTED_CAPABILITY', 'TIMEOUT', 'AUTH_FAILED', 'INVALID_INPUT'] as const
  const candidate = typeof value === 'object' && value !== null && 'code' in value ? String((value as { code: unknown }).code) : 'DEVICE_ERROR'
  const code = allowed.includes(candidate as typeof allowed[number]) ? candidate as typeof allowed[number] : 'DEVICE_ERROR'
  return new OperationErrorClass(code)
}
