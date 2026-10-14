import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WindowControls from './WindowControls'
import { hidePanel, isTauriRuntime } from './tauriWindow'

const native = vi.hoisted(() => ({
  isTauri: vi.fn(() => false),
  hide: vi.fn(async () => undefined),
}))

vi.mock('@tauri-apps/api/core', () => ({ isTauri: native.isTauri }))
vi.mock('@tauri-apps/api/window', () => ({ getCurrentWindow: () => ({ hide: native.hide }) }))

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
