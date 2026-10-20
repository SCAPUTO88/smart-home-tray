import type { ManualRecoveryController, PrepareOutcome, ConfirmOutcome } from './ManualRecoveryController'
import { parsePrepareResult, parseConfirmResult, validDeviceId, validProposalId } from './contracts'
import { parseBridgeError } from '../devices/publicDeviceMapper'

export type RecoveryInvoke = (command: 'bridge_recovery_prepare' | 'bridge_recovery_confirm', args: { deviceId: string } | { proposalId: string }) => Promise<unknown>

export class TauriManualRecoveryController implements ManualRecoveryController {
  private readonly attempted = new Set<string>()
  private readonly invoke: RecoveryInvoke
  constructor(invoke: RecoveryInvoke) { this.invoke = invoke }

  async prepare(deviceId: string): Promise<PrepareOutcome> {
    if (!validDeviceId(deviceId)) return { kind: 'rejected', code: 'INVALID_INPUT' }
    try {
      return { kind: 'terminal', result: parsePrepareResult(await this.invoke('bridge_recovery_prepare', { deviceId })) }
    } catch (error) {
      return { kind: 'bridge-error', code: parseBridgeError(error).code }
    }
  }

  async confirm(proposalId: string): Promise<ConfirmOutcome> {
    if (!validProposalId(proposalId)) return { kind: 'rejected', code: 'INVALID_INPUT' }
    if (this.attempted.has(proposalId)) return { kind: 'rejected', code: 'PROPOSAL_UNAVAILABLE' }
    this.attempted.add(proposalId)
    try {
      const result = parseConfirmResult(await this.invoke('bridge_recovery_confirm', { proposalId }))
      // Only terminal BUSY proves pre-admission. A later explicit call is allowed.
      if (result.recovery.status === 'BUSY') this.attempted.delete(proposalId)
      return { kind: 'terminal', result }
    } catch (error) {
      return { kind: 'indeterminate', code: parseBridgeError(error).code }
    }
  }
}

