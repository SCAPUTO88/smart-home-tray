import { describe, expect, it } from 'vitest'
import { MockManualRecoveryController } from './MockManualRecoveryController'
import { publicDevice, deferred } from '../features/recovery/testSupport'
import type { ReadbackResult } from '../features/recovery/contracts'

describe('memory-only manual recovery', () => {
  it('consumes confirmations, expires proposals by injected clock, and leaves pending human proposals outside the slot', async () => {
    let now = 10
    const pending = deferred<ReadbackResult>()
    const recovery = new MockManualRecoveryController(() => [publicDevice(), publicDevice('other')], () => pending.promise, () => now)
    const first = await recovery.prepare('lamp')
    const other = await recovery.prepare('other')
    if (first.kind !== 'terminal' || first.result.status !== 'PROPOSAL_READY' || other.kind !== 'terminal' || other.result.status !== 'PROPOSAL_READY') throw new Error('expected proposals')
    expect(await recovery.prepare('lamp')).toMatchObject({ result: { status: 'BUSY' } })
    const confirmation = recovery.confirm(first.result.proposalId)
    expect(await recovery.confirm(other.result.proposalId)).toMatchObject({ result: { recovery: { status: 'BUSY' } } })
    pending.resolve({ status: 'SUCCEEDED', device: publicDevice() })
    expect(await confirmation).toMatchObject({ result: { recovery: { status: 'ADOPTED' } } })
    expect(await recovery.confirm(first.result.proposalId)).toMatchObject({ result: { recovery: { status: 'PROPOSAL_EXPIRED' } } })
    now += 60
    expect(await recovery.confirm(other.result.proposalId)).toMatchObject({ result: { recovery: { status: 'PROPOSAL_EXPIRED' } } })
    expect(await recovery.prepare('other')).toMatchObject({ result: { status: 'PROPOSAL_READY' } })
  })
  it.each<ReadbackResult>([{ status: 'FAILED' }, { status: 'SUPERSEDED' }, { status: 'SUCCEEDED' }])('keeps adoption distinct from $status', async (readback) => {
    const recovery = new MockManualRecoveryController(() => [publicDevice()], async () => readback)
    const prepared = await recovery.prepare('lamp')
    if (prepared.kind !== 'terminal' || prepared.result.status !== 'PROPOSAL_READY') throw new Error('expected proposal')
    expect(await recovery.confirm(prepared.result.proposalId)).toEqual({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback } })
  })
  it('enforces eligibility and four pending proposals without extending TTL', async () => {
    let now = 0
    const catalog = ['a', 'b', 'c', 'd', 'e'].map(publicDevice)
    catalog.push({ ...publicDevice('legacy'), protocolVersion: 3.3 })
    const recovery = new MockManualRecoveryController(() => catalog, async () => ({ status: 'FAILED' }), () => now)
    expect(await recovery.prepare('legacy')).toMatchObject({ result: { status: 'PROTOCOL_NOT_ELIGIBLE' } })
    expect(await recovery.prepare('absent')).toMatchObject({ result: { status: 'DEVICE_NOT_FOUND' } })
    for (const id of ['a', 'b', 'c', 'd']) expect(await recovery.prepare(id)).toMatchObject({ result: { status: 'PROPOSAL_READY', ttlSeconds: 60 } })
    now = 59
    expect(await recovery.prepare('a')).toMatchObject({ result: { status: 'BUSY' } })
    expect(await recovery.prepare('e')).toMatchObject({ result: { status: 'BUSY' } })
    now = 60
    expect(await recovery.prepare('e')).toMatchObject({ result: { status: 'PROPOSAL_READY' } })
  })
})

