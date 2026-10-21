import type { PublicDeviceStatus } from '../features/devices/publicDeviceMapper'
import type { ManualRecoveryController, PrepareOutcome, ConfirmOutcome } from '../features/recovery/ManualRecoveryController'
import type { ReadbackResult } from '../features/recovery/contracts'
import { validDeviceId, validProposalId } from '../features/recovery/contracts'

interface Proposal { deviceId: string; expiresAt: number; candidateIp: string }
export class MockManualRecoveryController implements ManualRecoveryController {
  private readonly proposals = new Map<string, Proposal>()
  private sequence = 0
  private active = false
  private readonly catalog: () => readonly PublicDeviceStatus[]
  private readonly readback: (deviceId: string, address: string) => Promise<ReadbackResult>
  private readonly clock: () => number
  constructor(
    catalog: () => readonly PublicDeviceStatus[],
    readback: (deviceId: string, address: string) => Promise<ReadbackResult>,
    clock: () => number = () => performance.now() / 1000,
  ) { this.catalog = catalog; this.readback = readback; this.clock = clock }

  private expire() {
    for (const [token, proposal] of this.proposals) if (this.clock() >= proposal.expiresAt) this.proposals.delete(token)
  }
  async prepare(deviceId: string): Promise<PrepareOutcome> {
    if (!validDeviceId(deviceId)) return { kind: 'rejected', code: 'INVALID_INPUT' }
    if (this.active) return { kind: 'terminal', result: { status: 'BUSY' } }
    this.expire()
    const device = this.catalog().find((entry) => entry.deviceId === deviceId)
    if (!device) return { kind: 'terminal', result: { status: 'DEVICE_NOT_FOUND' } }
    if (device.protocolVersion !== 3.5) return { kind: 'terminal', result: { status: 'PROTOCOL_NOT_ELIGIBLE' } }
    if (this.proposals.size >= 4 || [...this.proposals.values()].some((entry) => entry.deviceId === deviceId)) return { kind: 'terminal', result: { status: 'BUSY' } }
    // Synthetic identifier only. This store is never used for REAL or FIXTURE.
    const proposalId = 'M' + (++this.sequence).toString(36).padStart(42, '0')
    const candidateIp = '198.51.100.35'
    this.proposals.set(proposalId, { deviceId, candidateIp, expiresAt: this.clock() + 60 })
    return { kind: 'terminal', result: { status: 'PROPOSAL_READY', proposalId, candidateIp, ttlSeconds: 60 } }
  }
  async confirm(proposalId: string): Promise<ConfirmOutcome> {
    if (!validProposalId(proposalId)) return { kind: 'rejected', code: 'INVALID_INPUT' }
    if (this.active) return { kind: 'terminal', result: { recovery: { status: 'BUSY' } } }
    this.expire()
    const proposal = this.proposals.get(proposalId)
    if (!proposal) return { kind: 'terminal', result: { recovery: { status: 'PROPOSAL_EXPIRED' } } }
    this.proposals.delete(proposalId)
    this.active = true
    try {
      const readback = await this.readback(proposal.deviceId, proposal.candidateIp)
      return { kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback } }
    } catch {
      return { kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } } }
    } finally { this.active = false }
  }
}

