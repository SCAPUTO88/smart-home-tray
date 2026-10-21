import type { PublicDeviceStatus } from '../devices/publicDeviceMapper'
import { OperationError } from '../devices/types'

export const prepareFailures = ['NOT_FOUND', 'AMBIGUOUS', 'TIMEOUT', 'TRANSPORT_FAILED', 'AUTH_FAILED', 'VALIDATION_FAILED', 'DEVICE_NOT_FOUND', 'PROTOCOL_NOT_ELIGIBLE', 'BUSY', 'INVALID_INPUT', 'CONFIG_CHANGED', 'SHUTDOWN'] as const
export const confirmFailures = ['PROPOSAL_EXPIRED', 'BUSY', 'INVALID_INPUT', 'TIMEOUT', 'SHUTDOWN', 'CONFIG_CHANGED', 'PROTOCOL_NOT_ELIGIBLE', 'AUTH_FAILED', 'TRANSPORT_FAILED', 'VALIDATION_FAILED'] as const
export type PrepareResult =
  | { status: 'PROPOSAL_READY'; proposalId: string; candidateIp: string; ttlSeconds: number }
  | { status: typeof prepareFailures[number] }
export type ReadbackResult =
  | { status: 'SUCCEEDED'; device?: PublicDeviceStatus }
  | { status: 'FAILED' | 'SUPERSEDED'; device?: never }
export type ConfirmResult =
  | { recovery: { status: 'ADOPTED' }; readback: ReadbackResult }
  | { recovery: { status: typeof confirmFailures[number] }; readback?: never }

export const validProposalId = (value: string) => typeof value === 'string' && /^[A-Za-z0-9_-]{43}$/.test(value)
export const validDeviceId = (value: string) => typeof value === 'string' && value.trim().length > 0 && new TextEncoder().encode(value).length <= 128

function invalid(): never { throw new OperationError('DEVICE_ERROR') }
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid()
  return value as Record<string, unknown>
}
function keys(value: Record<string, unknown>, required: string[], optional: string[] = []) {
  if (required.some((key) => !(key in value)) || Object.keys(value).some((key) => !required.includes(key) && !optional.includes(key))) invalid()
}
function oneOf<T extends string>(value: unknown, choices: readonly T[]): T {
  if (typeof value !== 'string' || !choices.includes(value as T)) return invalid()
  return value as T
}
function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
function ipv4(value: unknown): value is string {
  return typeof value === 'string' && value.split('.').length === 4
    && value.split('.').every((part) => /^(0|[1-9][0-9]{0,2})$/.test(part) && Number(part) <= 255)
}

// Runtime boundary mirrors the strict Rust DTO; never copy unknown snapshot fields.
export function parsePublicRecoveryDevice(value: unknown): PublicDeviceStatus {
  const device = record(value)
  keys(device, ['deviceId', 'name', 'address', 'protocolVersion', 'capabilities', 'connection', 'state'])
  if (typeof device.deviceId !== 'string' || !validDeviceId(device.deviceId) || typeof device.name !== 'string' || typeof device.address !== 'string' || !finite(device.protocolVersion)) invalid()
  oneOf(device.connection, ['online', 'offline', 'unknown'])
  const caps = record(device.capabilities)
  keys(caps, ['power', 'whiteBrightness', 'colorValue', 'colorTemperature', 'scenes'])
  if (Object.values(caps).some((value) => typeof value !== 'boolean')) invalid()
  const state = record(device.state)
  keys(state, ['power', 'workMode', 'whiteBrightnessPercent', 'colorValuePercent', 'colorTemperaturePercent', 'hsv', 'scene', 'quality', 'knowledge'])
  if (state.power !== null && typeof state.power !== 'boolean') invalid()
  for (const field of ['workMode', 'scene']) if (state[field] !== null && typeof state[field] !== 'string') invalid()
  for (const field of ['whiteBrightnessPercent', 'colorValuePercent', 'colorTemperaturePercent']) if (state[field] !== null && !finite(state[field])) invalid()
  oneOf(state.quality, ['confirmed', 'pending', 'offline', 'unknown'])
  const knowledge = record(state.knowledge)
  keys(knowledge, ['power', 'workMode', 'whiteBrightness', 'colorTemperature', 'hsv', 'colorValue', 'scene'])
  for (const value of Object.values(knowledge)) oneOf(value, ['observed', 'stale', 'unknown'])
  if (state.hsv !== null) {
    const hsv = record(state.hsv)
    keys(hsv, ['hue', 'saturation', 'value'])
    if (Object.values(hsv).some((value) => !finite(value))) invalid()
  }
  return structuredClone(device) as unknown as PublicDeviceStatus
}

export function parsePrepareResult(value: unknown): PrepareResult {
  const result = record(value)
  if (result.status === 'PROPOSAL_READY') {
    keys(result, ['status', 'proposalId', 'candidateIp', 'ttlSeconds'])
    if (typeof result.proposalId !== 'string' || !validProposalId(result.proposalId) || !ipv4(result.candidateIp) || !finite(result.ttlSeconds) || result.ttlSeconds < 0) return invalid()
    return { status: 'PROPOSAL_READY', proposalId: result.proposalId, candidateIp: result.candidateIp, ttlSeconds: result.ttlSeconds }
  }
  keys(result, ['status'])
  return { status: oneOf(result.status, prepareFailures) }
}

export function parseConfirmResult(value: unknown): ConfirmResult {
  const result = record(value)
  const recovery = record(result.recovery)
  keys(recovery, ['status'])
  if (recovery.status !== 'ADOPTED') {
    keys(result, ['recovery'])
    return { recovery: { status: oneOf(recovery.status, confirmFailures) } }
  }
  keys(result, ['recovery', 'readback'])
  const readback = record(result.readback)
  if (readback.status === 'SUCCEEDED') {
    keys(readback, ['status'], ['device'])
    return { recovery: { status: 'ADOPTED' }, readback: { status: 'SUCCEEDED', ...('device' in readback ? { device: parsePublicRecoveryDevice(readback.device) } : {}) } }
  }
  keys(readback, ['status'])
  return { recovery: { status: 'ADOPTED' }, readback: { status: oneOf(readback.status, ['FAILED', 'SUPERSEDED']) } }
}

