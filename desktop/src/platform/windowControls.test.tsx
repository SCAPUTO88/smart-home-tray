import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LightingApp from '../app/LightingApp'
import WindowControls from './WindowControls'
import { hidePanel, isTauriRuntime, startDraggingPanel } from './tauriWindow'

const native = vi.hoisted(() => ({
  isTauri: vi.fn(() => false),
  hide: vi.fn(async () => undefined),
  startDragging: vi.fn(async () => undefined),
}))

vi.mock('@tauri-apps/api/core', () => ({ isTauri: native.isTauri }))
vi.mock('@tauri-apps/api/window', () => ({ getCurrentWindow: () => ({ hide: native.hide, startDragging: native.startDragging }) }))

describe('Tauri window controls', () => {
  beforeEach(() => {
    native.isTauri.mockReset().mockReturnValue(false)
    native.hide.mockClear()
  })

  it('identifies browser and Tauri runtimes', () => {
    expect(isTauriRuntime()).toBe(false)
    native.isTauri.mockReturnValue(true)
    expect(isTauriRuntime()).toBe(true)
  })

  it('does not expose or invoke native window controls in a browser', async () => {
    render(<WindowControls />)
    expect(screen.queryByRole('button', { name: 'Ocultar painel' })).not.toBeInTheDocument()
    expect(await hidePanel()).toBe(false)
    expect(native.hide).not.toHaveBeenCalled()
  })

  it('exposes an accessible hide action in Tauri', () => {
    native.isTauri.mockReturnValue(true)
    render(<WindowControls />)
    fireEvent.click(screen.getByRole('button', { name: 'Ocultar painel' }))
    expect(native.hide).toHaveBeenCalledOnce()
  })
})

describe('frameless header dragging', () => {
  beforeEach(() => {
    native.isTauri.mockReset().mockReturnValue(false)
    native.startDragging.mockClear()
  })

  it('does not call native dragging from the browser', async () => {
    expect(await startDraggingPanel(document.createElement('div'), 0)).toBe(false)
    expect(native.startDragging).not.toHaveBeenCalled()
  })

  it('starts native dragging from the app header in Tauri', async () => {
    native.isTauri.mockReturnValue(true)
    render(<LightingApp />)
    fireEvent.mouseDown(screen.getByRole('banner'), { button: 0 })
    await waitFor(() => expect(native.startDragging).toHaveBeenCalledOnce())
  })

  it('does not start dragging from interactive header controls', async () => {
    native.isTauri.mockReturnValue(true)
    render(<LightingApp />)
    const hide = await screen.findByRole('button', { name: 'Ocultar painel' })
    fireEvent.mouseDown(hide, { button: 0 })
    expect(native.startDragging).not.toHaveBeenCalled()
  })

  it('ignores non-primary mouse buttons', async () => {
    native.isTauri.mockReturnValue(true)
    expect(await startDraggingPanel(document.createElement('div'), 2)).toBe(false)
    expect(native.startDragging).not.toHaveBeenCalled()
  })
})
