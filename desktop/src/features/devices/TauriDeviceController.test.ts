import { describe, expect, it, vi } from 'vitest'
import { TauriDeviceController, type BridgeApi } from './TauriDeviceController'
import type { PublicDeviceStatus } from './publicDeviceMapper'

const device: PublicDeviceStatus = {
  deviceId: 'lamp', name: 'Desk', address: '127.0.0.1', protocolVersion: 3.3, capabilities: { power: true, whiteBrightness: true, colorValue: true, colorTemperature: true, scenes: false }, connection: 'online',
  state: { power: true, workMode: 'colour', whiteBrightnessPercent: 40, colorValuePercent: 60, colorTemperaturePercent: 50, hsv: { hue: 120, saturation: 70, value: 60 }, scene: null, quality: 'confirmed' },
}

function api(): BridgeApi { return { list: vi.fn(async () => [device]), status: vi.fn(async () => device), command: vi.fn(async () => device) } }

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

  it("hydrates REAL catalog entries through status and isolates per-device failures", async () => {
    const unknown: PublicDeviceStatus = { ...device, connection: "unknown", state: { ...device.state, power: null, workMode: null, whiteBrightnessPercent: null, colorValuePercent: null, colorTemperaturePercent: null, hsv: null, quality: "unknown" } }
    const strip = { ...unknown, deviceId: "strip", name: "Strip", capabilities: { ...unknown.capabilities, whiteBrightness: false, colorTemperature: false }, state: { ...unknown.state } }
    const statusReadback = vi.fn(async (deviceId: string) => {
      if (deviceId === "strip") throw { code: "DEVICE_OFFLINE" }
      return device
    })
    const bridge = Object.assign({ ...api(), list: vi.fn(async () => [unknown, strip]) }, { status: statusReadback }) as BridgeApi & { status: typeof statusReadback }
    const controller = new TauriDeviceController(bridge, "real")
    const devices = await controller.list()
    expect(statusReadback).toHaveBeenCalledTimes(2)
    expect(devices[0].state.quality).toBe("confirmed")
    expect(devices[1]).toMatchObject({ connection: "offline", state: { quality: "offline" } })
    await expect(controller.command("strip", { mode: "rgb" })).rejects.toMatchObject({ code: "DEVICE_OFFLINE" })
    expect(bridge.command).not.toHaveBeenCalled()
  })
  it("does not hydrate MOCK or FIXTURE through status", async () => {
    const statusReadback = vi.fn(async () => device)
    const bridge = Object.assign(api(), { status: statusReadback }) as BridgeApi & { status: typeof statusReadback }
    await new TauriDeviceController(bridge, "fixture").list()
    expect(statusReadback).not.toHaveBeenCalled()
  })
  it("preserves unknown null state when REAL status has no confirmed readback", async () => {
    const unknown: PublicDeviceStatus = { ...device, connection: "unknown", state: { ...device.state, power: null, workMode: null, whiteBrightnessPercent: null, colorValuePercent: null, colorTemperaturePercent: null, hsv: null, quality: "unknown" } }
    const bridge = Object.assign({ ...api(), list: vi.fn(async () => [unknown]) }, { status: vi.fn(async () => ({ ...unknown, connection: "online" as const })) }) as BridgeApi & { status: ReturnType<typeof vi.fn> }
    const controller = new TauriDeviceController(bridge, "real")
    const [hydrated] = await controller.list()
    expect(hydrated).toMatchObject({ connection: "online", state: { enabled: false, quality: "unknown" } })
    await expect(controller.command("lamp", { mode: "rgb" })).rejects.toMatchObject({ code: "DEVICE_ERROR" })
    await expect(controller.command("lamp", { enabled: true })).rejects.toMatchObject({ code: "DEVICE_ERROR" })
    expect(bridge.command).not.toHaveBeenCalled()
  })


  it("keeps hue and saturation from a newer readback when responses finish out of order", async () => {
    let resolveHue!: (status: PublicDeviceStatus) => void
    let resolveSaturation!: (status: PublicDeviceStatus) => void
    const hueResponse = new Promise<PublicDeviceStatus>((resolve) => { resolveHue = resolve })
    const saturationResponse = new Promise<PublicDeviceStatus>((resolve) => { resolveSaturation = resolve })
    const bridge = api()
    bridge.command = vi.fn().mockImplementation(() => Promise.resolve(device)).mockImplementationOnce(() => hueResponse).mockImplementationOnce(() => saturationResponse)
    const controller = new TauriDeviceController(bridge); await controller.list()
    const hue = controller.command("lamp", { hsv: { hue: 210 } })
    const saturation = controller.command("lamp", { hsv: { saturation: 25 } })
    resolveSaturation({ ...device, state: { ...device.state, hsv: { hue: 210, saturation: 25, value: 60 }, colorValuePercent: 60 } }); await saturation
    resolveHue({ ...device, state: { ...device.state, hsv: { hue: 210, saturation: 70, value: 60 }, colorValuePercent: 60 } }); await hue
    await controller.command("lamp", { hsv: { value: 30 } })
    expect(bridge.command).toHaveBeenNthCalledWith(3, { command: "device.hsv", payload: { deviceId: "lamp", hue: 210, saturation: 25, value: 30 } })
  })
  it("retains the last confirmed channels after a canceled older intent", async () => {
    let rejectHue!: (reason: unknown) => void
    let resolveSaturation!: (status: PublicDeviceStatus) => void
    const hueResponse = new Promise<PublicDeviceStatus>((_, reject) => { rejectHue = reject })
    const saturationResponse = new Promise<PublicDeviceStatus>((resolve) => { resolveSaturation = resolve })
    const bridge = api()
    bridge.command = vi.fn().mockResolvedValue(device).mockImplementationOnce(() => hueResponse).mockImplementationOnce(() => saturationResponse).mockResolvedValueOnce({ ...device, state: { ...device.state, hsv: { hue: 210, saturation: 25, value: 30 }, colorValuePercent: 30 } }).mockResolvedValueOnce({ ...device, state: { ...device.state, hsv: { hue: 210, saturation: 25, value: 50 }, colorValuePercent: 50 } })
    const controller = new TauriDeviceController(bridge); await controller.list()
    const hue = controller.command("lamp", { hsv: { hue: 210 } })
    const saturation = controller.command("lamp", { hsv: { saturation: 25 } })
    rejectHue({ code: "COMMAND_CANCELED" }); await expect(hue).rejects.toMatchObject({ code: "COMMAND_CANCELED" })
    await controller.command("lamp", { hsv: { value: 30 } })
    expect(bridge.command).toHaveBeenNthCalledWith(3, { command: "device.hsv", payload: { deviceId: "lamp", hue: 210, saturation: 25, value: 30 } })
    resolveSaturation({ ...device, state: { ...device.state, hsv: { hue: 210, saturation: 25, value: 60 }, colorValuePercent: 60 } }); await saturation
    await controller.command("lamp", { hsv: { value: 50 } })
    expect(bridge.command).toHaveBeenNthCalledWith(4, { command: "device.hsv", payload: { deviceId: "lamp", hue: 210, saturation: 25, value: 50 } })
  })
  it("does not let one device response overwrite another devices HSV base", async () => {
    const strip: PublicDeviceStatus = { ...device, deviceId: "strip", name: "Strip", capabilities: { ...device.capabilities, whiteBrightness: false, colorTemperature: false }, state: { ...device.state, hsv: { hue: 10, saturation: 40, value: 50 }, colorValuePercent: 50 } }
    let resolveLamp!: (status: PublicDeviceStatus) => void
    let resolveStrip!: (status: PublicDeviceStatus) => void
    const lampResponse = new Promise<PublicDeviceStatus>((resolve) => { resolveLamp = resolve })
    const stripResponse = new Promise<PublicDeviceStatus>((resolve) => { resolveStrip = resolve })
    const bridge = { list: vi.fn(async () => [device, strip]), status: vi.fn(async () => device), command: vi.fn().mockImplementation((request: { payload: { deviceId: string } }) => Promise.resolve(request.payload.deviceId === "strip" ? strip : device)).mockImplementationOnce(() => lampResponse).mockImplementationOnce(() => stripResponse) }
    const controller = new TauriDeviceController(bridge); await controller.list()
    const lamp = controller.command("lamp", { hsv: { hue: 210 } })
    const led = controller.command("strip", { hsv: { saturation: 25 } })
    resolveStrip({ ...strip, state: { ...strip.state, hsv: { hue: 10, saturation: 25, value: 50 }, colorValuePercent: 50 } }); await led
    resolveLamp({ ...device, state: { ...device.state, hsv: { hue: 210, saturation: 70, value: 60 }, colorValuePercent: 60 } }); await lamp
    await Promise.all([controller.command("lamp", { hsv: { value: 30 } }), controller.command("strip", { hsv: { value: 30 } })])
    expect(bridge.command).toHaveBeenNthCalledWith(3, { command: "device.hsv", payload: { deviceId: "lamp", hue: 210, saturation: 70, value: 30 } })
    expect(bridge.command).toHaveBeenNthCalledWith(4, { command: "device.hsv", payload: { deviceId: "strip", hue: 10, saturation: 25, value: 30 } })
  })

  it("retains the confirmed HSV base after a failed command", async () => {
    const bridge = api()
    bridge.command = vi.fn().mockRejectedValueOnce({ code: "DEVICE_ERROR" }).mockResolvedValueOnce({
      ...device, state: { ...device.state, hsv: { hue: 120, saturation: 70, value: 35 }, colorValuePercent: 35 },
    })
    const controller = new TauriDeviceController(bridge)
    await controller.list()
    await expect(controller.command("lamp", { hsv: { hue: 240 } })).rejects.toMatchObject({ code: "DEVICE_ERROR" })
    await controller.command("lamp", { hsv: { value: 35 } })
    expect(bridge.command).toHaveBeenLastCalledWith({
      command: "device.hsv", payload: { deviceId: "lamp", hue: 120, saturation: 70, value: 35 },
    })
  })


})
