import { describe, expect, it, vi } from 'vitest'
import { createMockDeviceController } from './MockDeviceController'

describe('mock lighting catalog', () => {
  it('starts with two synthetic devices and different lighting capabilities', async () => {
    const controller = createMockDeviceController()
    const devices = await controller.list()

    expect(devices.map(({ deviceId }) => deviceId)).toEqual(['mock-desk-lamp', 'mock-led-strip'])
    expect(devices[0].capabilities).toEqual({ power: true, rgb: true, white: true, temperature: true })
    expect(devices[1].capabilities).toEqual({ power: true, rgb: true, white: false, temperature: false })
    expect(devices[0].connection).toBe('online')
  })
})

describe('mock lighting commands', () => {
  it('confirms a command asynchronously without changing catalog state before completion', async () => {
    const controller = createMockDeviceController({ delayMs: 25 })
    const initial = (await controller.list())[0]
    const pending = controller.command(initial.deviceId, { hsv: { hue: 180, saturation: 75, value: 60 } })

    expect((await controller.list())[0].state.hsv.hue).toBe(initial.state.hsv.hue)
    await expect(pending).resolves.toMatchObject({ state: { hsv: { hue: 180, saturation: 75, value: 60 } } })
  })

  it('supports deterministic cancellation, offline and error scenarios', async () => {
    const controller = createMockDeviceController({ delayMs: 0 })

    await expect(controller.command('mock-desk-lamp', { enabled: false }, 'canceled')).rejects.toMatchObject({ code: 'COMMAND_CANCELED' })
    await expect(controller.command('mock-desk-lamp', { enabled: false }, 'error')).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    await expect(controller.command('mock-desk-lamp', { enabled: false }, 'offline')).rejects.toMatchObject({ code: 'DEVICE_OFFLINE' })
  })

  it('rejects white controls on the RGB strip', async () => {
    const controller = createMockDeviceController({ delayMs: 0 })

    await expect(controller.command('mock-led-strip', { whiteBrightness: 40 })).rejects.toMatchObject({ code: 'UNSUPPORTED_CAPABILITY' })
  })

  it('uses a deterministic delay override for the delayed-operation scenario', async () => {
    vi.useFakeTimers()
    const controller = createMockDeviceController({ delayMs: 0, delayScenarioMs: 12 })
    let settled = false
    const operation = controller.command('mock-desk-lamp', { enabled: false }, 'delay').finally(() => { settled = true })

    await vi.advanceTimersByTimeAsync(12)
    const settledAtTarget = settled
    await vi.advanceTimersByTimeAsync(2000)
    await operation
    vi.useRealTimers()
    expect(settledAtTarget).toBe(true)
  })

  it('uses no HTTP transport for simulated commands', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const controller = createMockDeviceController({ delayMs: 0 })

    await controller.command('mock-desk-lamp', { enabled: false })

    expect(fetchSpy).not.toHaveBeenCalled()
    fetchSpy.mockRestore()
  })
})
