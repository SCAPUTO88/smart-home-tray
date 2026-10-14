import { describe, expect, it } from 'vitest'
import { hsvToRgb } from './color'

describe('hsvToRgb', () => {
  it('converts the primary hue values with normalized HSV percentages', () => {
    expect(hsvToRgb({ hue: 0, saturation: 100, value: 100 })).toEqual({ r: 255, g: 0, b: 0 })
    expect(hsvToRgb({ hue: 120, saturation: 100, value: 100 })).toEqual({ r: 0, g: 255, b: 0 })
    expect(hsvToRgb({ hue: 240, saturation: 100, value: 100 })).toEqual({ r: 0, g: 0, b: 255 })
  })

  it('applies Value as real channel intensity and saturation as the white mix', () => {
    expect(hsvToRgb({ hue: 0, saturation: 100, value: 25 })).toEqual({ r: 64, g: 0, b: 0 })
    expect(hsvToRgb({ hue: 0, saturation: 0, value: 50 })).toEqual({ r: 128, g: 128, b: 128 })
  })
})
