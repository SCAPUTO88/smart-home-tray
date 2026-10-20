import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useLightingSession } from '../devices/useLightingSession'
import { TauriDeviceController, type BridgeApi } from '../devices/TauriDeviceController'
import type { PublicDeviceStatus } from '../devices/publicDeviceMapper'
import type { ConfirmOutcome, ManualRecoveryController } from './ManualRecoveryController'
import type { ReadbackResult } from './contracts'
import { publicDevice, proposal, deferred } from './testSupport'

async function setup() {
  const confirm = deferred<ConfirmOutcome>()
  const bridge: BridgeApi = { list: vi.fn(async () => [publicDevice(), publicDevice('other')]), status: vi.fn(async (id) => publicDevice(id)), command: vi.fn(async () => publicDevice()) }
  const lighting = new TauriDeviceController(bridge)
  const controller: ManualRecoveryController = {
    prepare: vi.fn(async () => ({ kind: 'terminal' as const, result: proposal })),
    confirm: vi.fn(() => confirm.promise),
  }
  const recovery = { controller, reconciliation: lighting }
  const hook = renderHook(() => useLightingSession(lighting, recovery))
  await waitFor(() => expect(hook.result.current.selectedDevice).not.toBeNull())
  await act(async () => { await hook.result.current.prepareRecovery('lamp') })
  return { ...hook, confirm, bridge, lighting, recovery, controller }
}
function adopted(readback: ReadbackResult): ConfirmOutcome {
  return { kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback } }
}

describe('lighting recovery session', () => {
  it.each<ReadbackResult>([{ status: 'SUCCEEDED', device: publicDevice() }, { status: 'FAILED' }, { status: 'SUPERSEDED' }, { status: 'SUCCEEDED' }])('reconciles ADOPTED/$status by proposal Device ID despite selection change', async (readback) => {
    const s = await setup()
    let result!: Promise<ConfirmOutcome>
    act(() => { result = s.result.current.confirmRecovery(proposal.proposalId); s.result.current.selectDevice('other') })
    await act(async () => { s.confirm.resolve(adopted(readback)); expect(await result).toMatchObject({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' } } }) })
    expect(s.result.current.selectedDeviceId).toBe('other')
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('observed')
    const lamp = s.result.current.devices.find((device) => device.deviceId === 'lamp')!
    expect(lamp.state.knowledge.power).toBe(readback.status === 'SUCCEEDED' && readback.device ? 'observed' : 'stale')
    expect(lamp).not.toHaveProperty('address')
    expect(lamp).not.toHaveProperty('protocolVersion')
    expect(JSON.stringify(lamp)).not.toContain('proposalId')
    expect(await s.result.current.confirmRecovery(proposal.proposalId)).toMatchObject({ kind: 'rejected' })
    expect(s.controller.confirm).toHaveBeenCalledTimes(1)
  })
  it('preserves a newer command intent and lets its later observation win', async () => {
    const s = await setup()
    const pending = deferred<PublicDeviceStatus>()
    s.bridge.command = vi.fn(() => pending.promise)
    let confirmation!: Promise<ConfirmOutcome>
    act(() => {
      confirmation = s.result.current.confirmRecovery(proposal.proposalId)
      s.result.current.issue('lamp', { whiteBrightness: 80 }, 'success')
    })
    await act(async () => { s.confirm.resolve(adopted({ status: 'SUCCEEDED', device: publicDevice() })); await confirmation })
    expect(s.result.current.selectedView?.preview.whiteBrightness).toBe(80)
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('stale')
    expect(s.result.current.selectedView?.pendingOperations).toHaveLength(1)
    const readback = publicDevice(); readback.state.whiteBrightnessPercent = 80
    await act(async () => { pending.resolve(readback) })
    expect(s.result.current.selectedView?.confirmed.whiteBrightness).toBe(80)
    expect(s.result.current.selectedView?.confirmed.knowledge.whiteBrightness).toBe('observed')
    expect(s.result.current.selectedView?.pendingOperations).toHaveLength(0)
  })
  it('settles an older command without resurrecting the invalid baseline', async () => {
    const s = await setup()
    const pending = deferred<PublicDeviceStatus>()
    s.bridge.command = vi.fn(() => pending.promise)
    let confirmation!: Promise<ConfirmOutcome>
    act(() => { s.result.current.issue('lamp', { hsv: { hue: 220 } }, 'success'); confirmation = s.result.current.confirmRecovery(proposal.proposalId) })
    await act(async () => { s.confirm.resolve(adopted({ status: 'FAILED' })); await confirmation })
    expect(s.result.current.selectedView?.preview.hsv.hue).toBe(220)
    await act(async () => { pending.resolve(publicDevice()) })
    expect(s.result.current.selectedView?.confirmed.knowledge.hsv).toBe('stale')
    expect(s.result.current.selectedView?.pendingOperations).toHaveLength(0)
  })
  it.each([false, true])('handles refresh racing with recovery (newer=%s)', async (newer) => {
    const s = await setup()
    const pending = deferred<PublicDeviceStatus>()
    s.bridge.status = vi.fn(() => pending.promise)
    let confirmation!: Promise<ConfirmOutcome>
    let refresh!: Promise<void>
    act(() => {
      if (newer) confirmation = s.result.current.confirmRecovery(proposal.proposalId)
      refresh = s.result.current.refreshDevice('lamp')
      if (!newer) confirmation = s.result.current.confirmRecovery(proposal.proposalId)
    })
    await act(async () => { s.confirm.resolve(adopted({ status: 'FAILED' })); await confirmation })
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('stale')
    await act(async () => { pending.resolve(publicDevice()); await refresh })
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe(newer ? 'observed' : 'stale')
    expect(s.result.current.refreshing.lamp).toBe(false)
  })
  it('does not overwrite a newer refresh already applied before late recovery readback', async () => {
    const s = await setup()
    const newer = publicDevice(); newer.state.hsv!.hue = 310
    s.bridge.status = vi.fn(async () => newer)
    let confirmation!: Promise<ConfirmOutcome>
    act(() => { confirmation = s.result.current.confirmRecovery(proposal.proposalId) })
    await act(async () => { await s.result.current.refreshDevice('lamp') })
    await act(async () => { s.confirm.resolve(adopted({ status: 'SUCCEEDED', device: publicDevice() })); await confirmation })
    expect(s.result.current.selectedView?.confirmed.hsv.hue).toBe(310)
  })
  it('reports ambiguous transport as indeterminate, invalidates baseline and never retries', async () => {
    const s = await setup()
    let confirmation!: Promise<ConfirmOutcome>
    act(() => { confirmation = s.result.current.confirmRecovery(proposal.proposalId) })
    await act(async () => { s.confirm.reject({ code: 'TIMEOUT', message: 'private details' }); expect(await confirmation).toEqual({ kind: 'indeterminate', code: 'TIMEOUT' }) })
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('stale')
    expect(s.controller.confirm).toHaveBeenCalledTimes(1)
    expect(await s.result.current.confirmRecovery(proposal.proposalId)).toMatchObject({ kind: 'rejected' })
  })
  it('reconciles caches after unmount without treating it as backend cancellation', async () => {
    const s = await setup()
    let confirmation!: Promise<ConfirmOutcome>
    act(() => { confirmation = s.result.current.confirmRecovery(proposal.proposalId) })
    s.unmount()
    s.confirm.resolve(adopted({ status: 'FAILED' }))
    expect(await confirmation).toMatchObject({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' } } })
    await expect(s.lighting.command('lamp', { enabled: false })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
  })
  it('does not invalidate a new catalog/session when a previous session completes late', async () => {
    const s = await setup()
    let confirmation!: Promise<ConfirmOutcome>
    act(() => { confirmation = s.result.current.confirmRecovery(proposal.proposalId) })
    s.unmount()
    const next = renderHook(() => useLightingSession(s.lighting, s.recovery))
    await waitFor(() => expect(next.result.current.selectedDevice).not.toBeNull())
    await act(async () => { s.confirm.resolve(adopted({ status: 'FAILED' })); await confirmation })
    expect(next.result.current.selectedView?.confirmed.knowledge.power).toBe('observed')
    await s.lighting.command('lamp', { enabled: false })
    next.unmount()
  })
})

