import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './LightingApp'
import { TauriDeviceController, type BridgeApi } from '../features/devices/TauriDeviceController'
import { TauriManualRecoveryController } from '../features/recovery/TauriManualRecoveryController'
import type { ConfirmOutcome, PrepareOutcome } from '../features/recovery/ManualRecoveryController'
import type { PublicDeviceStatus } from '../features/devices/publicDeviceMapper'
import { deferred, proposal, publicDevice } from '../features/recovery/testSupport'

const runtime = vi.hoisted(() => ({ native: false, invoke: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ isTauri: () => runtime.native, invoke: (command: string, args?: unknown) => runtime.invoke(command, args) }))

async function setup() {
  const lamp = publicDevice(); lamp.name = 'Luz Mesa'
  const other = publicDevice('other'); other.name = 'Fita LED'
  const bridge: BridgeApi = { list: vi.fn(async () => [lamp, other]), status: vi.fn(async () => lamp), command: vi.fn(async () => lamp) }
  const lighting = new TauriDeviceController(bridge, 'fixture')
  const prepare = vi.fn<(_: string) => Promise<PrepareOutcome>>(async () => ({ kind: 'terminal', result: proposal }))
  const confirm = vi.fn<(_: string) => Promise<ConfirmOutcome>>(async () => ({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } } }))
  const integration = { lighting, recovery: { controller: { prepare, confirm }, reconciliation: lighting } }
  const view = render(<App integration={integration} />)
  const user = userEvent.setup()
  await screen.findByRole('heading', { name: 'Luz Mesa' })
  await user.click(screen.getByRole('button', { name: /Recuperar IP/ }))
  const start = async () => user.click(screen.getByRole('button', { name: 'Preparar recuperação' }))
  const adopt = async () => { await start(); await user.click(screen.getByRole('button', { name: 'Confirmar recuperação' })) }
  return { ...view, user, bridge, lighting, integration, prepare, confirm, start, adopt, lamp }
}

beforeEach(() => { runtime.native = false; runtime.invoke.mockReset() })
describe('recovery integrated with LightingApp/session/controllers', () => {
  it('uses reconciled stale knowledge after failed readback and restores it only through manual refresh', async () => {
    const s = await setup(); await s.adopt()
    expect(screen.getByText(/Adoção em memória concluída/)).toBeVisible()
    expect(screen.getByRole('slider', { name: 'Matiz' })).toBeDisabled()
    expect(screen.getByText(/Últimos valores observados/)).toBeVisible()
    expect(s.bridge.status).not.toHaveBeenCalled()
    await s.user.click(screen.getByRole('button', { name: 'Atualizar leitura' }))
    expect(s.bridge.status).toHaveBeenCalledExactlyOnceWith('lamp')
    expect(screen.getByRole('slider', { name: 'Matiz' })).toBeEnabled()
  })
  it('preserves a pending lighting intent when recovery readback arrives, then keeps late command stale', async () => {
    const s = await setup(); const c = deferred<ConfirmOutcome>(); const command = deferred<PublicDeviceStatus>()
    s.confirm.mockReturnValue(c.promise); s.bridge.command = vi.fn(() => command.promise)
    await s.adopt()
    fireEvent.change(screen.getByRole('slider', { name: 'Matiz' }), { target: { value: '81' } })
    await act(async () => { c.resolve({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'SUCCEEDED', device: s.lamp } } }) })
    expect(screen.getByRole('slider', { name: 'Matiz' })).toHaveValue('81')
    expect(screen.getByText('Enviando…')).toBeVisible()
    await act(async () => { command.resolve(s.lamp) })
    expect(screen.getByRole('slider', { name: 'Matiz' })).toBeDisabled()
  })
  it('never projects the first device confirmation onto a newly selected device', async () => {
    const s = await setup(); const c = deferred<ConfirmOutcome>(); s.confirm.mockReturnValue(c.promise)
    await s.adopt(); await s.user.click(screen.getByRole('button', { name: 'Fita LED' }))
    await act(async () => { c.resolve({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } } }) })
    expect(screen.queryByText(/Adoção em memória concluída/)).not.toBeInTheDocument()
    expect(screen.getByRole('slider', { name: 'Matiz' })).toBeEnabled()
    await s.user.click(screen.getByRole('button', { name: 'Luz Mesa' }))
    expect(screen.getByText(/Adoção em memória concluída/)).toBeVisible()
    expect(screen.getByRole('slider', { name: 'Matiz' })).toBeDisabled()
  })
  it('surfaces bridge timeout after send as indeterminate and never repeats confirm', async () => {
    const s = await setup()
    const invoke = vi.fn(async (command: string) => {
      if (command === 'bridge_recovery_prepare') return proposal
      throw { code: 'TIMEOUT', message: 'internal diagnostic must not appear' }
    })
    const integration = { ...s.integration, recovery: { ...s.integration.recovery, controller: new TauriManualRecoveryController(invoke) } }
    s.rerender(<App integration={integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await s.user.click(screen.getByRole('button', { name: /Recuperar IP/ }))
    await s.adopt()
    expect(screen.getByText(/adoção pode ter ocorrido/)).toBeVisible()
    expect(screen.getByRole('slider', { name: 'Matiz' })).toBeDisabled()
    expect(screen.queryByText(/internal diagnostic/)).not.toBeInTheDocument()
    expect(invoke).toHaveBeenLastCalledWith('bridge_recovery_confirm', { proposalId: proposal.proposalId })
  })
  it.each([false, true])('runs browser/native MOCK entirely in memory (native=%s)', async (native) => {
    runtime.native = native; runtime.invoke.mockResolvedValue({ mode: 'mock', available: true })
    const user = userEvent.setup(); render(<App />)
    await user.click(await screen.findByRole('button', { name: /Recuperar IP/ }))
    await user.click(screen.getByRole('button', { name: 'Preparar recuperação' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    expect(await screen.findByText(/Adoção em memória concluída/)).toBeVisible()
    expect(runtime.invoke.mock.calls.map(([name]) => name)).toEqual(native ? ['bridge_info'] : [])
  })
  it('uses only fixed invokes in FIXTURE mode and labels simulation (fake native boundary)', async () => {
    runtime.native = true
    runtime.invoke.mockImplementation(async (command: string) => {
      if (command === 'bridge_info') return { mode: 'fixture', available: true }
      if (command === 'bridge_list') return { devices: [publicDevice()] }
      if (command === 'bridge_recovery_prepare') return proposal
      if (command === 'bridge_recovery_confirm') return { recovery: { status: 'ADOPTED' }, readback: { status: 'SUCCEEDED', device: publicDevice() } }
      throw new Error('unexpected native call')
    })
    const user = userEvent.setup(); render(<App />)
    await user.click(await screen.findByRole('button', { name: /Recuperar IP/ }))
    expect(screen.getByText(/Simulação · sem homologação/)).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Preparar recuperação' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    await waitFor(() => expect(screen.getByText(/Leitura recebida/)).toBeVisible())
    expect(runtime.invoke.mock.calls).toEqual([
      ['bridge_info', undefined], ['bridge_list', undefined],
      ['bridge_recovery_prepare', { deviceId: 'lamp' }], ['bridge_recovery_confirm', { proposalId: proposal.proposalId }],
    ])
  })
})
