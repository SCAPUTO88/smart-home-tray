import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { DeviceController, LightingDevice, LightingPatch, OperationScenario } from './types'
import { OperationError } from './types'
import { createMockDevices } from '../../mock/MockDeviceController'
import { useLightingSession } from './useLightingSession'

interface DeferredCommand {
  deviceId: string
  patch: LightingPatch
  resolve(device: LightingDevice): void
  reject(error: OperationError): void
}

function createControlledController(devices = createMockDevices()) {
  const pending: DeferredCommand[] = []
  const controller: DeviceController = {
    list: async () => devices.map(copyDevice),
    refresh: async (deviceId) => copyDevice(devices.find((item) => item.deviceId === deviceId)!),
    command: (deviceId, patch, _scenario?: OperationScenario) => new Promise((resolve, reject) => {
      pending.push({ deviceId, patch, resolve, reject })
    }),
  }
  return { controller, pending, devices }
}

function copyDevice(device: LightingDevice): LightingDevice {
  return { ...device, state: { ...device.state, hsv: { ...device.state.hsv } } }
}

function readback(devices: LightingDevice[], deviceId: string, patch: LightingPatch): LightingDevice {
  const device = copyDevice(devices.find((item) => item.deviceId === deviceId)!)
  device.state = {
    ...device.state,
    ...patch,
    hsv: patch.hsv ? { ...device.state.hsv, ...patch.hsv } : device.state.hsv,
    quality: device.state.quality,
  }
  return device
}

async function startSession(devices?: LightingDevice[]) {
  const setup = createControlledController(devices)
  const session = renderHook(() => useLightingSession(setup.controller))
  await waitFor(() => expect(session.result.current.selectedView).not.toBeNull())
  return { ...setup, ...session }
}

function issue(result: { current: ReturnType<typeof useLightingSession> }, deviceId: string, patch: LightingPatch) {
  act(() => result.current.issue(deviceId, patch, 'success'))
}

function confirm(pending: DeferredCommand[], index: number, devices: LightingDevice[]) {
  pending[index].resolve(readback(devices, pending[index].deviceId, pending[index].patch))
}

describe('lighting session field reconciliation', () => {
  it('confirms hue and power independently when power returns first', async () => {
    const { result, pending, devices } = await startSession()
    issue(result, 'mock-desk-lamp', { hsv: { hue: 205 } })
    issue(result, 'mock-desk-lamp', { enabled: false })

    await act(async () => { confirm(pending, 1, devices) })
    await act(async () => { confirm(pending, 0, devices) })

    expect(result.current.selectedView?.confirmed).toMatchObject({ enabled: false, hsv: { hue: 205, saturation: 77 } })
    expect(result.current.selectedView?.preview).toMatchObject({ enabled: false, hsv: { hue: 205 } })
  })

  it('merges hue and saturation from separate requests without stale nested HSV fields', async () => {
    const { result, pending, devices } = await startSession()
    issue(result, 'mock-desk-lamp', { hsv: { hue: 205 } })
    issue(result, 'mock-desk-lamp', { hsv: { saturation: 42 } })

    await act(async () => { confirm(pending, 1, devices) })
    await act(async () => { confirm(pending, 0, devices) })

    expect(result.current.selectedView?.confirmed.hsv).toMatchObject({ hue: 205, saturation: 42, value: 82 })
  })

  it('preserves a pending RGB value when another HSV channel confirms first', async () => {
    const { result, pending, devices } = await startSession()
    issue(result, 'mock-desk-lamp', { hsv: { hue: 205, saturation: 42, value: 82 } })
    issue(result, 'mock-desk-lamp', { hsv: { value: 31 } })

    await act(async () => { confirm(pending, 0, devices) })
    await act(async () => { confirm(pending, 1, devices) })

    expect(result.current.selectedView?.confirmed.hsv).toEqual({ hue: 205, saturation: 42, value: 31 })
  })

  it('keeps the white mode request and its illumination value as independent fields', async () => {
    const { result, pending, devices } = await startSession()
    issue(result, 'mock-desk-lamp', { mode: 'white' })
    issue(result, 'mock-desk-lamp', { whiteBrightness: 21 })

    await act(async () => { confirm(pending, 1, devices) })
    await act(async () => { confirm(pending, 0, devices) })

    expect(result.current.selectedView?.confirmed).toMatchObject({ mode: 'white', whiteBrightness: 21 })
  })

  it('keeps pending state and responses isolated while switching devices', async () => {
    const { result, pending, devices } = await startSession()
    issue(result, 'mock-desk-lamp', { hsv: { hue: 205 } })
    act(() => result.current.selectDevice('mock-led-strip'))
    issue(result, 'mock-led-strip', { hsv: { hue: 300 } })
    await act(async () => { confirm(pending, 0, devices) })

    expect(result.current.selectedView?.preview.hsv.hue).toBe(300)
    await act(async () => { confirm(pending, 1, devices) })
    act(() => result.current.selectDevice('mock-desk-lamp'))
    expect(result.current.selectedView?.confirmed.hsv.hue).toBe(205)
    act(() => result.current.selectDevice('mock-led-strip'))
    expect(result.current.selectedView?.confirmed.hsv.hue).toBe(300)
  })
})


  it('refreshes a single device without resetting the other device view', async () => {
    const { result } = await startSession()
    act(() => result.current.selectDevice('mock-led-strip'))
    await act(async () => { await result.current.refreshDevice('mock-led-strip') })
    expect(result.current.selectedView?.confirmed.hsv).toEqual({ hue: 268, saturation: 88, value: 70 })
    act(() => result.current.selectDevice('mock-desk-lamp'))
    expect(result.current.selectedView?.confirmed.hsv).toEqual({ hue: 194, saturation: 77, value: 82 })
  })

  it('does not start refresh while a write is pending', async () => {
    const { result, pending } = await startSession()
    issue(result, 'mock-desk-lamp', { hsv: { hue: 210 } })
    await act(async () => { await result.current.refreshDevice('mock-desk-lamp') })
    expect(result.current.refreshing['mock-desk-lamp']).toBeUndefined()
    expect(pending).toHaveLength(1)
  })

describe('lighting session failure policy', () => {
  it.each([
    ['cancellation', 'COMMAND_CANCELED', 'canceled'],
    ['device error', 'DEVICE_ERROR', 'error'],
  ] as const)('restores confirmed preview after %s', async (_label, code, status) => {
    const { result, pending } = await startSession()
    issue(result, 'mock-desk-lamp', { hsv: { hue: 205 } })
    expect(result.current.selectedView?.preview.hsv.hue).toBe(205)

    await act(async () => { pending[0].reject(new OperationError(code)) })

    expect(result.current.selectedView).toMatchObject({ status, requested: { hsv: { hue: 205 } }, preview: { hsv: { hue: 194 }, quality: 'confirmed' }, confirmed: { hsv: { hue: 194 } } })
  })

  it('preserves the last known values and marks offline without confirming the request', async () => {
    const { result, pending, devices } = await startSession()
    issue(result, 'mock-desk-lamp', { hsv: { hue: 205 } })
    issue(result, 'mock-desk-lamp', { enabled: false })
    await act(async () => { pending[1].reject(new OperationError('DEVICE_OFFLINE')) })
    await act(async () => { confirm(pending, 0, devices) })

    expect(result.current.selectedDevice?.connection).toBe('offline')
    expect(result.current.selectedView).toMatchObject({ status: 'offline', preview: { enabled: true, hsv: { hue: 194 }, quality: 'offline' }, confirmed: { enabled: true, hsv: { hue: 194 }, quality: 'offline' } })
  })

  it('does not let an older error replace a newer pending HSV intention', async () => {
    const { result, pending } = await startSession()
    issue(result, 'mock-desk-lamp', { hsv: { hue: 205 } })
    issue(result, 'mock-desk-lamp', { hsv: { hue: 230 } })
    await act(async () => { pending[0].reject(new OperationError('DEVICE_ERROR')) })

    expect(result.current.selectedView).toMatchObject({ status: 'pending', preview: { hsv: { hue: 230 } }, error: null })
  })

  it('restores the newest operation feedback after an older independent request settles', async () => {
    const { result, pending, devices } = await startSession()
    issue(result, 'mock-desk-lamp', { hsv: { hue: 205 } })
    issue(result, 'mock-desk-lamp', { enabled: false })
    await act(async () => { confirm(pending, 1, devices) })
    expect(result.current.selectedView?.status).toBe('pending')
    await act(async () => { pending[0].reject(new OperationError('DEVICE_ERROR')) })

    expect(result.current.selectedView).toMatchObject({ status: 'confirmed', error: null, confirmed: { enabled: false, hsv: { hue: 194 } }, preview: { enabled: false, hsv: { hue: 194 } } })
  })

  it('does not promote a successful response with unknown quality to confirmed quality', async () => {
    const devices = createMockDevices().map((device) => ({ ...device, state: { ...device.state, quality: 'unknown' as const } }))
    const { result, pending } = await startSession(devices)
    issue(result, 'mock-desk-lamp', { hsv: { hue: 205 } })
    await act(async () => { confirm(pending, 0, devices) })

    expect(result.current.selectedView?.confirmed.quality).toBe('unknown')
  })
})
