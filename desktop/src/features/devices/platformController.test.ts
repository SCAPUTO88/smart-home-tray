import { beforeEach, describe, expect, it, vi } from 'vitest'

const runtime = vi.hoisted(() => ({
  native: false,
  info: { mode: 'mock', available: true, error: null } as { mode: 'mock' | 'fixture' | 'real'; available: boolean; error: unknown },
  invoke: vi.fn(),
}))
vi.mock('@tauri-apps/api/core', () => ({ isTauri: () => runtime.native, invoke: (command: string) => runtime.invoke(command) }))
import { resolveDeviceController } from './platformController'

describe('platform controller selection', () => {
  beforeEach(() => { runtime.native = false; runtime.info = { mode: 'mock', available: true, error: null }; runtime.invoke.mockReset() })
  it('preserves browser mock without native IPC calls', async () => {
    const controller = await resolveDeviceController()
    expect(controller.mode).toBe('mock')
    expect(await controller.list()).toHaveLength(2)
    expect(runtime.invoke).not.toHaveBeenCalled()
  })
  it('uses explicit fixture only when the Rust process reports it', async () => {
    runtime.native = true
    runtime.info = { mode: 'fixture', available: true, error: null }
    runtime.invoke.mockResolvedValue(runtime.info)
    const controller = await resolveDeviceController()
    expect(controller.mode).toBe('fixture')
    expect(runtime.invoke).toHaveBeenCalledWith('bridge_info')
  })
  it('does not silently fall back when an explicitly selected backend fails', async () => {
    runtime.native = true
    runtime.info = { mode: 'real', available: false, error: { code: 'DEVICE_ERROR' } }
    runtime.invoke.mockResolvedValue(runtime.info)
    await expect(resolveDeviceController()).rejects.toEqual({ code: 'DEVICE_ERROR' })
  })
  it('surfaces a bridge bootstrap rejection', async () => {
    runtime.native = true
    runtime.invoke.mockRejectedValue(new Error('native bridge unavailable'))
    await expect(resolveDeviceController()).rejects.toThrow('native bridge unavailable')
  })
})
