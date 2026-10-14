import { describe, expect, it, vi } from 'vitest'
import { TauriDeviceController, type BridgeApi } from './TauriDeviceController'
import type { PublicDeviceStatus } from './publicDeviceMapper'

const device: PublicDeviceStatus = {
  deviceId: 'lamp', name: 'Desk', address: '127.0.0.1', protocolVersion: 3.3, capabilities: { power: true, whiteBrightness: true, colorValue: true, colorTemperature: true, scenes: false }, connection: 'online',
  state: { power: true, workMode: 'colour', whiteBrightnessPercent: 40, colorValuePercent: 60, colorTemperaturePercent: 50, hsv: { hue: 120, saturation: 70, value: 60 }, scene: null, quality: 'confirmed' },
}

function api(): BridgeApi { return { list: vi.fn(async () => [device]), command: vi.fn(async () => device) } }

describe('TauriDeviceController', () => {
  it('recomposes partial HSV channels with current and pending intentions', async () => {
    const bridge = api(); const controller = new TauriDeviceController(bridge); await controller.list()
    const first = controller.command('lamp', { hsv: { hue: 200 } }); const second = controller.command('lamp', { hsv: { saturation: 25 } })
    await Promise.all([first, second])
    expect(bridge.command).toHaveBeenNthCalledWith(2, { command: 'device.hsv', payload: { deviceId: 'lamp', hue: 200, saturation: 25, value: 60 } })
  })
  it('uses existing white brightness and HSV operations for mode changes', async () => {
    const bridge = api(); const controller = new TauriDeviceController(bridge); await controller.list()
    await controller.command('lamp', { mode: 'white' }); await controller.command('lamp', { mode: 'rgb' })
    expect(bridge.command).toHaveBeenNthCalledWith(1, { command: 'device.whiteBrightness', payload: { deviceId: 'lamp', percent: 40 } })
    expect(bridge.command).toHaveBeenNthCalledWith(2, { command: 'device.hsv', payload: { deviceId: 'lamp', hue: 120, saturation: 70, value: 60 } })
  })
  it('rejects mode changes when required readback is unknown', async () => {
    const bridge = api(); bridge.list = vi.fn(async () => [{ ...device, state: { ...device.state, hsv: null } }]); const controller = new TauriDeviceController(bridge); await controller.list()
    await expect(controller.command('lamp', { mode: 'rgb' })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    expect(bridge.command).not.toHaveBeenCalled()
  })
  it('normalizes bridge errors', async () => {
    const bridge = api(); bridge.command = vi.fn(async () => { throw { code: 'TIMEOUT' } }); const controller = new TauriDeviceController(bridge); await controller.list()
    await expect(controller.command('lamp', { enabled: false })).rejects.toMatchObject({ code: 'TIMEOUT' })
  })
})
