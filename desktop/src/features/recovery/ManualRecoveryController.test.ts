import { describe, expect, it, vi } from 'vitest'
import { TauriManualRecoveryController } from './TauriManualRecoveryController'
import { parsePrepareResult, parseConfirmResult, prepareFailures, confirmFailures } from './contracts'
import { proposal, publicDevice, deferred } from './testSupport'

describe('manual recovery boundary', () => {
  it('uses only fixed invokes and exact payloads', async () => {
    const invoke = vi.fn().mockResolvedValueOnce(proposal).mockResolvedValueOnce({ recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } })
    const recovery = new TauriManualRecoveryController(invoke)
    expect(await recovery.prepare('lamp')).toEqual({ kind: 'terminal', result: proposal })
    expect(await recovery.confirm(proposal.proposalId)).toEqual({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } } })
    expect(invoke.mock.calls).toEqual([['bridge_recovery_prepare', { deviceId: 'lamp' }], ['bridge_recovery_confirm', { proposalId: proposal.proposalId }]])
  })
  it('keeps all public domain statuses distinct from bridge errors', () => {
    for (const status of prepareFailures) expect(parsePrepareResult({ status })).toEqual({ status })
    for (const status of confirmFailures) expect(parseConfirmResult({ recovery: { status } })).toEqual({ recovery: { status } })
    for (const status of ['FAILED', 'SUPERSEDED', 'SUCCEEDED']) {
      expect(parseConfirmResult({ recovery: { status: 'ADOPTED' }, readback: { status } })).toMatchObject({ recovery: { status: 'ADOPTED' }, readback: { status } })
    }
    expect(parsePrepareResult({ ...proposal, ttlSeconds: 0 }).status).toBe('PROPOSAL_READY')
  })
  it('rejects unknown fields, inconsistent results, invalid TTL/IP/token and private snapshots', () => {
    for (const value of [{ ...proposal, ttlSeconds: -1 }, { ...proposal, ttlSeconds: Infinity }, { ...proposal, candidateIp: 'localhost' }, { ...proposal, proposalId: 'x' }, { status: 'BUSY', owner: 'private' }, { status: 'OTHER' }]) {
      expect(() => parsePrepareResult(value)).toThrow()
    }
    for (const value of [
      { recovery: { status: 'ADOPTED' } },
      { recovery: { status: 'BUSY' }, readback: { status: 'FAILED' } },
      { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED', device: publicDevice() } },
      { recovery: { status: 'ADOPTED' }, readback: { status: 'SUCCEEDED', device: { ...publicDevice(), localKey: 'must-not-leak' } } },
    ]) expect(() => parseConfirmResult(value)).toThrow()
  })
  it('does not retry an ambiguous confirm or forward a concurrent duplicate', async () => {
    const pending = deferred<unknown>()
    const invoke = vi.fn(() => pending.promise)
    const recovery = new TauriManualRecoveryController(invoke)
    const first = recovery.confirm(proposal.proposalId)
    expect(await recovery.confirm(proposal.proposalId)).toMatchObject({ kind: 'rejected' })
    pending.reject({ code: 'TIMEOUT', message: 'private exception' })
    expect(await first).toEqual({ kind: 'indeterminate', code: 'TIMEOUT' })
    expect(await recovery.confirm(proposal.proposalId)).toMatchObject({ kind: 'rejected' })
    expect(invoke).toHaveBeenCalledTimes(1)
  })
  it('allows an explicit retry only after terminal BUSY and does not confuse domain TIMEOUT', async () => {
    const invoke = vi.fn().mockResolvedValueOnce({ recovery: { status: 'BUSY' } }).mockResolvedValueOnce({ recovery: { status: 'TIMEOUT' } })
    const recovery = new TauriManualRecoveryController(invoke)
    expect(await recovery.confirm(proposal.proposalId)).toMatchObject({ kind: 'terminal', result: { recovery: { status: 'BUSY' } } })
    expect(await recovery.confirm(proposal.proposalId)).toMatchObject({ kind: 'terminal', result: { recovery: { status: 'TIMEOUT' } } })
    expect(invoke).toHaveBeenCalledTimes(2)
  })
  it('rejects invalid local inputs before sending and sanitizes prepare failures', async () => {
    const invoke = vi.fn().mockRejectedValue(new Error('private exception'))
    const recovery = new TauriManualRecoveryController(invoke)
    expect(await recovery.prepare('')).toMatchObject({ kind: 'rejected' })
    expect(await recovery.confirm('bad')).toMatchObject({ kind: 'rejected' })
    expect(invoke).not.toHaveBeenCalled()
    expect(await recovery.prepare('lamp')).toEqual({ kind: 'bridge-error', code: 'DEVICE_ERROR' })
  })
})

