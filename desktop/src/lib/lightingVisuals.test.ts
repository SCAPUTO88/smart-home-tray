import { describe, expect, it } from 'vitest'
import { lightingIntensity, selectedLightingColor } from './lightingVisuals'
import type { DeviceState } from '../features/devices/types'

function state(overrides: Partial<DeviceState> = {}): DeviceState {
  return {
    enabled: true,
    mode: 'rgb',
    hsv: { hue: 180, saturation: 100, value: 50 },
    whiteBrightness: 50,
    whiteTemperature: 50,
    quality: 'confirmed',
    ...overrides,
  }
}

describe('lighting presentation', () => {
  it('maps HSV cyan and purple to their selected emission colors', () => {
    expect(selectedLightingColor(state())).toBe('rgb(0 128 128)')
    expect(selectedLightingColor(state({ hsv: { hue: 270, saturation: 100, value: 80 } }))).toBe('rgb(102 0 204)')
  })

  it('interpolates white temperature from warm through neutral to cool', () => {
    const white = (whiteTemperature: number) => selectedLightingColor(state({ mode: 'white', whiteTemperature }))
    expect(white(0)).toBe('rgb(255 174 100)')
    expect(white(50)).toBe('rgb(255 244 229)')
    expect(white(100)).toBe('rgb(205 225 255)')
  })

  it('uses the active mode brightness as normalized emission intensity', () => {
    expect(lightingIntensity(state())).toBe(0.5)
    expect(lightingIntensity(state({ mode: 'white', whiteBrightness: 12 }))).toBe(0.12)
  })

  it('turns off all emission while retaining the selected color', () => {
    const off = state({ enabled: false })
    expect(selectedLightingColor(off)).toBe('rgb(0 128 128)')
    expect(lightingIntensity(off)).toBe(0)
  })

  it('clamps normalized intensity and white temperature inputs', () => {
    expect(lightingIntensity(state({ hsv: { hue: 180, saturation: 100, value: 140 } }))).toBe(1)
    expect(lightingIntensity(state({ hsv: { hue: 180, saturation: 100, value: -8 } }))).toBe(0)
    expect(selectedLightingColor(state({ mode: 'white', whiteTemperature: -10 }))).toBe('rgb(255 174 100)')
    expect(selectedLightingColor(state({ mode: 'white', whiteTemperature: 110 }))).toBe('rgb(205 225 255)')
  })
})
