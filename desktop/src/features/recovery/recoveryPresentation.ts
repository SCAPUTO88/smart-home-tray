import type { ConfirmOutcome, PrepareOutcome } from './ManualRecoveryController'
import type { PrepareResult, ReadbackResult } from './contracts'

type Proposal = Extract<PrepareResult, { status: 'PROPOSAL_READY' }> & { deadline: number }
export type RecoveryView =
  | { kind: 'idle' }
  | { kind: 'preparing' | 'confirming'; deviceName: string }
  | { kind: 'proposal-ready'; deviceName: string; proposal: Proposal }
  | { kind: 'busy'; deviceName: string; proposal?: Proposal }
  | { kind: 'failed' | 'ambiguous' | 'expired'; deviceName: string; message: string }
  | { kind: 'adopted'; deviceName: string; readback: ReadbackResult }
  | { kind: 'indeterminate'; deviceName: string }

const idle: RecoveryView = { kind: 'idle' }
const messages = {
  NOT_FOUND: 'Nenhum endereço candidato foi encontrado.',
  AMBIGUOUS: 'Mais de um endereço respondeu; nenhum foi escolhido.',
  TIMEOUT: 'A operação excedeu o prazo. O backend informou um resultado terminal.',
  AUTH_FAILED: 'O candidato não autenticou com a chave local configurada.',
  TRANSPORT_FAILED: 'Não foi possível concluir a comunicação.',
  VALIDATION_FAILED: 'Não foi possível validar o candidato.',
  DEVICE_NOT_FOUND: 'Dispositivo não está disponível no catálogo atual.',
  PROTOCOL_NOT_ELIGIBLE: 'A recuperação atual exige Tuya 3.5 elegível.',
  INVALID_INPUT: 'Solicitação incompatível com o serviço de recuperação.',
  CONFIG_CHANGED: 'A configuração do dispositivo mudou; prepare uma nova proposta.',
  SHUTDOWN: 'O serviço está encerrando.',
  PROPOSAL_EXPIRED: 'Proposta expirada ou indisponível. Prepare outra.',
} as const

function failure(status: keyof typeof messages | 'BUSY', deviceName: string): RecoveryView {
  if (status === 'BUSY') return { kind: 'busy', deviceName }
  return { kind: status === 'AMBIGUOUS' ? 'ambiguous' : status === 'PROPOSAL_EXPIRED' ? 'expired' : 'failed', deviceName, message: messages[status] }
}

/** Presentation only. Session/controller retain all physical reconciliation authority.
 * Lifetime follows the integration, not a popup mount. No persisted tokens or timers.
 */
export class RecoveryPresentation {
  private views = new Map<string, RecoveryView>()
  private listeners = new Set<() => void>()
  readonly now: () => number
  constructor(now: () => number = () => performance.now()) { this.now = now }
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  get = (deviceId: string): RecoveryView => this.views.get(deviceId) ?? idle
  private put(deviceId: string, state: RecoveryView) {
    this.views.set(deviceId, state)
    for (const listener of this.listeners) listener()
  }
  remaining(state: RecoveryView): number {
    return 'proposal' in state && state.proposal ? Math.max(0, (state.proposal.deadline - this.now()) / 1000) : 0
  }
  expire(deviceId: string) {
    const state = this.get(deviceId)
    if ('proposal' in state && state.proposal && this.remaining(state) <= 0) this.put(deviceId, failure('PROPOSAL_EXPIRED', state.deviceName))
  }
  dismiss(deviceId: string) {
    const state = this.get(deviceId)
    if (state.kind !== 'preparing' && state.kind !== 'confirming' && state.kind !== 'indeterminate') this.put(deviceId, idle)
  }
  async prepare(deviceId: string, deviceName: string, operation: (id: string) => Promise<PrepareOutcome>) {
    const current = this.get(deviceId)
    if (!['idle', 'failed', 'expired', 'ambiguous', 'busy', 'adopted'].includes(current.kind) || current.kind === 'busy' && current.proposal) return
    const pending: RecoveryView = { kind: 'preparing', deviceName }
    this.put(deviceId, pending)
    let outcome: PrepareOutcome
    try { outcome = await operation(deviceId) }
    catch { outcome = { kind: 'bridge-error', code: 'DEVICE_ERROR' } }
    if (this.get(deviceId) !== pending) return
    if (outcome.kind !== 'terminal') {
      this.put(deviceId, { kind: 'failed', deviceName, message: 'Não foi possível preparar a recuperação. Tente novamente por ação explícita.' })
    } else if (outcome.result.status === 'PROPOSAL_READY') {
      const proposal = outcome.result
      if (!Number.isFinite(proposal.ttlSeconds) || proposal.ttlSeconds < 0) {
        this.put(deviceId, failure('INVALID_INPUT', deviceName)); return
      }
      this.put(deviceId, { kind: 'proposal-ready', deviceName, proposal: { ...proposal, deadline: this.now() + proposal.ttlSeconds * 1000 } })
      this.expire(deviceId)
    } else this.put(deviceId, failure(outcome.result.status, deviceName))
  }
  async confirm(deviceId: string, operation: (id: string) => Promise<ConfirmOutcome>) {
    this.expire(deviceId)
    const current = this.get(deviceId)
    if (!('proposal' in current) || !current.proposal || this.remaining(current) <= 2) return
    const { deviceName, proposal } = current
    const pending: RecoveryView = { kind: 'confirming', deviceName }
    this.put(deviceId, pending)
    let outcome: ConfirmOutcome
    try { outcome = await operation(proposal.proposalId) }
    catch { outcome = { kind: 'indeterminate', code: 'DEVICE_ERROR' } }
    if (this.get(deviceId) !== pending) return
    if (outcome.kind === 'indeterminate') this.put(deviceId, { kind: 'indeterminate', deviceName })
    else if (outcome.kind === 'rejected') this.put(deviceId, failure(outcome.code === 'PROPOSAL_UNAVAILABLE' ? 'PROPOSAL_EXPIRED' : 'INVALID_INPUT', deviceName))
    else if (outcome.result.recovery.status === 'ADOPTED' && outcome.result.readback) this.put(deviceId, { kind: 'adopted', deviceName, readback: outcome.result.readback })
    else if (outcome.result.recovery.status === 'BUSY') {
      this.put(deviceId, { kind: 'busy', deviceName, proposal }); this.expire(deviceId)
    } else if (outcome.result.recovery.status !== 'ADOPTED') this.put(deviceId, failure(outcome.result.recovery.status, deviceName))
  }
}

const presentations = new WeakMap<object, RecoveryPresentation>()
export function recoveryPresentationFor(integration: object): RecoveryPresentation {
  let store = presentations.get(integration)
  if (!store) { store = new RecoveryPresentation(); presentations.set(integration, store) }
  return store
}
