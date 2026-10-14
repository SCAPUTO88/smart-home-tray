import type { DeviceState } from '../features/devices/types'
import { hsvToRgb, rgbCss, type RgbColor } from './color'

const WHITE_TEMPERATURE_STOPS: readonly [number, RgbColor][] = [
  [0, { r: 255, g: 174, b: 100 }],
  [50, { r: 255, g: 244, b: 229 }],
  [100, { r: 205, g: 225, b: 255 }],
]

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value))
}

function interpolateColor(from: RgbColor, to: RgbColor, amount: number): RgbColor {
  return {
    r: Math.round(from.r + (to.r - from.r) * amount),
    g: Math.round(from.g + (to.g - from.g) * amount),
    b: Math.round(from.b + (to.b - from.b) * amount),
  }
}

function whiteTemperatureColor(temperature: number): RgbColor {
  const value = clampPercent(temperature)
  const [lower, upper] = value <= 50
    ? [WHITE_TEMPERATURE_STOPS[0], WHITE_TEMPERATURE_STOPS[1]]
    : [WHITE_TEMPERATURE_STOPS[1], WHITE_TEMPERATURE_STOPS[2]]
  const amount = (value - lower[0]) / (upper[0] - lower[0])
  return interpolateColor(lower[1], upper[1], amount)
}

export function selectedLightingColor(state: DeviceState): string {
  return rgbCss(state.mode === 'rgb' ? hsvToRgb(state.hsv) : whiteTemperatureColor(state.whiteTemperature))
}

export function lightingIntensity(state: DeviceState): number {
  if (!state.enabled) return 0
  const brightness = state.mode === 'rgb' ? state.hsv.value : state.whiteBrightness
  return clampPercent(brightness) / 100
}
