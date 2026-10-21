import type { PublicDeviceStatus } from '../devices/publicDeviceMapper'

export const publicDevice = (deviceId = 'lamp'): PublicDeviceStatus => ({
  deviceId, name: 'Synthetic lamp', address: '192.0.2.1', protocolVersion: 3.5,
  capabilities: { power: true, whiteBrightness: true, colorValue: true, colorTemperature: true, scenes: false },
  connection: 'online',
  state: { power: true, workMode: 'colour', whiteBrightnessPercent: 40, colorValuePercent: 60, colorTemperaturePercent: 50,
    hsv: { hue: 120, saturation: 70, value: 60 }, scene: null, quality: 'confirmed',
    knowledge: { power: 'observed', workMode: 'observed', whiteBrightness: 'observed', colorTemperature: 'observed', hsv: 'observed', colorValue: 'observed', scene: 'unknown' } },
})
export const proposal = { status: 'PROPOSAL_READY' as const, proposalId: 'A'.repeat(43), candidateIp: '198.51.100.35', ttlSeconds: 60 }
export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

