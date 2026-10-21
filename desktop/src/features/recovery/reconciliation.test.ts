import { describe, expect, it, vi } from 'vitest'
import { TauriDeviceController, type BridgeApi } from '../devices/TauriDeviceController'
import { publicDevice, deferred } from './testSupport'
import type { PublicDeviceStatus } from '../devices/publicDeviceMapper'
import type { ReadbackResult } from './contracts'

async function setup() {
  const bridge: BridgeApi = { list: vi.fn(async () => [publicDevice(), publicDevice('other')]), status: vi.fn(async (id) => publicDevice(id)), command: vi.fn(async (request) => publicDevice(request.payload.deviceId)) }
  const controller = new TauriDeviceController(bridge)
  await controller.list()
  return { bridge, controller }
}

describe('recovery reconciliation', () => {
  it.each<ReadbackResult>([{ status: 'FAILED' }, { status: 'SUPERSEDED' }, { status: 'SUCCEEDED' }])('invalidates history without inventing observation for $status', async (readback) => {
    const { controller, bridge } = await setup()
    const token = controller.beginRecoveryConfirmation('lamp')
    const stale = controller.reconcileRecovery(token, readback)!
    expect(stale.state).toMatchObject({ hsv: { hue: 120 }, quality: 'unknown', knowledge: { hsv: 'stale', power: 'stale', scene: 'unknown' } })
    expect(stale).not.toHaveProperty('address')
    expect(stale).not.toHaveProperty('protocolVersion')
    await expect(controller.command('lamp', { hsv: { hue: 10 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    await expect(controller.command('lamp', { enabled: false })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    expect(bridge.command).not.toHaveBeenCalled()
    await controller.command('other', { enabled: false })
    await controller.refresh('lamp')
    await controller.command('lamp', { hsv: { hue: 20 } })
  })
  it('accepts compatible observed readback and derives advisory eligibility from the loaded catalog', async () => {
    const { controller } = await setup()
    expect(controller.eligibility('lamp')).toEqual({ status: 'ELIGIBLE', protocolVersion: 3.5 })
    expect(controller.eligibility('missing')).toEqual({ status: 'UNKNOWN', protocolVersion: null })
    const token = controller.beginRecoveryConfirmation('lamp')
    const device = publicDevice(); device.state.hsv!.hue = 250
    expect(controller.reconcileRecovery(token, { status: 'SUCCEEDED', device })?.state.hsv.hue).toBe(250)
    await controller.command('lamp', { enabled: false })
    expect(controller.reconcileRecovery(token, { status: 'FAILED' })).toBeUndefined()
  })
  it('cannot restore a baseline from stale values even in a successful readback', async () => {
    const { controller } = await setup()
    const device = publicDevice()
    device.state.knowledge.hsv = 'stale'
    device.state.knowledge.power = 'stale'
    controller.reconcileRecovery(controller.beginRecoveryConfirmation('lamp'), { status: 'SUCCEEDED', device })
    await expect(controller.command('lamp', { hsv: { hue: 10 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    await expect(controller.command('lamp', { enabled: true })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
  })
  it('settles an older in-flight command stale and blocks HSV composition after adoption', async () => {
    const { controller, bridge } = await setup()
    const pending = deferred<PublicDeviceStatus>()
    bridge.command = vi.fn(() => pending.promise)
    const command = controller.command('lamp', { hsv: { hue: 200 } })
    const settled = expect(command).resolves.toMatchObject({ state: { knowledge: { hsv: 'stale' } } })
    controller.reconcileRecovery(controller.beginRecoveryConfirmation('lamp'), { status: 'FAILED' })
    await expect(controller.command('lamp', { hsv: { saturation: 10 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    pending.resolve(publicDevice())
    await settled
    await expect(controller.command('lamp', { enabled: false })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
  })
  it('applies authoritative recovery readback despite an in-flight command, then makes that command response stale', async () => {
    const { controller, bridge } = await setup()
    const token = controller.beginRecoveryConfirmation('lamp')
    const pending = deferred<PublicDeviceStatus>()
    bridge.command = vi.fn(() => pending.promise)
    const command = controller.command('lamp', { whiteBrightness: 80 })
    const recovered = publicDevice(); recovered.state.hsv!.hue = 301
    expect(controller.reconcileRecovery(token, { status: 'SUCCEEDED', device: recovered })?.state.hsv.hue).toBe(301)
    pending.resolve(publicDevice())
    const late = await command
    expect(late.state.knowledge.whiteBrightness).toBe('stale')
    await controller.command('lamp', { hsv: { hue: 20 } })
  })
  it.each([
    { name: 'whiteBrightness', patch: { whiteBrightness: 80 }, blockedPatch: { mode: 'white' }, stale: ['whiteBrightness', 'workMode'], unavailable: 'colorTemperature' },
    { name: 'colorTemperature', patch: { whiteTemperature: 80 }, blockedPatch: { mode: 'white' }, stale: ['colorTemperature', 'workMode'], unavailable: 'whiteBrightness' },
    { name: 'HSV', patch: { hsv: { hue: 200 } }, blockedPatch: { hsv: { saturation: 10 } }, stale: ['hsv', 'colorValue', 'workMode'] },
    { name: 'power', patch: { enabled: false }, blockedPatch: { enabled: true }, stale: ['power'] },
  ] as const)('invalidates only physical fields affected by a late $name command', async ({ patch, stale, blockedPatch, unavailable }) => {
    const { controller, bridge } = await setup()
    const pending = deferred<PublicDeviceStatus>()
    bridge.command = vi.fn(() => pending.promise)
    const token = controller.beginRecoveryConfirmation('lamp')
    const command = controller.command('lamp', patch)
    const recovered = publicDevice()
    recovered.state.workMode = 'white'
    recovered.state.whiteBrightnessPercent = 67
    recovered.state.colorTemperaturePercent = 33
    recovered.state.hsv = { hue: 240, saturation: 50, value: 40 }
    recovered.state.colorValuePercent = 40
    if (unavailable === 'colorTemperature') recovered.state.knowledge.colorTemperature = 'unknown'
    if (unavailable === 'whiteBrightness') recovered.state.knowledge.whiteBrightness = 'unknown'
    controller.reconcileRecovery(token, { status: 'SUCCEEDED', device: recovered })

    pending.resolve(publicDevice())
    const status = (await command).state.knowledge
    for (const field of stale) expect(status[field]).toBe('stale')
    const staleFields = new Set<string>(stale)
    for (const field of ['power', 'workMode', 'whiteBrightness', 'colorTemperature', 'hsv', 'colorValue'] as const) {
      if (field === unavailable) expect(status[field]).toBe('unknown')
      else if (!staleFields.has(field)) expect(status[field]).toBe('observed')
    }
    await expect(controller.command('lamp', blockedPatch)).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
  })
  it('invalidates command or refresh snapshots that completed after the checkpoint but before adoption', async () => {
    for (const operation of ['command', 'refresh']) {
      const { controller } = await setup()
      const token = controller.beginRecoveryConfirmation('lamp')
      if (operation === 'command') await controller.command('lamp', { enabled: false })
      else await controller.refresh('lamp')
      expect(controller.reconcileRecovery(token, { status: 'FAILED' })?.state.knowledge.power).toBe('stale')
      await expect(controller.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    }
  })
  it.each<ReadbackResult>([{ status: 'FAILED' }, { status: 'SUPERSEDED' }, { status: 'SUCCEEDED' }])('does not let a refresh in flight across %s restore a baseline', async (readback) => {
    const { controller, bridge } = await setup()
    const token = controller.beginRecoveryConfirmation('lamp')
    const pending = deferred<PublicDeviceStatus>()
    bridge.status = vi.fn(() => pending.promise)
    const refresh = controller.refresh('lamp')
    controller.reconcileRecovery(token, readback)
    pending.resolve(publicDevice())
    const result = await refresh
    expect(result.state.knowledge.power).toBe('stale')
    await expect(controller.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
  })
  it('discards an old refresh response after applying an authoritative recovery readback', async () => {
    const { controller, bridge } = await setup()
    const pending = deferred<PublicDeviceStatus>()
    bridge.status = vi.fn(() => pending.promise)
    const refresh = controller.refresh('lamp')
    const recovered = publicDevice()
    recovered.state.hsv = { hue: 312, saturation: 21, value: 43 }
    recovered.state.whiteBrightnessPercent = 76
    const token = controller.beginRecoveryConfirmation('lamp')
    controller.reconcileRecovery(token, { status: 'SUCCEEDED', device: recovered })
    pending.resolve(publicDevice())
    const result = await refresh
    expect(result.state.hsv.hue).toBe(312)
    expect(result.state.whiteBrightness).toBe(76)
    expect(result.state.knowledge.hsv).toBe('observed')
    await controller.command('lamp', { hsv: { saturation: 22 } })
  })
  it('keeps a pre-confirm refresh response non-authoritative after ADOPTED and permits a later fresh refresh', async () => {
    const { controller, bridge } = await setup()
    const pending = deferred<PublicDeviceStatus>()
    bridge.status = vi.fn(() => pending.promise)
    const refresh = controller.refresh('lamp')
    const token = controller.beginRecoveryConfirmation('lamp')
    controller.reconcileRecovery(token, { status: 'FAILED' })
    pending.resolve(publicDevice())
    expect((await refresh).state.knowledge.power).toBe('stale')
    await expect(controller.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    bridge.status = vi.fn(async () => publicDevice())
    expect((await controller.refresh('lamp')).state.knowledge.hsv).toBe('observed')
    await controller.command('lamp', { hsv: { hue: 20 } })
  })
  it('indeterminate creates the same causal barrier without treating adoption as failed', async () => {
    const { controller, bridge } = await setup()
    const token = controller.beginRecoveryConfirmation('lamp')
    const pending = deferred<PublicDeviceStatus>()
    bridge.status = vi.fn(() => pending.promise)
    const refresh = controller.refresh('lamp')
    controller.reconcileRecovery(token)
    pending.resolve(publicDevice())
    expect((await refresh).state.knowledge.power).toBe('stale')
    await expect(controller.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
  })
  it('keeps causal barriers independent per device', async () => {
    const { controller } = await setup()
    controller.reconcileRecovery(controller.beginRecoveryConfirmation('lamp'), { status: 'FAILED' })
    await expect(controller.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    await controller.command('other', { enabled: false })
  })
  it('does not let a pre-barrier command overwrite a command proven applied after the barrier', async () => {
    const { controller, bridge } = await setup()
    const old = deferred<PublicDeviceStatus>()
    const newer = deferred<PublicDeviceStatus>()
    bridge.command = vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(newer.promise).mockResolvedValue(publicDevice())
    const oldCommand = controller.command('lamp', { whiteBrightness: 20 })
    controller.reconcileRecovery(controller.beginRecoveryConfirmation('lamp'), { status: 'FAILED' })
    const newCommand = controller.command('lamp', { whiteBrightness: 90 })
    const latest = publicDevice(); latest.state.whiteBrightnessPercent = 90
    newer.resolve(latest)
    await newCommand
    old.resolve(publicDevice())
    expect((await oldCommand).state.whiteBrightness).toBe(90)
    expect((await controller.command('lamp', { mode: 'white' })).state.knowledge.whiteBrightness).toBe('observed')
  })
  it('accepts an earlier terminal recovery while a newer one is pending, then orders already-reconciled generations and catalogs', async () => {
    const { controller } = await setup()
    const old = controller.beginRecoveryConfirmation('lamp')
    const current = controller.beginRecoveryConfirmation('lamp')
    const stale = controller.reconcileRecovery(old, { status: 'SUCCEEDED', device: publicDevice() })
    expect(stale?.state.knowledge.power).toBe('observed')
    expect(stale?.state.enabled).toBe(true)
    const latest = publicDevice(); latest.state.hsv!.hue = 250
    expect(controller.reconcileRecovery(current, { status: 'SUCCEEDED', device: latest })?.state.hsv.hue).toBe(250)
    expect(controller.reconcileRecovery(old, { status: 'FAILED' })).toBeUndefined()
    await controller.command('lamp', { hsv: { saturation: 10 } })
    const previousCatalog = controller.beginRecoveryConfirmation('lamp')
    await controller.list()
    expect(controller.reconcileRecovery(previousCatalog, { status: 'FAILED' })).toBeUndefined()
  })
})

