import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { DeviceController, LightingDevice } from '../features/devices/types'
import { createMockDeviceController, createMockDevices } from '../mock/MockDeviceController'
import App from './LightingApp'

function renderApp() {
  const user = userEvent.setup()
  render(<App controller={createMockDeviceController({ delayMs: 0 })} />)
  return user
}

describe('Smart Home Tray app', () => {
  it('shows the product and the two simulated devices', async () => {
    renderApp()

    expect(screen.getByRole('heading', { name: 'Smart Home Tray' })).toBeVisible()
    expect(await screen.findByRole('heading', { name: 'Luz Mesa' })).toBeVisible()
    expect(screen.getByText('Conectado · simulação')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Fita LED' })).toBeVisible()
  })

  it('preserves each device preview when switching between devices', async () => {
    const user = renderApp()
    const hue = await screen.findByRole('slider', { name: 'Matiz' })

    fireEvent.change(hue, { target: { value: '195' } })
    expect(hue).toHaveValue('195')

    await user.click(screen.getByRole('button', { name: 'Fita LED' }))
    expect(await screen.findByRole('heading', { name: 'Fita LED' })).toBeVisible()
    await waitFor(() => expect(screen.getByRole('slider', { name: 'Saturação' })).toBeVisible())
    expect(screen.getByRole('slider', { name: 'Intensidade RGB' })).toBeVisible()
    expect(screen.queryByRole('slider', { name: 'Brilho branco' })).not.toBeInTheDocument()
    expect(screen.queryByRole('slider', { name: 'Temperatura de branco' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Luz Mesa' }))
    expect(await screen.findByRole('slider', { name: 'Matiz' })).toHaveValue('195')
  })

  it('updates the color preview immediately as the range value changes', async () => {
    renderApp()
    const hue = await screen.findByRole('slider', { name: 'Matiz' })
    const artwork = screen.getByRole('img', { name: /Ilustração Luz Mesa/ })

    fireEvent.change(hue, { target: { value: '195' } })

    expect(hue).toHaveValue('195')
    expect(artwork).toHaveAttribute('data-hue', '195')
  })

  it('reaches the native hue slider with keyboard tab navigation', async () => {
    const user = renderApp()
    const hue = await screen.findByRole('slider', { name: 'Matiz' })
    for (let index = 0; index < 6; index += 1) await user.tab()

    expect(hue).toHaveFocus()
    expect(hue).toHaveAttribute('type', 'range')
    expect(hue).toHaveAttribute('min', '0')
    expect(hue).toHaveAttribute('max', '360')
  })

  it('toggles power accessibly and dims the illustration', async () => {
    const user = renderApp()
    const power = await screen.findByRole('button', { name: 'Desligar Luz Mesa' })

    expect(power).toHaveAttribute('aria-pressed', 'true')
    await user.click(power)

    expect(await screen.findByRole('button', { name: 'Ligar Luz Mesa' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('img', { name: /Ilustração Luz Mesa/ })).toHaveAttribute('data-powered', 'false')
  })

  it('shows the strip as off without changing its configured RGB intensity', async () => {
    const user = renderApp()
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await user.click(screen.getByRole('button', { name: 'Fita LED' }))
    await screen.findByRole('heading', { name: 'Fita LED' })

    expect(screen.getByRole('slider', { name: 'Intensidade RGB' })).toHaveValue('70')
    await user.click(screen.getByRole('button', { name: 'Desligar Fita LED' }))

    expect(await screen.findByRole('button', { name: 'Ligar Fita LED' })).toHaveAttribute('aria-pressed', 'false')
    const stripStage = await screen.findByRole('region', { name: 'Visualização Fita LED' })
    await waitFor(() => expect(stripStage.querySelector('.stage-value')).toHaveTextContent('Desligada'))
    expect(screen.getByRole('slider', { name: 'Intensidade RGB' })).toHaveValue('70')
  })

  it('switches white and RGB controls by mode', async () => {
    const user = renderApp()
    await screen.findByRole('heading', { name: 'Luz Mesa' })

    await user.click(screen.getByRole('button', { name: 'Branco' }))
    expect(screen.getByTestId('mode-panel')).toHaveAttribute('data-mode', 'white')
    await waitFor(() => expect(screen.getByRole('slider', { name: 'Brilho branco' })).toBeVisible())
    expect(screen.getByRole('slider', { name: 'Temperatura de branco' })).toBeInTheDocument()
    expect(screen.queryByRole('slider', { name: 'Matiz' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'RGB' }))
    expect(screen.getByTestId('mode-panel')).toHaveAttribute('data-mode', 'rgb')
    await waitFor(() => expect(screen.getByRole('slider', { name: 'Intensidade RGB' })).toBeVisible())
  })

  it('updates the rendered brightness immediately without waiting for mock confirmation', async () => {
    renderApp()
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    fireEvent.change(screen.getByRole('slider', { name: 'Intensidade RGB' }), { target: { value: '31' } })

    expect(screen.getByRole('img', { name: /Ilustração Luz Mesa/ })).toHaveAttribute('data-value', '31')
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Atualizado'))
  })

  it('shows pending feedback during a controlled delayed operation, then confirms it', async () => {
    const user = userEvent.setup()
    render(<App controller={createMockDeviceController({ delayMs: 0, delayScenarioMs: 60 })} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await user.selectOptions(screen.getByRole('combobox', { name: 'Resposta simulada' }), 'delay')
    fireEvent.change(screen.getByRole('slider', { name: 'Matiz' }), { target: { value: '205' } })

    expect(screen.getByRole('status')).toHaveTextContent('Enviando')
    expect(screen.getByRole('img', { name: /Ilustração Luz Mesa/ })).toHaveAttribute('data-hue', '205')
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Atualizado'))
  })

  it('keeps a newer preview when command responses arrive out of order', async () => {
    const [lamp] = createMockDevices()
    const pendingResponses: Array<(device: LightingDevice) => void> = []
    const controller: DeviceController = {
      list: async () => createMockDevices(),
      command: async () => new Promise<LightingDevice>((resolve) => pendingResponses.push(resolve)),
    }
    render(<App controller={controller} />)
    await screen.findByRole('heading', { name: 'Luz Mesa' })

    fireEvent.change(screen.getByRole('slider', { name: 'Matiz' }), { target: { value: '195' } })
    fireEvent.change(screen.getByRole('slider', { name: 'Matiz' }), { target: { value: '196' } })
    expect(screen.getByRole('img', { name: /Ilustração Luz Mesa/ })).toHaveAttribute('data-hue', '196')

    const currentResponse = { ...lamp, state: { ...lamp.state, hsv: { ...lamp.state.hsv, hue: 196 } } }
    const oldResponse = { ...lamp, state: { ...lamp.state, hsv: { ...lamp.state.hsv, hue: 195 } } }
    pendingResponses[1](currentResponse)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Atualizado'))
    pendingResponses[0](oldResponse)

    expect(screen.getByRole('img', { name: /Ilustração Luz Mesa/ })).toHaveAttribute('data-hue', '196')
  })

  it('shows textual error feedback when a mock operation fails', async () => {
    const user = renderApp()
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await user.selectOptions(screen.getByRole('combobox', { name: 'Resposta simulada' }), 'error')
    fireEvent.change(screen.getByRole('slider', { name: 'Matiz' }), { target: { value: '195' } })

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Não foi possível atualizar'))
    expect(screen.getByRole('slider', { name: 'Matiz' })).toHaveValue('194')
    expect(screen.getByRole('img', { name: /Ilustração Luz Mesa/ })).toHaveAttribute('data-hue', '194')
  })

  it('shows canceled and offline results without claiming confirmation', async () => {
    const user = renderApp()
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    const scenario = screen.getByRole('combobox', { name: 'Resposta simulada' })

    await user.selectOptions(scenario, 'canceled')
    fireEvent.change(screen.getByRole('slider', { name: 'Matiz' }), { target: { value: '195' } })
    expect(await screen.findByRole('alert')).toHaveTextContent('Operação cancelada')
    expect(screen.getByRole('slider', { name: 'Matiz' })).toHaveValue('194')

    await user.selectOptions(scenario, 'offline')
    fireEvent.change(screen.getByRole('slider', { name: 'Matiz' }), { target: { value: '196' } })
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Offline'))
  })

  it('tracks white temperature in the visible bulb color', async () => {
    renderApp()
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    await userEvent.setup().click(screen.getByRole('button', { name: 'Branco' }))
    const artwork = screen.getByRole('img', { name: /Ilustração Luz Mesa/ })
    const shell = screen.getByRole('main')
    const temperature = await screen.findByRole('slider', { name: 'Temperatura de branco' })

    fireEvent.change(temperature, { target: { value: '0' } })
    expect(artwork.style.getPropertyValue('--lamp-color')).toBe('rgb(255 174 100)')
    expect(shell.style.getPropertyValue('--accent-color')).toBe('rgb(255 174 100)')
    fireEvent.change(temperature, { target: { value: '100' } })
    expect(artwork.style.getPropertyValue('--lamp-color')).toBe('rgb(205 225 255)')
    expect(shell.style.getPropertyValue('--accent-color')).toBe('rgb(205 225 255)')
  })

  it('removes the ambient card tint when the light is switched off', async () => {
    const user = renderApp()
    await screen.findByRole('heading', { name: 'Luz Mesa' })
    const shell = screen.getByRole('main')
    expect(shell.style.getPropertyValue('--accent-intensity')).toBe('0.82')
    await user.click(screen.getByRole('button', { name: 'Desligar Luz Mesa' }))
    await screen.findByRole('button', { name: 'Ligar Luz Mesa' })
    expect(shell.style.getPropertyValue('--accent-intensity')).toBe('0')
  })
})
