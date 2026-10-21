import { useEffect, useId, useRef, useState, useSyncExternalStore } from 'react'
import type { ConfirmOutcome, PrepareOutcome } from './ManualRecoveryController'
import type { RecoveryEligibility } from './reconciliation'
import type { RecoveryPresentation, RecoveryView } from './recoveryPresentation'

interface Props {
  deviceId: string
  deviceName: string
  eligibility: RecoveryEligibility
  store: RecoveryPresentation
  prepareRecovery: (deviceId: string) => Promise<PrepareOutcome>
  confirmRecovery: (proposalId: string) => Promise<ConfirmOutcome>
  refreshDevice?: (deviceId: string) => Promise<void>
  refreshDisabled: boolean
  simulation: boolean
}

function resultMessage(state: RecoveryView): string {
  switch (state.kind) {
    case 'idle': return 'A busca começa somente ao preparar. Nenhum endereço é alterado sem sua confirmação.'
    case 'preparing': return 'Preparando proposta… Ocultar o painel não cancela a operação.'
    case 'confirming': return 'Confirmação em andamento… Ocultar o painel não cancela a operação.'
    case 'proposal-ready': return 'Confira o candidato antes de confirmar.'
    case 'busy': return 'Outra operação de recuperação está em andamento. Uma nova tentativa exige sua ação.'
    case 'failed': case 'ambiguous': case 'expired': return state.message
    case 'indeterminate': return 'Resultado desconhecido: a adoção pode ter ocorrido. Não repita a confirmação. Atualizar a leitura não comprova o resultado da adoção original.'
    case 'adopted': {
      const prefix = 'Adoção em memória concluída. '
      if (state.readback.status === 'FAILED') return prefix + 'O estado físico ainda não foi confirmado.'
      if (state.readback.status === 'SUPERSEDED') return prefix + 'A leitura foi superada por outra operação.'
      return prefix + (state.readback.device ? 'Leitura recebida; os controles refletem o estado reconciliado.' : 'Snapshot indisponível; o estado físico ainda não foi confirmado.')
    }
  }
}

export function ManualRecoveryPanel(props: Props) {
  const { deviceId, deviceName, eligibility, store, prepareRecovery, confirmRecovery, refreshDevice, refreshDisabled, simulation } = props
  const state = useSyncExternalStore(store.subscribe, () => store.get(deviceId))
  const [expanded, setExpanded] = useState(false)
  const [, tick] = useState(0)
  const toggle = useRef<HTMLButtonElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const focusedProposal = useRef<string | null>(null)
  const regionId = useId()
  const busy = state.kind === 'preparing' || state.kind === 'confirming'
  const proposal = 'proposal' in state ? state.proposal : undefined
  const remaining = store.remaining(state)
  const canPrepare = eligibility.status === 'ELIGIBLE' && !busy && !proposal && state.kind !== 'indeterminate'
  const needsRefresh = state.kind === 'indeterminate' || state.kind === 'adopted' && (state.readback.status === 'FAILED' || state.readback.status === 'SUCCEEDED' && !state.readback.device)

  useEffect(() => {
    const update = () => { store.expire(deviceId); tick((value) => value + 1) }
    update()
    const timer = proposal ? window.setInterval(update, 250) : undefined
    window.addEventListener('focus', update)
    window.addEventListener('pageshow', update)
    document.addEventListener('visibilitychange', update)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', update)
      window.removeEventListener('pageshow', update)
      document.removeEventListener('visibilitychange', update)
    }
  }, [deviceId, proposal, store])

  useEffect(() => {
    if (expanded && proposal && focusedProposal.current !== proposal.proposalId) {
      focusedProposal.current = proposal.proposalId
      heading.current?.focus()
    }
  }, [expanded, proposal, deviceId])

  const dismiss = () => {
    if (busy) return
    store.dismiss(deviceId)
    setExpanded(false)
    toggle.current?.focus()
  }

  return <section className="recovery-panel" onKeyDown={(event) => {
    if (event.key === 'Escape' && expanded) { event.stopPropagation(); event.preventDefault(); dismiss() }
  }}>
    <button ref={toggle} className="recovery-toggle" type="button" aria-expanded={expanded} aria-controls={regionId} onClick={() => setExpanded(!expanded)}>
      Recuperar IP {busy ? '· operação em andamento' : state.kind === 'indeterminate' ? '· resultado desconhecido' : ''}
      <span aria-hidden="true">{expanded ? '−' : '+'}</span>
    </button>
    {expanded && <div id={regionId} role="region" aria-label={`Recuperação manual de ${deviceName}`}>
      {simulation && <p className="recovery-simulation">Simulação · sem homologação em hardware real</p>}
      <p>{eligibility.status === 'ELIGIBLE' ? 'Elegível · Tuya 3.5' : eligibility.status === 'INELIGIBLE' ? `Protocolo ${eligibility.protocolVersion}: a recuperação atual exige Tuya 3.5.` : 'Elegibilidade desconhecida. Protocolo não informado.'}</p>
      <div data-testid="recovery-state" data-state={state.kind} aria-live="polite" aria-atomic="true"><p>{resultMessage(state)}</p></div>
      {proposal && <div className="recovery-proposal">
        <h3 ref={heading} tabIndex={-1}>Confirmar recuperação de {state.kind !== 'idle' ? state.deviceName : deviceName}</h3>
        <dl><dt>Protocolo</dt><dd>Tuya 3.5</dd><dt>IPv4 candidato</dt><dd>{proposal.candidateIp}</dd></dl>
        <p role="timer" aria-live="off">Tempo restante estimado: {Math.ceil(remaining)} s</p>
        <p>A adoção será apenas em memória. Ao reiniciar, o endereço configurado será usado.</p>
        <p className="recovery-trust">O endpoint respondeu utilizando a chave local configurada. Isso demonstra posse dessa chave, mas não constitui prova independente da identidade física do dispositivo.</p>
        <p>A estimativa não garante validade: o serviço decide a expiração. Confirmação bloqueada nos 2 segundos finais.</p>
      </div>}
      <div className="recovery-actions">
        {proposal && <button type="button" disabled={remaining <= 2} onClick={() => void store.confirm(deviceId, confirmRecovery)}>Confirmar recuperação</button>}
        {!proposal && state.kind !== 'indeterminate' && <button type="button" disabled={!canPrepare} onClick={() => void store.prepare(deviceId, deviceName, prepareRecovery)}>{busy ? 'Aguarde…' : 'Preparar recuperação'}</button>}
        {needsRefresh && refreshDevice && <button type="button" disabled={refreshDisabled} onClick={() => void refreshDevice(deviceId)}>Atualizar leitura</button>}
        {!busy && state.kind !== 'idle' && <button type="button" onClick={dismiss}>{state.kind === 'indeterminate' ? 'Ocultar resultado' : 'Dispensar'}</button>}
      </div>
      {proposal && <p>Dispensar não cancela a proposta no serviço; uma nova preparação pode aguardar sua expiração.</p>}
    </div>}
  </section>
}
