import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ManualRecoveryPanel } from './ManualRecoveryPanel'
import { RecoveryPresentation } from './recoveryPresentation'
import type { ConfirmOutcome, PrepareOutcome } from './ManualRecoveryController'
import type { RecoveryEligibility } from './reconciliation'
import { confirmFailures, prepareFailures, type ReadbackResult } from './contracts'
import { deferred, proposal, publicDevice } from './testSupport'

const eligible: RecoveryEligibility = { status: 'ELIGIBLE', protocolVersion: 3.5 }
function setup(options: { ttl?: number; eligibility?: RecoveryEligibility } = {}) {
  let time = 0
  const store = new RecoveryPresentation(() => time)
  const prepare = vi.fn<(_: string) => Promise<PrepareOutcome>>(async () => ({ kind: 'terminal', result: { ...proposal, ttlSeconds: options.ttl ?? 60 } }))
  const confirm = vi.fn<(_: string) => Promise<ConfirmOutcome>>(async () => ({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } } }))
  const refresh = vi.fn(async () => {})
  const props = { deviceId: 'lamp', deviceName: 'Luz Mesa', eligibility: options.eligibility ?? eligible, store, prepareRecovery: prepare, confirmRecovery: confirm, refreshDevice: refresh, refreshDisabled: false, simulation: true }
  const view = render(<ManualRecoveryPanel {...props} />)
  const user = userEvent.setup(vi.isFakeTimers() ? { advanceTimers: vi.advanceTimersByTime } : {})
  const open = async () => user.click(screen.getByRole('button', { name: /Recuperar IP/ }))
  const start = async () => { await open(); await user.click(screen.getByRole('button', { name: 'Preparar recuperação' })) }
  return { ...view, props, store, user, prepare, confirm, refresh, open, start, setTime: (value: number) => { time = value } }
}
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

describe('manual recovery presentation', () => {
  it('requires explicit prepare and confirm, shows trust warning, immutable IP and only sends proposalId', async () => {
    const s = setup(); await s.open()
    expect(s.prepare).not.toHaveBeenCalled()
    expect(screen.getByText(/Elegível.*Tuya 3.5/)).toBeVisible()
    await s.user.click(screen.getByRole('button', { name: 'Preparar recuperação' }))
    expect(s.prepare).toHaveBeenCalledExactlyOnceWith('lamp')
    expect(screen.getByText(proposal.candidateIp)).toBeVisible()
    expect(screen.getByText(/não constitui prova independente da identidade física/)).toBeVisible()
    expect(screen.getByText(/apenas em memória/)).toBeVisible()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(s.confirm).not.toHaveBeenCalled()
    expect(screen.getByRole('heading', { name: /Confirmar.*Luz Mesa/ })).toHaveFocus()
    await s.user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    expect(s.confirm).toHaveBeenCalledExactlyOnceWith(proposal.proposalId)
  })
  it.each<RecoveryEligibility>([{ status: 'INELIGIBLE', protocolVersion: 3.3 }, { status: 'UNKNOWN', protocolVersion: null }])('blocks $status without inventing protocol', async (eligibility) => {
    const s = setup({ eligibility }); await s.open()
    expect(screen.getByRole('button', { name: 'Preparar recuperação' })).toBeDisabled()
    expect(s.prepare).not.toHaveBeenCalled()
    expect(screen.getByText(eligibility.status === 'UNKNOWN' ? /Elegibilidade desconhecida/ : /exige Tuya 3.5/)).toBeVisible()
  })
  it.each([0, 1, 2])('blocks confirmation with initial TTL %s', async (ttl) => {
    const s = setup({ ttl }); await s.start()
    if (ttl) expect(screen.getByRole('button', { name: 'Confirmar recuperação' })).toBeDisabled()
    else { expect(screen.queryByRole('button', { name: 'Confirmar recuperação' })).not.toBeInTheDocument(); expect(screen.getByText(/Proposta expirada/)).toBeVisible() }
    expect(s.confirm).not.toHaveBeenCalled()
  })
  it('expires using elapsed monotonic time, including hidden popup and resume without interval delivery', async () => {
    vi.useFakeTimers()
    const s = setup()
    fireEvent.click(screen.getByRole('button', { name: /Recuperar IP/ }))
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Preparar recuperação' })) })
    s.setTime(58000); act(() => { vi.advanceTimersByTime(250) })
    expect(screen.getByRole('button', { name: 'Confirmar recuperação' })).toBeDisabled()
    fireEvent(document, new Event('visibilitychange'))
    s.setTime(61000); fireEvent(window, new Event('focus'))
    expect(screen.getByText(/Proposta expirada/)).toBeVisible()
    expect(s.confirm).not.toHaveBeenCalled()
  })
  it('rechecks TTL on click even before the next timer tick', async () => {
    const s = setup(); await s.start(); s.setTime(59000)
    await s.user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    expect(s.confirm).not.toHaveBeenCalled()
  })
  it('prevents duplicate prepare and confirm and cannot dismiss an executing confirmation', async () => {
    const s = setup(); const p = deferred<PrepareOutcome>(); const c = deferred<ConfirmOutcome>()
    s.prepare.mockReturnValue(p.promise); s.confirm.mockReturnValue(c.promise)
    await s.open(); await s.user.dblClick(screen.getByRole('button', { name: 'Preparar recuperação' }))
    expect(s.prepare).toHaveBeenCalledTimes(1)
    await act(async () => { p.resolve({ kind: 'terminal', result: proposal }) })
    await s.user.dblClick(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    expect(s.confirm).toHaveBeenCalledTimes(1)
    await s.user.keyboard('{Escape}')
    expect(screen.getByText(/Confirmação em andamento/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Dispensar' })).not.toBeInTheDocument()
  })
  it('allows only explicit BUSY retry with original TTL/token', async () => {
    const s = setup(); s.confirm.mockResolvedValue({ kind: 'terminal', result: { recovery: { status: 'BUSY' } } })
    await s.start(); await s.user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    expect(screen.getByText(/Outra operação/)).toBeVisible(); expect(s.confirm).toHaveBeenCalledTimes(1)
    await s.user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    expect(s.confirm).toHaveBeenCalledTimes(2)
    s.setTime(61000); fireEvent(window, new Event('focus'))
    expect(screen.queryByRole('button', { name: 'Confirmar recuperação' })).not.toBeInTheDocument()
  })
  it.each(prepareFailures)('presents public prepare %s without internal details or address selection', async (status) => {
    const s = setup(); s.prepare.mockResolvedValue({ kind: 'terminal', result: { status } }); await s.start()
    expect(screen.getByTestId('recovery-state')).toHaveAttribute('data-state', status === 'AMBIGUOUS' ? 'ambiguous' : status === 'BUSY' ? 'busy' : 'failed')
    expect(screen.queryByText(proposal.candidateIp)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirmar recuperação' })).not.toBeInTheDocument()
  })
  it.each(confirmFailures)('presents terminal confirm %s, never as indeterminate', async (status) => {
    const s = setup(); s.confirm.mockResolvedValue({ kind: 'terminal', result: { recovery: { status } } })
    await s.start(); await s.user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    expect(screen.getByTestId('recovery-state')).toHaveAttribute('data-state', status === 'PROPOSAL_EXPIRED' ? 'expired' : status === 'BUSY' ? 'busy' : 'failed')
  })
  it('treats bridge timeout as unknown adoption, never enables retry or claims rollback', async () => {
    const s = setup(); s.confirm.mockResolvedValue({ kind: 'indeterminate', code: 'TIMEOUT' })
    await s.start(); await s.user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    expect(screen.getByText(/adoção pode ter ocorrido/)).toBeVisible()
    expect(screen.queryByRole('button', { name: /Preparar|Confirmar recuperação/ })).not.toBeInTheDocument()
    await s.user.click(screen.getByRole('button', { name: 'Atualizar leitura' }))
    expect(s.refresh).toHaveBeenCalledExactlyOnceWith('lamp')
    expect(s.confirm).toHaveBeenCalledTimes(1)
  })
  it.each<ReadbackResult>([{ status: 'SUCCEEDED', device: publicDevice() }, { status: 'FAILED' }, { status: 'SUPERSEDED' }, { status: 'SUCCEEDED' }])('keeps adoption distinct from readback $status', async (readback) => {
    const s = setup(); s.confirm.mockResolvedValue({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback } })
    await s.start(); await s.user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    expect(screen.getByText(/Adoção em memória concluída/)).toBeVisible()
    expect(s.refresh).not.toHaveBeenCalled()
    if (readback.status === 'FAILED' || readback.status === 'SUCCEEDED' && !readback.device) {
      await s.user.click(screen.getByRole('button', { name: 'Atualizar leitura' })); expect(s.refresh).toHaveBeenCalledWith('lamp')
    }
  })
  it('isolates late prepare results by original device and restores the original panel', async () => {
    const s = setup(); const p = deferred<PrepareOutcome>(); s.prepare.mockReturnValueOnce(p.promise)
    await s.start(); s.rerender(<ManualRecoveryPanel {...s.props} deviceId="other" deviceName="Fita LED" />)
    await s.user.click(screen.getByRole('button', { name: 'Preparar recuperação' }))
    await act(async () => { p.resolve({ kind: 'terminal', result: { ...proposal, candidateIp: '192.0.2.10' } }) })
    expect(screen.queryByText('192.0.2.10')).not.toBeInTheDocument()
    s.rerender(<ManualRecoveryPanel {...s.props} />)
    expect(screen.getByText('192.0.2.10')).toBeVisible()
  })
  it('retains in-flight confirmation through unmount/remount without restarting it', async () => {
    const s = setup(); const c = deferred<ConfirmOutcome>(); s.confirm.mockReturnValue(c.promise)
    await s.start(); await s.user.click(screen.getByRole('button', { name: 'Confirmar recuperação' })); s.unmount()
    const remount = render(<ManualRecoveryPanel {...s.props} />)
    await s.user.click(screen.getByRole('button', { name: /Recuperar IP/ }))
    expect(screen.getByText(/Confirmação em andamento/)).toBeVisible()
    await act(async () => { c.resolve({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } } }) })
    expect(screen.getByText(/Adoção em memória concluída/)).toBeVisible()
    expect(s.confirm).toHaveBeenCalledTimes(1); remount.unmount()
  })
  it('supports keyboard activation, labelled region, live result and safe Escape focus return', async () => {
    const s = setup(); await s.user.tab(); await s.user.keyboard('{Enter}')
    expect(screen.getByRole('region', { name: /Recuperação manual/ })).toBeVisible()
    await s.user.tab(); await s.user.keyboard('{Enter}')
    expect(screen.getByRole('heading', { name: /Confirmar.*Luz Mesa/ })).toHaveFocus()
    expect(screen.getByTestId('recovery-state')).toHaveAttribute('aria-live', 'polite')
    await s.user.keyboard('{Escape}')
    expect(screen.getByRole('button', { name: /Recuperar IP/ })).toHaveFocus()
    expect(screen.queryByRole('button', { name: 'Confirmar recuperação' })).not.toBeInTheDocument()
  })
  it('expires while collapsed and removes interval/listeners on unmount', async () => {
    vi.useFakeTimers()
    const s = setup()
    fireEvent.click(screen.getByRole('button', { name: /Recuperar IP/ }))
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Preparar recuperação' })) })
    fireEvent.click(screen.getByRole('button', { name: /Recuperar IP/ }))
    s.setTime(61000)
    act(() => { vi.advanceTimersByTime(1000) })
    fireEvent.click(screen.getByRole('button', { name: /Recuperar IP/ }))
    expect(screen.getByText(/Proposta expirada/)).toBeVisible()
    expect(s.prepare).toHaveBeenCalledTimes(1)
    s.unmount(); expect(vi.getTimerCount()).toBe(0)
    fireEvent(window, new Event('focus'))
    expect(s.confirm).not.toHaveBeenCalled()
  })
  it.each([NaN, Infinity, -1])('fails closed for invalid TTL %s', async (ttl) => {
    const s = setup({ ttl }); await s.start()
    expect(screen.getByText(/Solicitação incompatível/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Confirmar recuperação' })).not.toBeInTheDocument()
  })
  it('sanitizes unexpected prepare rejection without exposing exception details', async () => {
    const s = setup(); s.prepare.mockRejectedValue(new Error('private diagnostic sentinel'))
    await s.start()
    expect(screen.getByText(/Não foi possível preparar/)).toBeVisible()
    expect(screen.queryByText(/private diagnostic/)).not.toBeInTheDocument()
    expect(screen.getByTestId('recovery-state')).toHaveAttribute('data-state', 'failed')
  })
  it('offers a fresh preparation after unavailable/replayed proposal without replaying confirm', async () => {
    const s = setup(); s.confirm.mockResolvedValue({ kind: 'rejected', code: 'PROPOSAL_UNAVAILABLE' })
    await s.start(); await s.user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    expect(screen.getByText(/Proposta expirada/)).toBeVisible()
    expect(s.prepare).toHaveBeenCalledTimes(1)
    await s.user.click(screen.getByRole('button', { name: 'Preparar recuperação' }))
    expect(s.prepare).toHaveBeenCalledTimes(2); expect(s.confirm).toHaveBeenCalledTimes(1)
  })
  it('does not steal focus or show a late confirmation while another device is selected', async () => {
    const s = setup(); const c = deferred<ConfirmOutcome>(); s.confirm.mockReturnValue(c.promise)
    await s.start(); await s.user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    s.rerender(<ManualRecoveryPanel {...s.props} deviceId="other" deviceName="Fita LED" />)
    screen.getByRole('button', { name: 'Preparar recuperação' }).focus()
    await act(async () => { c.resolve({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } } }) })
    expect(screen.queryByText(/Adoção em memória concluída/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Preparar recuperação' })).toHaveFocus()
    s.rerender(<ManualRecoveryPanel {...s.props} />)
    await s.user.click(screen.getByRole('button', { name: 'Atualizar leitura' }))
    expect(s.refresh).toHaveBeenCalledExactlyOnceWith('lamp')
  })
})
