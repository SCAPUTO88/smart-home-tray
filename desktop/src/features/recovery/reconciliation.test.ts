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
  it('rejects an older in-flight command and its pending HSV baseline after adoption', async () => {
    const { controller, bridge } = await setup()
    const pending = deferred<PublicDeviceStatus>()
    bridge.command = vi.fn(() => pending.promise)
    const command = controller.command('lamp', { hsv: { hue: 200 } })
    const rejected = expect(command).rejects.toMatchObject({ code: 'COMMAND_CANCELED' })
    controller.reconcileRecovery(controller.beginRecoveryConfirmation('lamp'), { status: 'FAILED' })
    await expect(controller.command('lamp', { hsv: { saturation: 10 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    pending.resolve(publicDevice())
    await rejected
    await expect(controller.command('lamp', { enabled: false })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
  })
  it('preserves a newer pending command and discards recovery readback', async () => {
    const { controller, bridge } = await setup()
    const token = controller.beginRecoveryConfirmation('lamp')
    const pending = deferred<PublicDeviceStatus>()
    bridge.command = vi.fn(() => pending.promise)
    const command = controller.command('lamp', { whiteBrightness: 80 })
    expect(controller.reconcileRecovery(token, { status: 'SUCCEEDED', device: publicDevice() })?.state.knowledge.power).toBe('stale')
    pending.resolve(publicDevice())
    await command
    await controller.command('lamp', { enabled: false })
  })
  it('preserves snapshots already applied by newer commands or refreshes', async () => {
    for (const operation of ['command', 'refresh']) {
      const { controller } = await setup()
      const token = controller.beginRecoveryConfirmation('lamp')
      if (operation === 'command') await controller.command('lamp', { enabled: false })
      else await controller.refresh('lamp')
      expect(controller.reconcileRecovery(token, { status: 'FAILED' })).toBeUndefined()
      await controller.command('lamp', { enabled: true })
    }
  })
  it('rejects refresh started before capture but lets a newer pending refresh complete', async () => {
    for (const newer of [false, true]) {
      const { controller, bridge } = await setup()
      const pending = deferred<PublicDeviceStatus>()
      bridge.status = vi.fn(() => pending.promise)
      const before = newer ? controller.beginRecoveryConfirmation('lamp') : undefined
      const refresh = controller.refresh('lamp')
      const checked = newer ? expect(refresh).resolves.toMatchObject({ deviceId: 'lamp' }) : expect(refresh).rejects.toMatchObject({ code: 'COMMAND_CANCELED' })
      controller.reconcileRecovery(before ?? controller.beginRecoveryConfirmation('lamp'), { status: 'FAILED' })
      pending.resolve(publicDevice())
      await checked
    }
  })
  it('invalidates late adoption without applying its readback, and rejects mismatched Device ID and previous catalog generation', async () => {
    const { controller } = await setup()
    const old = controller.beginRecoveryConfirmation('lamp')
    const current = controller.beginRecoveryConfirmation('lamp')
    const stale = controller.reconcileRecovery(old, { status: 'SUCCEEDED', device: publicDevice() })
    expect(stale?.state.knowledge.power).toBe('stale')
    expect(stale?.state.enabled).toBe(true)
    expect(controller.reconcileRecovery(current, { status: 'SUCCEEDED', device: publicDevice('other') })).toBeUndefined()
    const fresh = controller.beginRecoveryConfirmation('lamp')
    expect(controller.reconcileRecovery(fresh, { status: 'SUCCEEDED', device: publicDevice('other') })?.state.knowledge.power).toBe('stale')
    const previousCatalog = controller.beginRecoveryConfirmation('lamp')
    await controller.list()
    expect(controller.reconcileRecovery(previousCatalog, { status: 'FAILED' })).toBeUndefined()
  })
})

