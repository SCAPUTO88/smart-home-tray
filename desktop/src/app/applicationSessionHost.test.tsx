import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { StrictMode, useState } from 'react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApplicationSessionHost } from './ApplicationSessionHost'
import { useApplicationSession } from './ApplicationSessionContext'
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

function SessionProbe() {
  const session = useApplicationSession()
  const [commandResult, setCommandResult] = useState('')
  if (!session || session.status !== 'ready') return <output data-testid="session-probe">loading</output>
  const view = session.session.selectedView
  return <>
    <output data-testid="session-probe">{JSON.stringify({
      selectedDeviceId: session.session.selectedDeviceId,
      confirmed: view ? { ...view.confirmed.knowledge, hsv: view.confirmed.hsv, hsvKnowledge: view.confirmed.knowledge.hsv, quality: view.confirmed.quality } : undefined,
      preview: view ? { ...view.preview.knowledge, hsv: view.preview.hsv, hsvKnowledge: view.preview.knowledge.hsv, quality: view.preview.quality } : undefined,
      pendingOperations: view?.pendingOperations.length,
      devices: Object.fromEntries(session.session.devices.map((device) => [device.deviceId, device.state.knowledge])),
      eligibility: session.session.recoveryEligibility('lamp'),
    })}</output>
    <button type="button" onClick={() => void session.controller.command('lamp', { hsv: { hue: 222 } }).then(() => setCommandResult('accepted'), (error: { code?: string }) => setCommandResult(error.code ?? 'failed'))}>Probe confirmed base</button>
    <button type="button" onClick={() => void session.controller.command('other', { hsv: { hue: 223 } }).then(() => setCommandResult('other-accepted'), (error: { code?: string }) => setCommandResult(error.code ?? 'failed'))}>Probe other device</button>
    <button type="button" onClick={() => session.session.issue('lamp', { hsv: { hue: 211 } }, 'success')}>Issue pending intent</button>
    <output data-testid="command-probe">{commandResult}</output>
  </>
}

function setupDefaultFixture(pendingConfirm: ReturnType<typeof deferred<unknown>>, pendingCommand?: ReturnType<typeof deferred<unknown>>) {
  runtime.native = true
  const lamp = publicDevice()
  const other = publicDevice('other')
  runtime.invoke.mockReset().mockImplementation(async (command: string, args?: unknown) => {
    if (command === 'bridge_info') return { mode: 'fixture', available: true }
    if (command === 'bridge_list') return { devices: [lamp, other] }
    if (command === 'bridge_recovery_prepare') return proposal
    if (command === 'bridge_recovery_confirm') return pendingConfirm.promise
    if (command === 'bridge_hsv') return pendingCommand?.promise ?? (args && typeof args === 'object' && 'deviceId' in args && args.deviceId === 'other' ? other : lamp)
    throw new Error(`Unexpected bridge command ${command}`)
  })
  return { lamp, other }
}

async function beginDefaultConfirmAcrossSourceSwitch(pendingConfirm: ReturnType<typeof deferred<unknown>>, strictMode = false, pendingCommand?: ReturnType<typeof deferred<unknown>>) {
  const devices = setupDefaultFixture(pendingConfirm, pendingCommand)
  const explicit = makeController('Explicit Lamp')
  const user = userEvent.setup()
  const host = (controller?: ReturnType<typeof makeController>['lighting']) => {
    const tree = <ApplicationSessionHost controller={controller}><><LightingApp /><SessionProbe /></></ApplicationSessionHost>
    return strictMode ? <StrictMode>{tree}</StrictMode> : tree
  }
  const view = render(host())
  await screen.findByRole('heading', { name: 'Synthetic lamp' })
  await waitFor(() => expect(JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}').confirmed.power).toBe('observed'))
  await prepare(user)
  await startConfirm(user)
  view.rerender(host(explicit.lighting))
  await screen.findByRole('heading', { name: 'Explicit Lamp' })
  view.rerender(host())
  await screen.findByRole('heading', { name: 'Synthetic lamp' })
  return { view, user, explicit, ...devices }
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
  it('reconciles an old default confirmation before a returning session can relist the controller', async () => {
    runtime.native = true
    const pendingConfirm = deferred<unknown>()
    const lamp = publicDevice()
    const other = publicDevice('other')
    runtime.invoke.mockReset().mockImplementation(async (command: string, args?: unknown) => {
      if (command === 'bridge_info') return { mode: 'fixture', available: true }
      if (command === 'bridge_list') return { devices: [lamp, other] }
      if (command === 'bridge_recovery_prepare') return proposal
      if (command === 'bridge_recovery_confirm') return pendingConfirm.promise
      if (command === 'bridge_hsv') return args && typeof args === 'object' && 'deviceId' in args && args.deviceId === 'other' ? other : lamp
      throw new Error(`Unexpected bridge command ${command}`)
    })
    const explicit = makeController('Explicit Lamp')
    const user = userEvent.setup()
    const view = render(<StrictMode><ApplicationSessionHost><><LightingApp /><SessionProbe /></></ApplicationSessionHost></StrictMode>)
    await screen.findByRole('heading', { name: 'Synthetic lamp' })
    await waitFor(() => expect(JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}').confirmed.power).toBe('observed'))
    await prepare(user)
    await startConfirm(user)

    view.rerender(<StrictMode><ApplicationSessionHost controller={explicit.lighting}><><LightingApp /><SessionProbe /></></ApplicationSessionHost></StrictMode>)
    await screen.findByRole('heading', { name: 'Explicit Lamp' })
    view.rerender(<StrictMode><ApplicationSessionHost><><LightingApp /><SessionProbe /></></ApplicationSessionHost></StrictMode>)
    await screen.findByRole('heading', { name: 'Synthetic lamp' })
    expect(runtime.invoke.mock.calls.filter(([command]) => command === 'bridge_list')).toHaveLength(1)
    expect(JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}').confirmed.power).toBe('observed')

    await act(async () => { pendingConfirm.resolve({ recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } }) })

    await waitFor(() => expect(JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}').confirmed.power).toBe('stale'))
    const snapshot = JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}')
    expect(snapshot.preview.power).toBe('stale')
    expect(snapshot.confirmed.quality).toBe('unknown')
    expect(snapshot.preview.quality).toBe('unknown')
    expect(snapshot.selectedDeviceId).toBe('lamp')
    expect(snapshot.eligibility).toEqual({ status: 'ELIGIBLE', protocolVersion: 3.5 })
    await user.click(screen.getByRole('button', { name: 'Probe confirmed base' }))
    await waitFor(() => expect(screen.getByTestId('command-probe')).toHaveTextContent('DEVICE_ERROR'))
    expect(runtime.invoke.mock.calls.filter(([command]) => command === 'bridge_hsv')).toHaveLength(0)
    expect(screen.getByTestId('session-probe')).toHaveTextContent('stale')
    await user.click(screen.getByRole('button', { name: /Recuperar IP/ }))
    expect(screen.getByText(/Adoção em memória concluída/)).toBeVisible()
    expect(screen.getByRole('button', { name: /Recuperar IP/ })).toBeVisible()
    expect(runtime.invoke.mock.calls.filter(([command]) => command === 'bridge_recovery_confirm')).toHaveLength(1)
    expect(snapshot.devices.other.power).toBe('observed')
    await user.click(screen.getByRole('button', { name: 'Probe other device' }))
    await waitFor(() => expect(screen.getByTestId('command-probe')).toHaveTextContent('other-accepted'))
    expect(runtime.invoke.mock.calls.filter(([command, args]) => command === 'bridge_hsv' && args?.deviceId === 'other')).toHaveLength(1)
  })

  it.each([
    { name: 'ADOPTED plus SUPERSEDED', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'SUPERSEDED' } }, expected: 'stale' },
    { name: 'ADOPTED plus SUCCEEDED without a device', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'SUCCEEDED' } }, expected: 'stale' },
    { name: 'indeterminate', result: null, expected: 'stale' },
  ])('retains the old source checkpoint across switching for $name', async ({ name: _name, result, expected }) => {
    const pendingConfirm = deferred<unknown>()
    const s = await beginDefaultConfirmAcrossSourceSwitch(pendingConfirm)
    if (result) await act(async () => { pendingConfirm.resolve(result) })
    else await act(async () => { pendingConfirm.reject({ code: 'TIMEOUT' }) })

    await waitFor(() => expect(JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}').confirmed.power).toBe(expected))
    const snapshot = JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}')
    expect(snapshot.preview.power).toBe(expected)
    expect(snapshot.confirmed.hsv).toEqual({ hue: 120, saturation: 70, value: 60 })
    expect(snapshot.confirmed.quality).toBe('unknown')
    expect(snapshot.selectedDeviceId).toBe('lamp')
    expect(snapshot.devices.other.power).toBe('observed')
    expect(runtime.invoke.mock.calls.filter(([command]) => command === 'bridge_list')).toHaveLength(1)
    expect(runtime.invoke.mock.calls.filter(([command]) => command === 'bridge_recovery_confirm')).toHaveLength(1)
    await s.user.click(screen.getByRole('button', { name: 'Probe confirmed base' }))
    await waitFor(() => expect(screen.getByTestId('command-probe')).toHaveTextContent('DEVICE_ERROR'))
    expect(runtime.invoke.mock.calls.filter(([command]) => command === 'bridge_hsv')).toHaveLength(0)
  })

  it('uses only the old source recovery readback when confirm finishes before that source is reactivated', async () => {
    const pendingConfirm = deferred<unknown>()
    setupDefaultFixture(pendingConfirm)
    const explicit = makeController('Explicit Lamp')
    const user = userEvent.setup()
    const host = (controller?: typeof explicit.lighting) => <ApplicationSessionHost controller={controller}><><LightingApp /><SessionProbe /></></ApplicationSessionHost>
    const view = render(host())
    await screen.findByRole('heading', { name: 'Synthetic lamp' })
    await prepare(user)
    await startConfirm(user)
    view.rerender(host(explicit.lighting))
    await screen.findByRole('heading', { name: 'Explicit Lamp' })
    await act(async () => { pendingConfirm.resolve({ recovery: { status: 'ADOPTED' }, readback: { status: 'SUCCEEDED', device: { ...publicDevice(), state: { ...publicDevice().state, hsv: { hue: 245, saturation: 70, value: 60 }, colorValuePercent: 60 } } } }) })
    expect(screen.getByRole('heading', { name: 'Explicit Lamp' })).toBeVisible()
    const explicitSnapshot = JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}')
    expect(explicitSnapshot.selectedDeviceId).toBe('explicit-lamp')
    expect(explicitSnapshot.confirmed.power).toBe('observed')

    view.rerender(host())
    await screen.findByRole('heading', { name: 'Synthetic lamp' })
    const snapshot = JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}')
    expect(snapshot.confirmed.hsv.hue).toBe(245)
    expect(snapshot.confirmed.hsv).toMatchObject({ hue: 245 })
    expect(snapshot.selectedDeviceId).toBe('lamp')
    expect(runtime.invoke.mock.calls.filter(([command]) => command === 'bridge_list')).toHaveLength(1)
    expect(runtime.invoke.mock.calls.filter(([command]) => command === 'bridge_recovery_confirm')).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: 'Probe confirmed base' }))
    await waitFor(() => expect(screen.getByTestId('command-probe')).toHaveTextContent('accepted'))
    expect(runtime.invoke.mock.calls.filter(([command, args]) => command === 'bridge_hsv' && args && typeof args === 'object' && 'hue' in args && args.hue === 222)).toHaveLength(1)
  })

  it('preserves a concurrent lighting intent across the confirmation source switch and causal barrier', async () => {
    const pendingConfirm = deferred<unknown>()
    const pendingCommand = deferred<unknown>()
    setupDefaultFixture(pendingConfirm, pendingCommand)
    const explicit = makeController('Explicit Lamp')
    const user = userEvent.setup()
    const host = (controller?: typeof explicit.lighting) => <ApplicationSessionHost controller={controller}><><LightingApp /><SessionProbe /></></ApplicationSessionHost>
    const view = render(host())
    await screen.findByRole('heading', { name: 'Synthetic lamp' })
    await prepare(user)
    await startConfirm(user)
    await user.click(screen.getByRole('button', { name: 'Issue pending intent' }))
    expect(JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}').pendingOperations).toBe(1)
    expect(JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}').preview.hsv.hue).toBe(211)
    view.rerender(host(explicit.lighting))
    await screen.findByRole('heading', { name: 'Explicit Lamp' })
    view.rerender(host())
    await screen.findByRole('heading', { name: 'Synthetic lamp' })
    expect(runtime.invoke.mock.calls.filter(([command]) => command === 'bridge_list')).toHaveLength(1)

    await act(async () => { pendingConfirm.resolve({ recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } }) })
    expect(JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}').pendingOperations).toBe(1)
    expect(JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}').preview.hsv.hue).toBe(211)
    await act(async () => { pendingCommand.resolve(publicDevice()) })

    const snapshot = JSON.parse(screen.getByTestId('session-probe').textContent ?? '{}')
    expect(snapshot.pendingOperations).toBe(0)
    expect(snapshot.confirmed.hsv).toMatchObject({ hue: 120 })
    expect(snapshot.confirmed.hsvKnowledge).toBe('stale')
    expect(runtime.invoke.mock.calls.filter(([command]) => command === 'bridge_recovery_confirm')).toHaveLength(1)
  })

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

  it('replaces an earlier successful operation indicator when recovery makes current knowledge stale', async () => {
    const s = makeIntegration()
    s.confirm.mockResolvedValue({ kind: 'terminal', result: { recovery: { status: 'ADOPTED' }, readback: { status: 'FAILED' } } })
    const user = userEvent.setup()
    render(<HostedApp integration={s.integration} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    fireEvent.change(screen.getByRole('slider', { name: 'Matiz' }), { target: { value: '205' } })
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Atualizado'))
    await prepare(user)
    await user.click(screen.getByRole('button', { name: 'Confirmar recuperação' }))
    await waitFor(() => expect(screen.getByTestId('recovery-state')).toHaveTextContent('leitura realizada imediatamente após a recuperação falhou'))
    expect(screen.getByRole('status')).toHaveTextContent('Atualização necessária')
    expect(screen.getByRole('slider', { name: 'Matiz' })).toBeDisabled()
    expect(document.querySelector('.operation-indicator')).toHaveClass('is-idle')
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
