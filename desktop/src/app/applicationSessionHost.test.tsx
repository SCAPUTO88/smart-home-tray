import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { StrictMode } from 'react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApplicationSessionHost } from './ApplicationSessionHost'
import LightingApp from './LightingApp'
import { TauriDeviceController, type BridgeApi } from '../features/devices/TauriDeviceController'
import type { ConfirmOutcome, PrepareOutcome } from '../features/recovery/ManualRecoveryController'
import type { DeviceIntegration } from '../features/devices/platformController'
import { deferred, proposal, publicDevice } from '../features/recovery/testSupport'

const runtime = vi.hoisted(() => ({ native: false, invoke: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ isTauri: () => runtime.native, invoke: (command: string, args?: unknown) => runtime.invoke(command, args) }))

function makeIntegration() {
  const lamp = publicDevice()
  const other = publicDevice('other')
  lamp.name = 'Luz Mesa'
  other.name = 'Fita LED'
  const bridge: BridgeApi = { list: vi.fn(async () => [lamp, other]), status: vi.fn(async () => lamp), command: vi.fn(async () => lamp) }
  const lighting = new TauriDeviceController(bridge, 'fixture')
  const prepare = vi.fn<(_: string) => Promise<PrepareOutcome>>(async () => ({ kind: 'terminal', result: proposal }))
  const confirm = vi.fn<(_: string) => Promise<ConfirmOutcome>>(async () => ({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } } }))
  const integration: DeviceIntegration = { lighting, recovery: { controller: { prepare, confirm }, reconciliation: lighting } }
  return { integration, bridge, lighting, prepare, confirm, lamp, other }
}

function makeController(name: string) {
  const lamp = publicDevice(name.toLowerCase().replaceAll(' ', '-'))
  lamp.name = name
  const bridge: BridgeApi = { list: vi.fn(async () => [lamp]), status: vi.fn(async () => lamp), command: vi.fn(async () => lamp) }
  return { lighting: new TauriDeviceController(bridge, 'fixture'), bridge, lamp }
}

function HostedApp({ integration, visible = true, now }: { integration: DeviceIntegration; visible?: boolean; now?: () => number }) {
  return <ApplicationSessionHost integration={integration} now={now}>{visible ? <LightingApp /> : null}</ApplicationSessionHost>
}

async function prepare(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /Recuperar IP/ }))
  await user.click(screen.getByRole('button', { name: 'Preparar recuperação' }))
  await screen.findByRole('button', { name: 'Confirmar recuperação' })
}

async function startConfirm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
  await screen.findByText(/Confirmação em andamento/)
}

describe('application session host', () => {
  it('uses an explicitly supplied controller after the default integration has resolved', async () => {
    runtime.native = true
    runtime.invoke.mockReset().mockResolvedValue({ mode: 'mock', available: true })
    const explicit = makeController('Explicit Lamp')
    const view = render(<StrictMode><ApplicationSessionHost><LightingApp /></ApplicationSessionHost></StrictMode>)
    await screen.findByRole('heading', { name: 'Luz Mesa' })

    view.rerender(<StrictMode><ApplicationSessionHost controller={explicit.lighting}><LightingApp /></ApplicationSessionHost></StrictMode>)

    expect(await screen.findByRole('heading', { name: 'Explicit Lamp' })).toBeVisible()
    expect(explicit.bridge.list).toHaveBeenCalledTimes(1)
    expect(runtime.invoke).toHaveBeenCalledExactlyOnceWith('bridge_info', undefined)
    expect(screen.queryByRole('button', { name: /Recuperar IP/ })).not.toBeInTheDocument()
  })

  it('isolates catalog, selection, and pending operations when switching explicit controllers', async () => {
    const first = makeController('First Lamp')
    const second = makeController('Second Lamp')
    const pending = deferred<ReturnType<typeof publicDevice>>()
    first.bridge.command = vi.fn(() => pending.promise)
    const view = render(<ApplicationSessionHost controller={first.lighting}><LightingApp /></ApplicationSessionHost>)
    await screen.findByRole('heading', { name: 'First Lamp' })
    fireEvent.change(screen.getByRole('slider', { name: 'Matiz' }), { target: { value: '211' } })
    expect(screen.getByRole('slider', { name: 'Matiz' })).toHaveValue('211')

    view.rerender(<ApplicationSessionHost controller={second.lighting}><LightingApp /></ApplicationSessionHost>)
    expect(await screen.findByRole('heading', { name: 'Second Lamp' })).toBeVisible()
    expect(screen.getByRole('slider', { name: 'Matiz' })).toHaveValue(String(second.lamp.state.hsv?.hue ?? 0))
    expect(second.bridge.list).toHaveBeenCalledTimes(1)

    await act(async () => { pending.resolve({ ...first.lamp, state: { ...first.lamp.state, hsv: { hue: 211, saturation: 70, value: 60 } } }) })
    expect(screen.getByRole('heading', { name: 'Second Lamp' })).toBeVisible()
    expect(screen.getByRole('slider', { name: 'Matiz' })).toHaveValue(String(second.lamp.state.hsv?.hue ?? 0))
    expect(screen.queryByText('Atualizado')).not.toBeInTheDocument()
  })

  it('prefers an explicitly supplied integration over a supplied controller', async () => {
    const controller = makeController('Controller Lamp')
    const integration = makeIntegration()
    const view = render(<ApplicationSessionHost controller={controller.lighting}><LightingApp /></ApplicationSessionHost>)
    await screen.findByRole('heading', { name: 'Controller Lamp' })

    view.rerender(<ApplicationSessionHost controller={controller.lighting} integration={integration.integration}><LightingApp /></ApplicationSessionHost>)

    expect(await screen.findByRole('heading', { name: 'Luz Mesa' })).toBeVisible()
    expect(integration.bridge.list).toHaveBeenCalledTimes(1)
    expect(controller.bridge.list).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: /Recuperar IP/ })).toBeVisible()
  })

  it('ignores a late default integration resolution while an explicit source is active', async () => {
    runtime.native = true
    const bridgeInfo = deferred<{ mode: 'mock'; available: boolean }>()
    runtime.invoke.mockReset().mockReturnValue(bridgeInfo.promise)
    const explicit = makeController('Explicit During Resolve')
    const view = render(<ApplicationSessionHost><LightingApp /></ApplicationSessionHost>)
    expect(runtime.invoke).toHaveBeenCalledWith('bridge_info', undefined)
    view.rerender(<ApplicationSessionHost controller={explicit.lighting}><LightingApp /></ApplicationSessionHost>)
    expect(await screen.findByRole('heading', { name: 'Explicit During Resolve' })).toBeVisible()

    await act(async () => { bridgeInfo.resolve({ mode: 'mock', available: true }) })
    expect(screen.getByRole('heading', { name: 'Explicit During Resolve' })).toBeVisible()
    expect(explicit.bridge.list).toHaveBeenCalledTimes(1)
  })

  it('returns to the default origin with a fresh session after an explicit source', async () => {
    runtime.native = true
    runtime.invoke.mockReset().mockResolvedValue({ mode: 'mock', available: true })
    const explicit = makeController('Temporary Lamp')
    const user = userEvent.setup()
    const view = render(<ApplicationSessionHost><LightingApp /></ApplicationSessionHost>)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await prepare(user)
    expect(screen.getByRole('button', { name: 'Confirmar recuperação' })).toBeEnabled()
    view.rerender(<ApplicationSessionHost controller={explicit.lighting}><LightingApp /></ApplicationSessionHost>)
    await screen.findByRole('heading', { name: 'Temporary Lamp' })
    view.rerender(<ApplicationSessionHost><LightingApp /></ApplicationSessionHost>)

    expect(await screen.findByRole('heading', { name: 'Luz Mesa' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: /Recuperar IP/ }))
    expect(screen.getByText(/A busca começa somente ao preparar/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Confirmar recuperação' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Preparar recuperação' })).toBeEnabled()
    expect(screen.queryByText(/Confirmação em andamento|Resultado desconhecido/)).not.toBeInTheDocument()
    expect(runtime.invoke).toHaveBeenCalledExactlyOnceWith('bridge_info', undefined)
  })

  it('keeps a prepared proposal confirmable after the complete lighting UI remounts', async () => {
    const s = makeIntegration()
    const user = userEvent.setup()
    const view = render(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await user.click(screen.getByRole('button', { name: /Recuperar IP/ }))
    await user.click(screen.getByRole('button', { name: 'Preparar recuperação' }))
    expect(await screen.findByRole('button', { name: 'Confirmar recuperação' })).toBeEnabled()

    view.rerender(<HostedApp integration={s.integration} visible={false} />)
    view.rerender(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })

    await user.click(screen.getByRole('button', { name: /Recuperar IP/ }))
    expect(screen.getByRole('button', { name: 'Confirmar recuperação' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    expect(s.confirm).toHaveBeenCalledExactlyOnceWith(proposal.proposalId)
    expect(s.bridge.list).toHaveBeenCalledTimes(1)
  })

  it('reconciles ADOPTED plus FAILED while the UI is unmounted and keeps the same confirmation tracked', async () => {
    const s = makeIntegration()
    const pending = deferred<ConfirmOutcome>()
    s.confirm.mockReturnValue(pending.promise)
    const user = userEvent.setup()
    const view = render(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await prepare(user)
    await startConfirm(user)
    view.rerender(<HostedApp integration={s.integration} visible={false} />)
    await act(async () => { pending.resolve({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } } }) })
    view.rerender(<HostedApp integration={s.integration} />)

    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await user.click(screen.getByRole('button', { name: /Recuperar IP/ }))
    expect(screen.getByText(/Adoção em memória concluída/)).toBeVisible()
    expect(screen.getByRole('slider', { name: 'Matiz' })).toBeDisabled()
    expect(s.confirm).toHaveBeenCalledExactlyOnceWith(proposal.proposalId)
  })

  it('applies an adopted readback to its original Device ID after selection and UI remount change', async () => {
    const s = makeIntegration()
    const pending = deferred<ConfirmOutcome>()
    s.confirm.mockReturnValue(pending.promise)
    const user = userEvent.setup()
    const view = render(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await prepare(user)
    await startConfirm(user)
    await user.click(screen.getByRole('button', { name: 'Fita LED' }))
    view.rerender(<HostedApp integration={s.integration} visible={false} />)
    const readback = { ...s.lamp, state: { ...s.lamp.state, hsv: { hue: 211, saturation: 70, value: 60 } } }
    await act(async () => { pending.resolve({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'SUCCEEDED', device: readback } } }) })
    view.rerender(<HostedApp integration={s.integration} />)

    expect(await screen.findByRole('heading', { name: 'Fita LED' })).toBeVisible()
    expect(screen.getByRole('slider', { name: 'Intensidade RGB' })).toHaveValue('60')
    await user.click(screen.getByRole('button', { name: 'Luz Mesa' }))
    expect(screen.getByRole('slider', { name: 'Matiz' })).toHaveValue('211')
    expect(s.bridge.list).toHaveBeenCalledTimes(1)
  })

  it('keeps an indeterminate confirmation visible after remount without retrying', async () => {
    const s = makeIntegration()
    const pending = deferred<ConfirmOutcome>()
    s.confirm.mockReturnValue(pending.promise)
    const user = userEvent.setup()
    const view = render(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await prepare(user)
    await startConfirm(user)
    view.rerender(<HostedApp integration={s.integration} visible={false} />)
    await act(async () => { pending.resolve({ kind: 'indeterminate', code: 'TIMEOUT' }) })
    view.rerender(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await user.click(screen.getByRole('button', { name: /Recuperar IP/ }))

    expect(screen.getByText(/Resultado desconhecido/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Confirmar recuperação' })).not.toBeInTheDocument()
    expect(s.confirm).toHaveBeenCalledExactlyOnceWith(proposal.proposalId)
  })

  it('keeps the original proposal deadline while the UI is unmounted', async () => {
    const s = makeIntegration()
    let now = 1000
    const clock = () => now
    const user = userEvent.setup()
    const view = render(<HostedApp integration={s.integration} now={clock} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await prepare(user)
    view.rerender(<HostedApp integration={s.integration} visible={false} now={clock} />)
    now = 62_000
    view.rerender(<HostedApp integration={s.integration} now={clock} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await user.click(screen.getByRole('button', { name: /Recuperar IP/ }))

    expect(await screen.findByText(/Proposta expirada ou indisponível/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Confirmar recuperação' })).not.toBeInTheDocument()
    expect(s.prepare).toHaveBeenCalledTimes(1)
    expect(s.confirm).not.toHaveBeenCalled()
  })

  it('preserves a pending lighting intent and reconciles it after remount', async () => {
    const s = makeIntegration()
    const command = deferred<ReturnType<typeof publicDevice>>()
    s.bridge.command = vi.fn(() => command.promise)
    const view = render(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    fireEvent.change(screen.getByRole('slider', { name: 'Matiz' }), { target: { value: '211' } })
    expect(screen.getByRole('slider', { name: 'Matiz' })).toHaveValue('211')
    view.rerender(<HostedApp integration={s.integration} visible={false} />)
    view.rerender(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })

    expect(screen.getByRole('slider', { name: 'Matiz' })).toHaveValue('211')
    expect(s.bridge.command).toHaveBeenCalledTimes(1)
    const readback = { ...s.lamp, state: { ...s.lamp.state, hsv: { hue: 211, saturation: 70, value: 60 } } }
    await act(async () => { command.resolve(readback) })
    expect(screen.getByRole('slider', { name: 'Matiz' })).toHaveValue('211')
    await waitFor(() => expect(view.container.querySelector('.operation-indicator')).toHaveTextContent('Atualizado'))
    expect(s.bridge.list).toHaveBeenCalledTimes(1)
  })

  it('does not move the selected device when an earlier device confirmation completes', async () => {
    const s = makeIntegration()
    const pending = deferred<ConfirmOutcome>()
    s.confirm.mockReturnValue(pending.promise)
    const user = userEvent.setup()
    const view = render(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await prepare(user)
    await startConfirm(user)
    await user.click(screen.getByRole('button', { name: 'Fita LED' }))
    view.rerender(<HostedApp integration={s.integration} visible={false} />)
    await act(async () => { pending.resolve({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } } }) })
    view.rerender(<HostedApp integration={s.integration} />)

    expect(await screen.findByRole('heading', { name: 'Fita LED' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Luz Mesa' }))
    expect(screen.getByRole('slider', { name: 'Matiz' })).toBeDisabled()
    expect(s.confirm).toHaveBeenCalledExactlyOnceWith(proposal.proposalId)
  })

  it('bootstraps one catalog under React StrictMode', async () => {
    const s = makeIntegration()
    render(<StrictMode><ApplicationSessionHost integration={s.integration}><LightingApp /></ApplicationSessionHost></StrictMode>)
    await screen.findByRole('heading', { name: 'Luz Mesa' })

    expect(s.bridge.list).toHaveBeenCalledTimes(1)
  })

  it('resolves the default runtime integration once under React StrictMode', async () => {
    runtime.native = true
    runtime.invoke.mockReset().mockResolvedValue({ mode: 'mock', available: true })
    render(<StrictMode><ApplicationSessionHost><LightingApp /></ApplicationSessionHost></StrictMode>)
    await screen.findByRole('heading', { name: 'Luz Mesa' })

    expect(runtime.invoke).toHaveBeenCalledExactlyOnceWith('bridge_info', undefined)
  })

  it('does not relist and erase stale recovery checkpoints on visual remount', async () => {
    const s = makeIntegration()
    const pending = deferred<ConfirmOutcome>()
    s.confirm.mockReturnValue(pending.promise)
    const user = userEvent.setup()
    const view = render(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await prepare(user)
    await startConfirm(user)
    view.rerender(<HostedApp integration={s.integration} visible={false} />)
    await act(async () => { pending.resolve({ kind: 'indeterminate', code: 'TIMEOUT' }) })
    view.rerender(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })

    expect(s.bridge.list).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('slider', { name: 'Matiz' })).toBeDisabled()
    expect(s.lighting.eligibility('lamp')).toEqual({ status: 'ELIGIBLE', protocolVersion: 3.5 })
    expect(s.confirm).toHaveBeenCalledExactlyOnceWith(proposal.proposalId)
  })

  it('isolates presentation state between independently injected integrations', async () => {
    const first = makeIntegration()
    const second = makeIntegration()
    const user = userEvent.setup()
    render(<div><div data-testid="first"><HostedApp integration={first.integration} /></div><div data-testid="second"><HostedApp integration={second.integration} /></div></div>)
    const firstRoot = within(screen.getByTestId('first'))
    const secondRoot = within(screen.getByTestId('second'))
    await firstRoot.findByRole('heading', { name: 'Luz Mesa' })
    await secondRoot.findByRole('heading', { name: 'Luz Mesa' })
    await user.click(firstRoot.getByRole('button', { name: /Recuperar IP/ }))
    await user.click(firstRoot.getByRole('button', { name: 'Preparar recuperação' }))
    await firstRoot.findByRole('button', { name: 'Confirmar recuperação' })
    await user.click(secondRoot.getByRole('button', { name: /Recuperar IP/ }))

    expect(secondRoot.getByText(/A busca começa somente ao preparar/)).toBeVisible()
    expect(secondRoot.getByRole('button', { name: 'Preparar recuperação' })).toBeEnabled()
    expect(second.prepare).not.toHaveBeenCalled()
  })
})
