import type { PublicDeviceStatus } from '../devices/publicDeviceMapper'
import type { LightingDevice } from '../devices/types'
import type { ReadbackResult } from './contracts'
import type { ManualRecoveryController } from './ManualRecoveryController'

export type RecoveryEligibility =
  | { status: 'ELIGIBLE'; protocolVersion: 3.5 }
  | { status: 'INELIGIBLE'; protocolVersion: number }
  | { status: 'UNKNOWN'; protocolVersion: null }

export function recoveryEligibility(status?: Pick<PublicDeviceStatus, 'protocolVersion'>): RecoveryEligibility {
  const version = status?.protocolVersion
  if (version === undefined || !Number.isFinite(version) || version <= 0) return { status: 'UNKNOWN', protocolVersion: null }
  return version === 3.5 ? { status: 'ELIGIBLE', protocolVersion: 3.5 } : { status: 'INELIGIBLE', protocolVersion: version }
}

export interface RecoveryCheckpoint {
  readonly deviceId: string
  readonly catalog: number
  readonly generation: number
  /** Causal observation epoch captured when confirm was sent. */
  readonly observationEpoch: number
}

export interface RecoveryReconciler {
  eligibility(deviceId: string): RecoveryEligibility
  beginRecoveryConfirmation(deviceId: string): RecoveryCheckpoint
  reconcileRecovery(checkpoint: RecoveryCheckpoint, readback?: ReadbackResult): LightingDevice | undefined
}
export interface RecoveryIntegration {
  controller: ManualRecoveryController
  reconciliation: RecoveryReconciler
}

