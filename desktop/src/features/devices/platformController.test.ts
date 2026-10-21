import { beforeEach, describe, expect, it, vi } from 'vitest'

const runtime = vi.hoisted(() => ({
  native: false,
  info: { mode: 'mock', available: true, error: null } as { mode: 'mock' | 'fixture' | 'real'; available: boolean; error: unknown },
  invoke: vi.fn(),
}))
vi.mock('@tauri-apps/api/core', () => ({ isTauri: () => runtime.native, invoke: (command: string, args?: unknown) => args === undefined ? runtime.invoke(command) : runtime.invoke(command, args) }))
import { resolveDeviceController, resolveDeviceIntegration } from './platformController'
import { proposal, publicDevice } from '../recovery/testSupport'

describe('platform controller selection', () => {
  beforeEach(() => { runtime.native = false; runtime.info = { mode: 'mock', available: true, error: null }; runtime.invoke.mockReset() })
  it('preserves browser mock without native IPC calls', async () => {
    const controller = await resolveDeviceController()
    expect(controller.mode).toBe('mock')
    expect(await controller.list()).toHaveLength(2)
    expect(runtime.invoke).not.toHaveBeenCalled()
  })
  it('uses explicit fixture only when the Rust process reports it', async () => {
    runtime.native = true
    runtime.info = { mode: 'fixture', available: true, error: null }
    runtime.invoke.mockResolvedValue(runtime.info)
    const controller = await resolveDeviceController()
    expect(controller.mode).toBe('fixture')
    expect(runtime.invoke).toHaveBeenCalledWith('bridge_info')
  })
  it('does not silently fall back when an explicitly selected backend fails', async () => {
    runtime.native = true
    runtime.info = { mode: 'real', available: false, error: { code: 'DEVICE_ERROR' } }
    runtime.invoke.mockResolvedValue(runtime.info)
    await expect(resolveDeviceController()).rejects.toEqual({ code: 'DEVICE_ERROR' })
  })
  it('surfaces a bridge bootstrap rejection', async () => {
    runtime.native = true
    runtime.invoke.mockRejectedValue(new Error('native bridge unavailable'))
    await expect(resolveDeviceController()).rejects.toThrow('native bridge unavailable')
  })
  it('resolves browser MOCK recovery in memory without any native invoke', async () => {
    const integration = await resolveDeviceIntegration()
    const devices = await integration.lighting.list()
    expect(integration.recovery.reconciliation.eligibility(devices[0].deviceId)).toEqual({ status: 'ELIGIBLE', protocolVersion: 3.5 })
    expect(integration.recovery.reconciliation.eligibility(devices[1].deviceId)).toEqual({ status: 'INELIGIBLE', protocolVersion: 3.3 })
    const prepared = await integration.recovery.controller.prepare(devices[0].deviceId)
    if (prepared.kind !== 'terminal' || prepared.result.status !== 'PROPOSAL_READY') throw new Error('expected proposal')
    expect(await integration.recovery.controller.confirm(prepared.result.proposalId)).toMatchObject({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' } } })
    expect(runtime.invoke).not.toHaveBeenCalled()
    expect(devices[0]).not.toHaveProperty('protocolVersion')
    expect(devices[0]).not.toHaveProperty('address')
  })
  it.each(['fixture', 'real'] as const)('resolves %s through fixed invokes with the existing gate', async (mode) => {
    runtime.native = true
    runtime.invoke.mockImplementation(async (command: string) => {
      if (command === 'bridge_info') return { mode, available: true, error: null }
      if (command === 'bridge_list') return { devices: [publicDevice()] }
      if (command === 'bridge_status') return publicDevice()
      if (command === 'bridge_recovery_prepare') return proposal
      if (command === 'bridge_recovery_confirm') return { recovery: { status: 'ADOPTED' }, readback: { status: 'SUPERSEDED' } }
      throw new Error('unexpected command')
    })
    const integration = await resolveDeviceIntegration()
    expect(integration.lighting.mode).toBe(mode)
    await integration.lighting.list()
    const calls = runtime.invoke.mock.calls.length
    expect(integration.recovery.reconciliation.eligibility('lamp').status).toBe('ELIGIBLE')
    expect(runtime.invoke).toHaveBeenCalledTimes(calls)
    await integration.recovery.controller.prepare('lamp')
    await integration.recovery.controller.confirm(proposal.proposalId)
    expect(runtime.invoke).toHaveBeenCalledWith('bridge_recovery_prepare', { deviceId: 'lamp' })
    expect(runtime.invoke).toHaveBeenCalledWith('bridge_recovery_confirm', { proposalId: proposal.proposalId })
  })
})
