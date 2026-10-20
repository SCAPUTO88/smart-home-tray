import { invoke, isTauri } from '@tauri-apps/api/core'
import type { DeviceController } from './types'
import { createMockDeviceIntegration } from '../../mock/createMockDeviceIntegration'
import { TauriManualRecoveryController } from '../recovery/TauriManualRecoveryController'
import type { RecoveryIntegration } from '../recovery/reconciliation'
import { TauriDeviceController, type BridgeApi } from './TauriDeviceController'
import type { PublicDeviceStatus } from './publicDeviceMapper'

interface BridgeInfo { mode: 'mock' | 'fixture' | 'real'; available: boolean; error: unknown }

const bridgeApi: BridgeApi = {
  async list() {
    const result = await invoke<{ devices: PublicDeviceStatus[] }>('bridge_list')
    if (!result || !Array.isArray(result.devices)) throw { code: 'DEVICE_ERROR' }
    return result.devices
  },
  status(deviceId) {
    return invoke<PublicDeviceStatus>('bridge_status', { deviceId })
  },
  async command(request) {
    const payload = request.payload
    switch (request.command) {
      case 'device.power': return invoke<PublicDeviceStatus>('bridge_power', payload)
      case 'device.whiteBrightness': return invoke<PublicDeviceStatus>('bridge_white_brightness', payload)
      case 'device.colorTemperature': return invoke<PublicDeviceStatus>('bridge_color_temperature', payload)
      case 'device.hsv': return invoke<PublicDeviceStatus>('bridge_hsv', payload)
      default: throw { code: 'INVALID_INPUT' }
    }
  },
}

export interface DeviceIntegration { lighting: DeviceController; recovery: RecoveryIntegration }

export async function resolveDeviceIntegration(): Promise<DeviceIntegration> {
  if (!isTauri()) return createMockDeviceIntegration()
  const info = await invoke<BridgeInfo>('bridge_info')
  if (info.mode === 'mock') return createMockDeviceIntegration()
  if (!info.available) throw info.error ?? { code: 'DEVICE_ERROR' }
  if (info.mode !== 'fixture' && info.mode !== 'real') throw { code: 'DEVICE_ERROR' }
  const lighting = new TauriDeviceController(bridgeApi, info.mode)
  return { lighting, recovery: { controller: new TauriManualRecoveryController(invoke), reconciliation: lighting } }
}

export async function resolveDeviceController(): Promise<DeviceController> {
  return (await resolveDeviceIntegration()).lighting
}
