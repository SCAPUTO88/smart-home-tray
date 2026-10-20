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
    if (readback.status === 'SUCCEEDED' && readback.device) await s.lighting.command('lamp', { hsv: { saturation: 11 } })
    else await expect(s.lighting.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
    expect(await s.result.current.confirmRecovery(proposal.proposalId)).toMatchObject({ kind: 'rejected' })
    expect(s.controller.confirm).toHaveBeenCalledTimes(1)
  })
  it('preserves an in-flight intent, applies recovery readback, then makes the older command response stale', async () => {
    const s = await setup()
    const pending = deferred<PublicDeviceStatus>()
    s.bridge.command = vi.fn(() => pending.promise)
    let confirmation!: Promise<ConfirmOutcome>
    act(() => {
      confirmation = s.result.current.confirmRecovery(proposal.proposalId)
      s.result.current.issue('lamp', { hsv: { hue: 80 } }, 'success')
    })
    await act(async () => { s.confirm.resolve(adopted({ status: 'SUCCEEDED', device: publicDevice() })); await confirmation })
    expect(s.result.current.selectedView?.preview.hsv.hue).toBe(80)
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('observed')
    expect(s.result.current.selectedView?.pendingOperations).toHaveLength(1)
    const readback = publicDevice(); readback.state.hsv!.hue = 80
    await act(async () => { pending.resolve(readback) })
    expect(s.result.current.selectedView?.confirmed.knowledge.hsv).toBe('stale')
    expect(s.result.current.selectedView?.pendingOperations).toHaveLength(0)
    await expect(s.lighting.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
  })
  it.each([
    { name: 'whiteBrightness', patch: { whiteBrightness: 81 }, field: 'whiteBrightness' as const },
    { name: 'colorTemperature', patch: { whiteTemperature: 81 }, field: 'colorTemperature' as const },
    { name: 'HSV', patch: { hsv: { hue: 81 } }, field: 'hsv' as const },
  ])('projects $name command side effects as stale after its late result', async ({ patch, field }) => {
    const s = await setup()
    const pending = deferred<PublicDeviceStatus>()
    s.bridge.command = vi.fn(() => pending.promise)
    let confirmation!: Promise<ConfirmOutcome>
    act(() => { confirmation = s.result.current.confirmRecovery(proposal.proposalId); s.result.current.issue('lamp', patch, 'success') })
    const recovered = publicDevice()
    recovered.state.workMode = 'white'
    recovered.state.hsv = { hue: 242, saturation: 52, value: 42 }
    await act(async () => { s.confirm.resolve(adopted({ status: 'SUCCEEDED', device: recovered })); await confirmation })
    expect(s.result.current.selectedView?.confirmed.knowledge.workMode).toBe('observed')
    await act(async () => { pending.resolve(publicDevice()) })
    expect(s.result.current.selectedView?.confirmed.knowledge[field]).toBe('stale')
    expect(s.result.current.selectedView?.confirmed.knowledge.workMode).toBe('stale')
    expect(s.result.current.selectedView?.preview.knowledge.workMode).toBe('stale')
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
  it.each([false, true])('keeps refreshes started before ADOPTED non-authoritative (confirmation first=%s)', async (confirmationFirst) => {
    const s = await setup()
    const pending = deferred<PublicDeviceStatus>()
    s.bridge.status = vi.fn(() => pending.promise)
    let confirmation!: Promise<ConfirmOutcome>
    let refresh!: Promise<void>
    act(() => {
      if (confirmationFirst) confirmation = s.result.current.confirmRecovery(proposal.proposalId)
      refresh = s.result.current.refreshDevice('lamp')
      if (!confirmationFirst) confirmation = s.result.current.confirmRecovery(proposal.proposalId)
    })
    await act(async () => { s.confirm.resolve(adopted({ status: 'FAILED' })); await confirmation })
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('stale')
    await act(async () => { pending.resolve(publicDevice()); await refresh })
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('stale')
    expect(s.result.current.refreshing.lamp).toBe(false)
  })
  it('invalidates a command that settles before ADOPTED even though its request revision advanced', async () => {
    const s = await setup()
    let confirmation!: Promise<ConfirmOutcome>
    act(() => { confirmation = s.result.current.confirmRecovery(proposal.proposalId) })
    await act(async () => { s.result.current.issue('lamp', { enabled: false }, 'success') })
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('observed')
    await act(async () => { s.confirm.resolve(adopted({ status: 'FAILED' })); await confirmation })
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('stale')
    await expect(s.lighting.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
  })
  it('invalidates a command issued before confirm even when it settles before ADOPTED', async () => {
    const s = await setup()
    let confirmation!: Promise<ConfirmOutcome>
    act(() => { s.result.current.issue('lamp', { enabled: false }, 'success'); confirmation = s.result.current.confirmRecovery(proposal.proposalId) })
    await waitFor(() => expect(s.result.current.selectedView?.pendingOperations).toHaveLength(0))
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('observed')
    await act(async () => { s.confirm.resolve(adopted({ status: 'FAILED' })); await confirmation })
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('stale')
    expect(s.result.current.selectedView?.requested?.enabled).toBe(false)
    await expect(s.lighting.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
  })
  it('does not restore baseline from a command started during confirm and resolved after ADOPTED', async () => {
    const s = await setup()
    const pending = deferred<PublicDeviceStatus>()
    s.bridge.command = vi.fn(() => pending.promise)
    let confirmation!: Promise<ConfirmOutcome>
    act(() => { confirmation = s.result.current.confirmRecovery(proposal.proposalId); s.result.current.issue('lamp', { whiteBrightness: 81 }, 'success') })
    await act(async () => { s.confirm.resolve(adopted({ status: 'FAILED' })); await confirmation })
    expect(s.result.current.selectedView?.pendingOperations).toHaveLength(1)
    await act(async () => { pending.resolve(publicDevice()) })
    expect(s.result.current.selectedView?.pendingOperations).toHaveLength(0)
    expect(s.result.current.selectedView?.confirmed.knowledge.whiteBrightness).toBe('stale')
    expect(s.result.current.selectedView?.preview.whiteBrightness).toBe(s.result.current.selectedView?.confirmed.whiteBrightness)
    await expect(s.lighting.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
  })
  it('accepts a refresh issued after reconciliation as new evidence', async () => {
    const s = await setup()
    let confirmation!: Promise<ConfirmOutcome>
    act(() => { confirmation = s.result.current.confirmRecovery(proposal.proposalId) })
    await act(async () => { s.confirm.resolve(adopted({ status: 'FAILED' })); await confirmation })
    s.bridge.status = vi.fn(async () => publicDevice())
    await act(async () => { await s.result.current.refreshDevice('lamp') })
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('observed')
    await s.lighting.command('lamp', { hsv: { hue: 21 } })
  })
  it('uses recovery readback after an earlier refresh completed during confirmation', async () => {
    const s = await setup()
    const newer = publicDevice(); newer.state.hsv!.hue = 310
    s.bridge.status = vi.fn(async () => newer)
    let confirmation!: Promise<ConfirmOutcome>
    act(() => { confirmation = s.result.current.confirmRecovery(proposal.proposalId) })
    await act(async () => { await s.result.current.refreshDevice('lamp') })
    await act(async () => { s.confirm.resolve(adopted({ status: 'SUCCEEDED', device: publicDevice() })); await confirmation })
    expect(s.result.current.selectedView?.confirmed.hsv.hue).toBe(120)
  })
  it('discards a refresh response that arrives after the authoritative recovery readback', async () => {
    const s = await setup()
    const oldRefresh = deferred<PublicDeviceStatus>()
    s.bridge.status = vi.fn(() => oldRefresh.promise)
    let confirmation!: Promise<ConfirmOutcome>
    let refresh!: Promise<void>
    act(() => { refresh = s.result.current.refreshDevice('lamp'); confirmation = s.result.current.confirmRecovery(proposal.proposalId) })
    const recovered = publicDevice()
    recovered.state.hsv = { hue: 316, saturation: 29, value: 46 }
    recovered.state.whiteBrightnessPercent = 73
    await act(async () => { s.confirm.resolve(adopted({ status: 'SUCCEEDED', device: recovered })); await confirmation })
    expect(s.result.current.selectedView?.confirmed.hsv.hue).toBe(316)
    oldRefresh.resolve(publicDevice())
    await act(async () => { await refresh })
    expect(s.result.current.selectedView?.confirmed.hsv.hue).toBe(316)
    expect(s.result.current.selectedView?.confirmed.whiteBrightness).toBe(73)
    expect(s.result.current.selectedView?.confirmed.knowledge.hsv).toBe('observed')
    expect(s.result.current.selectedView?.preview.hsv.hue).toBe(316)
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
  it('keeps an in-flight refresh stale after an indeterminate confirmation', async () => {
    const s = await setup()
    const pending = deferred<PublicDeviceStatus>()
    s.bridge.status = vi.fn(() => pending.promise)
    let confirmation!: Promise<ConfirmOutcome>
    let refresh!: Promise<void>
    act(() => { confirmation = s.result.current.confirmRecovery(proposal.proposalId); refresh = s.result.current.refreshDevice('lamp') })
    s.confirm.reject({ code: 'TIMEOUT' })
    await act(async () => { expect(await confirmation).toMatchObject({ kind: 'indeterminate' }) })
    pending.resolve(publicDevice())
    await act(async () => { await refresh })
    expect(s.result.current.selectedView?.confirmed.knowledge.power).toBe('stale')
    await expect(s.lighting.command('lamp', { hsv: { hue: 20 } })).rejects.toMatchObject({ code: 'DEVICE_ERROR' })
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

