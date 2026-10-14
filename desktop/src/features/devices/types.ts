export type DeviceId = string
export type DeviceKind = 'bulb' | 'led-strip'
export type DeviceMode = 'rgb' | 'white'
export type ConnectionState = 'online' | 'offline'
export type StateQuality = 'confirmed' | 'pending' | 'offline' | 'unknown'

export interface HsvColor {
  hue: number
  saturation: number
  value: number
}

export interface DeviceCapabilities {
  power: boolean
  rgb: boolean
  white: boolean
  temperature: boolean
}

export interface DeviceState {
  enabled: boolean
  mode: DeviceMode
  hsv: HsvColor
  whiteBrightness: number
  whiteTemperature: number
  quality: StateQuality
}

export interface LightingDevice {
  deviceId: DeviceId
  name: string
  kind: DeviceKind
  capabilities: DeviceCapabilities
  connection: ConnectionState
  state: DeviceState
}

export type LightingPatch = Partial<Omit<Pick<DeviceState, 'enabled' | 'mode' | 'hsv' | 'whiteBrightness' | 'whiteTemperature'>, 'hsv'>> & {
  hsv?: Partial<HsvColor>
}

export type OperationScenario = 'success' | 'delay' | 'canceled' | 'error' | 'offline'
export type OperationStatus = 'idle' | 'pending' | 'confirmed' | 'canceled' | 'offline' | 'error'

export interface DeviceController {
  list(): Promise<LightingDevice[]>
  command(deviceId: DeviceId, patch: LightingPatch, scenario?: OperationScenario): Promise<LightingDevice>
}

export interface DeviceViewState {
  requested: LightingPatch | null
  preview: DeviceState
  pendingOperations: Array<{ operationId: number; patch: LightingPatch }>
  confirmed: DeviceState
  error: string | null
  status: OperationStatus
}

export class OperationError extends Error {
  readonly code: 'COMMAND_CANCELED' | 'DEVICE_OFFLINE' | 'DEVICE_ERROR' | 'UNSUPPORTED_CAPABILITY'

  constructor(code: OperationError['code']) {
    super(code)
    this.name = 'OperationError'
    this.code = code
  }
}
