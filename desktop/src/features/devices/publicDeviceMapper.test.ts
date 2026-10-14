import { describe, expect, it } from 'vitest'
import { mapPublicDevice } from './publicDeviceMapper'

const source = {
  deviceId: 'lamp-1', name: 'Desk', address: 'private', protocolVersion: 3.3,
  capabilities: { power: true, whiteBrightness: true, colorValue: true, colorTemperature: true, scenes: false },
  connection: 'online', state: { power: true, workMode: 'colour', whiteBrightnessPercent: 40, colorValuePercent: 72, colorTemperaturePercent: 50, hsv: { hue: 210, saturation: 80, value: 72 }, scene: null, quality: 'confirmed', knowledge: { power: 'observed', workMode: 'observed', whiteBrightness: 'observed', colorTemperature: 'observed', hsv: 'observed', colorValue: 'observed', scene: 'unknown' } },
} as const

describe('public device mapper', () => {
  it('maps capabilities and confirmed HSV without exposing private backend fields', () => {
    const device = mapPublicDevice(source)
    expect(device).toMatchObject({ deviceId: 'lamp-1', kind: 'bulb', capabilities: { power: true, rgb: true, white: true, temperature: true }, state: { mode: 'rgb', enabled: true, hsv: { hue: 210, saturation: 80, value: 72 }, quality: 'confirmed' } })
    expect(device).not.toHaveProperty('address')
    expect(device).not.toHaveProperty('protocolVersion')
  })
  it('derives strip capability without relying on its display name', () => {
    const device = mapPublicDevice({ ...source, name: 'Desk', capabilities: { ...source.capabilities, whiteBrightness: false, colorTemperature: false }, state: { ...source.state, whiteBrightnessPercent: null, colorTemperaturePercent: null } })
    expect(device.kind).toBe('led-strip')
    expect(device.capabilities).toMatchObject({ rgb: true, white: false, temperature: false })
  })
  it('preserves nulls as unknown quality and connection', () => {
    const device = mapPublicDevice({ ...source, connection: 'unknown', state: { ...source.state, power: null, hsv: null, quality: 'confirmed', knowledge: { ...source.state.knowledge, power: 'unknown', hsv: 'unknown', colorValue: 'unknown' } } })
    expect(device.connection).toBe('unknown')
    expect(device.state.quality).toBe('unknown')
  })
  it('maps backend quality and white mode explicitly', () => {
    const device = mapPublicDevice({ ...source, state: { ...source.state, workMode: 'white', quality: 'pending' } })
    expect(device.state.mode).toBe('white')
    expect(device.state.quality).toBe('pending')
  })

  it('does not infer field knowledge from non-null fallback values', () => {
    const device = mapPublicDevice({ ...source, state: { ...source.state, knowledge: { ...source.state.knowledge, hsv: 'unknown', colorValue: 'unknown' } } })
    expect(device.state.hsv).toEqual({ hue: 210, saturation: 80, value: 72 })
    expect(device.state.knowledge.hsv).toBe('unknown')
    expect(device.state.knowledge.colorValue).toBe('unknown')
  })

})
