import type { OperationError } from '../devices/types'
import type { PrepareResult, ConfirmResult } from './contracts'

export type PrepareOutcome =
  | { kind: 'terminal'; result: PrepareResult }
  | { kind: 'bridge-error'; code: OperationError['code'] }
  | { kind: 'rejected'; code: 'INVALID_INPUT' }
export type ConfirmOutcome =
  | { kind: 'terminal'; result: ConfirmResult }
  | { kind: 'indeterminate'; code: OperationError['code'] }
  | { kind: 'rejected'; code: 'INVALID_INPUT' | 'PROPOSAL_UNAVAILABLE' }

export interface ManualRecoveryController {
  prepare(deviceId: string): Promise<PrepareOutcome>
  confirm(proposalId: string): Promise<ConfirmOutcome>
}

