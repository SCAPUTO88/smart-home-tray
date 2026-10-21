import { createMockDeviceController } from './MockDeviceController'
import { MockManualRecoveryController } from './MockManualRecoveryController'
import { TauriDeviceController, type BridgeApi } from '../features/devices/TauriDeviceController'
import type { PublicDeviceStatus } from '../features/devices/publicDeviceMapper'
import type { LightingDevice, LightingPatch } from '../features/devices/types'

export function createMockDeviceIntegration() {
  const memory = createMockDeviceController()
  const catalog = new Map<string, PublicDeviceStatus>()
  const addresses = new Map<string, string>()
  function publicStatus(device: LightingDevice): PublicDeviceStatus {
    return {
      deviceId: device.deviceId, name: device.name, address: addresses.get(device.deviceId) ?? '',
      protocolVersion: device.deviceId === 'mock-desk-lamp' ? 3.5 : 3.3,
      capabilities: { power: device.capabilities.power, whiteBrightness: device.capabilities.white, colorValue: device.capabilities.rgb, colorTemperature: device.capabilities.temperature, scenes: false },
      connection: device.connection,
      state: { power: device.state.enabled, workMode: device.state.mode === 'rgb' ? 'colour' : 'white', whiteBrightnessPercent: device.state.whiteBrightness, colorValuePercent: device.state.hsv.value, colorTemperaturePercent: device.state.whiteTemperature, hsv: { ...device.state.hsv }, scene: null, quality: device.state.quality, knowledge: { ...device.state.knowledge } },
    }
  }
  const bridge: BridgeApi = {
    async list() {
      const devices = (await memory.list()).map(publicStatus)
      for (const device of devices) catalog.set(device.deviceId, device)
      return devices
    },
    async status(id) { return publicStatus(await memory.refresh!(id)) },
    async command(request, scenario) {
      const { deviceId } = request.payload
      let patch: LightingPatch
      switch (request.command) {
        case 'device.power': patch = { enabled: request.payload.enabled }; break
        case 'device.whiteBrightness': patch = { mode: 'white', whiteBrightness: request.payload.percent }; break
        case 'device.colorTemperature': patch = { mode: 'white', whiteTemperature: request.payload.percent }; break
        case 'device.hsv': patch = { mode: 'rgb', hsv: { hue: request.payload.hue, saturation: request.payload.saturation, value: request.payload.value } }; break
      }
      return publicStatus(await memory.command(deviceId, patch, scenario))
    },
  }
  // Reuse the revision/knowledge guards with an in-memory bridge, without invoke.
  const lighting = new TauriDeviceController(bridge, 'mock')
  const controller = new MockManualRecoveryController(() => [...catalog.values()], async (id, address) => {
    addresses.set(id, address)
    return { status: 'SUCCEEDED', device: await bridge.status(id) }
  })
  return { lighting, recovery: { controller, reconciliation: lighting } }
}

