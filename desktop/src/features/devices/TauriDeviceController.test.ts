import { describe, expect, it, vi } from 'vitest'
import { TauriDeviceController, type BridgeApi } from './TauriDeviceController'
import type { PublicDeviceStatus } from './publicDeviceMapper'

const device: PublicDeviceStatus = {
  deviceId: 'lamp', name: 'Desk', address: '127.0.0.1', protocolVersion: 3.3, capabilities: { power: true, whiteBrightness: true, colorValue: true, colorTemperature: true, scenes: false }, connection: 'online',
  state: { power: true, workMode: 'colour', whiteBrightnessPercent: 40, colorValuePercent: 60, colorTemperaturePercent: 50, hsv: { hue: 120, saturation: 70, value: 60 }, scene: null, quality: 'confirmed', knowledge: { power: 'observed', workMode: 'observed', whiteBrightness: 'observed', colorTemperature: 'observed', hsv: 'observed', colorValue: 'observed', scene: 'unknown' } },
}

function api(): BridgeApi { return { list: vi.fn(async () => [device]), status: vi.fn(async () => device), command: vi.fn(async () => device) } }

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise })
  return { promise, resolve, reject }
}

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
    const unknown: PublicDeviceStatus = { ...device, connection: "unknown", state: { ...device.state, power: null, workMode: null, whiteBrightnessPercent: null, colorValuePercent: null, colorTemperaturePercent: null, hsv: null, quality: "unknown", knowledge: { power: "unknown", workMode: "unknown", whiteBrightness: "unknown", colorTemperature: "unknown", hsv: "unknown", colorValue: "unknown", scene: "unknown" } } }
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
    const unknown: PublicDeviceStatus = { ...device, connection: "unknown", state: { ...device.state, power: null, workMode: null, whiteBrightnessPercent: null, colorValuePercent: null, colorTemperaturePercent: null, hsv: null, quality: "unknown", knowledge: { power: "unknown", workMode: "unknown", whiteBrightness: "unknown", colorTemperature: "unknown", hsv: "unknown", colorValue: "unknown", scene: "unknown" } } }
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

  it('applies a newer command readback when the earlier command confirms first', async () => {
    const first = deferred<PublicDeviceStatus>()
    const second = deferred<PublicDeviceStatus>()
    const bridge = api()
    bridge.command = vi.fn().mockResolvedValue(device).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const controller = new TauriDeviceController(bridge); await controller.list()
    const hue = controller.command('lamp', { hsv: { hue: 210 } })
    const saturation = controller.command('lamp', { hsv: { saturation: 25 } })

    first.resolve({ ...device, state: { ...device.state, hsv: { hue: 210, saturation: 70, value: 60 } } })
    await hue
    second.resolve({ ...device, state: { ...device.state, hsv: { hue: 210, saturation: 25, value: 60 } } })
    await saturation

    await controller.command('lamp', { hsv: { value: 30 } })
    expect(bridge.command).toHaveBeenNthCalledWith(3, { command: 'device.hsv', payload: { deviceId: 'lamp', hue: 210, saturation: 25, value: 30 } })
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


  it('allows independently observed power when HSV is unknown and blocks only RGB composition', async () => {
    const partial: PublicDeviceStatus = { ...device, state: { ...device.state, hsv: null, colorValuePercent: null, knowledge: { ...device.state.knowledge, hsv: 'unknown', colorValue: 'unknown' } } }
    const bridge = api(); bridge.list = vi.fn(async () => [partial]); bridge.command = vi.fn(async () => partial)
    const controller = new TauriDeviceController(bridge); await controller.list()
    await controller.command('lamp', { enabled: false })
    await expect(controller.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    expect(bridge.command).toHaveBeenCalledTimes(1)
  })

  it('refreshes only the requested device and blocks refresh while a write is pending', async () => {
    let resolveCommand!: (status: PublicDeviceStatus) => void
    const write = new Promise<PublicDeviceStatus>((resolve) => { resolveCommand = resolve })
    const bridge = api(); bridge.command = vi.fn(() => write)
    const controller = new TauriDeviceController(bridge); await controller.list()
    const pending = controller.command('lamp', { hsv: { hue: 200 } })
    await expect(controller.refresh('lamp')).rejects.toMatchObject({ code: 'COMMAND_CANCELED' })
    resolveCommand(device); await pending
    const refreshed = { ...device, state: { ...device.state, power: false } }
    bridge.status = vi.fn(async (id) => id === 'lamp' ? refreshed : device)
    await expect(controller.refresh('lamp')).resolves.toMatchObject({ state: { enabled: false } })
    expect(bridge.status).toHaveBeenCalledWith('lamp')
  })

  it('marks offline knowledge stale and recovers only after a successful manual refresh', async () => {
    const bridge = api()
    bridge.status = vi.fn().mockRejectedValueOnce({ code: 'DEVICE_OFFLINE' }).mockResolvedValueOnce(device)
    const controller = new TauriDeviceController(bridge); await controller.list()
    await expect(controller.refresh('lamp')).rejects.toMatchObject({ code: 'DEVICE_OFFLINE' })
    await expect(controller.command('lamp', { enabled: false })).rejects.toMatchObject({ code: 'DEVICE_OFFLINE' })
    await expect(controller.refresh('lamp')).resolves.toMatchObject({ connection: 'online' })
    await expect(controller.command('lamp', { enabled: false })).resolves.toMatchObject({})
  })

  it('keeps RGB available when power knowledge is unknown', async () => {
    const unknownPower: PublicDeviceStatus = { ...device, state: { ...device.state, power: null, knowledge: { ...device.state.knowledge, power: 'unknown' } } }
    const bridge = api(); bridge.list = vi.fn(async () => [unknownPower])
    const controller = new TauriDeviceController(bridge); await controller.list()
    await expect(controller.command('lamp', { enabled: false })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    await expect(controller.command('lamp', { hsv: { hue: 200 } })).resolves.toMatchObject({ deviceId: 'lamp' })
    expect(bridge.command).toHaveBeenCalledTimes(1)
  })

  it('does not let an old refresh timeout offline a device after a write readback', async () => {
    const status = deferred<PublicDeviceStatus>()
    const bridge = api(); bridge.status = vi.fn(() => status.promise)
    const controller = new TauriDeviceController(bridge); await controller.list()
    const refresh = controller.refresh('lamp')
    await controller.command('lamp', { enabled: false })
    status.reject({ code: 'TIMEOUT' })
    await expect(refresh).rejects.toMatchObject({ code: 'TIMEOUT' })
    await expect(controller.command('lamp', { enabled: true })).resolves.toMatchObject({ connection: 'online' })
  })

  it('does not let a late command timeout replace a newer confirmed command readback', async () => {
    const older = deferred<PublicDeviceStatus>()
    const bridge = api(); bridge.command = vi.fn().mockResolvedValue(device).mockReturnValueOnce(older.promise).mockResolvedValueOnce({ ...device, state: { ...device.state, power: false } })
    const controller = new TauriDeviceController(bridge); await controller.list()
    const first = controller.command('lamp', { enabled: false })
    await controller.command('lamp', { enabled: true })
    older.reject({ code: 'TIMEOUT' })
    await expect(first).rejects.toMatchObject({ code: 'TIMEOUT' })
    await expect(controller.command('lamp', { enabled: false })).resolves.toMatchObject({ connection: 'online' })
  })

  it('ignores an older failed refresh after a newer refresh has applied', async () => {
    const older = deferred<PublicDeviceStatus>()
    const newer = deferred<PublicDeviceStatus>()
    const bridge = api(); bridge.status = vi.fn().mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
    const controller = new TauriDeviceController(bridge); await controller.list()
    const first = controller.refresh('lamp')
    const second = controller.refresh('lamp')
    newer.resolve({ ...device, state: { ...device.state, power: false } })
    await expect(second).resolves.toMatchObject({ state: { enabled: false } })
    older.reject({ code: 'TIMEOUT' })
    await expect(first).rejects.toMatchObject({ code: 'TIMEOUT' })
    await expect(controller.command('lamp', { enabled: true })).resolves.toMatchObject({ connection: 'online' })
  })

  it('applies an older valid refresh when a newer refresh failed without a readback', async () => {
    const older = deferred<PublicDeviceStatus>()
    const newer = deferred<PublicDeviceStatus>()
    const bridge = api(); bridge.status = vi.fn().mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
    const controller = new TauriDeviceController(bridge); await controller.list()
    const first = controller.refresh('lamp')
    const second = controller.refresh('lamp')
    newer.reject({ code: 'TIMEOUT' })
    await expect(second).rejects.toMatchObject({ code: 'TIMEOUT' })
    older.resolve({ ...device, state: { ...device.state, power: false } })
    await expect(first).resolves.toMatchObject({ connection: 'online', state: { enabled: false } })
    await expect(controller.command('lamp', { enabled: true })).resolves.toMatchObject({ connection: 'online' })
  })

  it('keeps a current refresh timeout offline and isolated to its device', async () => {
    const strip: PublicDeviceStatus = { ...device, deviceId: 'strip', name: 'Strip', state: { ...device.state, hsv: { hue: 10, saturation: 40, value: 50 } } }
    const bridge: BridgeApi = {
      list: vi.fn(async () => [device, strip]),
      status: vi.fn(async (deviceId) => { if (deviceId === 'lamp') throw { code: 'TIMEOUT' }; return strip }),
      command: vi.fn(async () => strip),
    }
    const controller = new TauriDeviceController(bridge); await controller.list()
    await expect(controller.refresh('lamp')).rejects.toMatchObject({ code: 'TIMEOUT' })
    await expect(controller.command('lamp', { enabled: false })).rejects.toMatchObject({ code: 'DEVICE_OFFLINE' })
    await expect(controller.command('strip', { enabled: false })).resolves.toMatchObject({ connection: 'online' })
  })

  it('applies an older valid readback when a later command failed without confirming its intent', async () => {
    const earlier = deferred<PublicDeviceStatus>()
    const bridge = api()
    bridge.command = vi.fn().mockReturnValueOnce(earlier.promise).mockRejectedValueOnce({ code: 'TIMEOUT' }).mockResolvedValueOnce({
      ...device, state: { ...device.state, hsv: { hue: 210, saturation: 70, value: 30 }, colorValuePercent: 30 },
    })
    const controller = new TauriDeviceController(bridge); await controller.list()
    const first = controller.command('lamp', { hsv: { hue: 210 } })
    await expect(controller.command('lamp', { hsv: { saturation: 25 } })).rejects.toMatchObject({ code: 'TIMEOUT' })
    earlier.resolve({ ...device, state: { ...device.state, hsv: { hue: 222, saturation: 70, value: 60 } } })
    await expect(first).resolves.toMatchObject({ state: { hsv: { hue: 222, saturation: 70, value: 60 } } })
    await controller.command('lamp', { hsv: { value: 30 } })
    expect(bridge.command).toHaveBeenNthCalledWith(3, { command: 'device.hsv', payload: { deviceId: 'lamp', hue: 222, saturation: 70, value: 30 } })
  })

})
