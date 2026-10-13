import type { HsvColor } from '../features/devices/types'

export interface RgbColor {
  r: number
  g: number
  b: number
}

export function hsvToRgb({ hue, saturation, value }: HsvColor): RgbColor {
  const h = ((hue % 360) + 360) % 360 / 60
  const s = Math.min(100, Math.max(0, saturation)) / 100
  const v = Math.min(100, Math.max(0, value)) / 100
  const chroma = v * s
  const secondary = chroma * (1 - Math.abs((h % 2) - 1))
  const match = v - chroma
  const sector = Math.floor(h)
  const channels = sector === 0 ? [chroma, secondary, 0]
    : sector === 1 ? [secondary, chroma, 0]
      : sector === 2 ? [0, chroma, secondary]
        : sector === 3 ? [0, secondary, chroma]
          : sector === 4 ? [secondary, 0, chroma]
            : [chroma, 0, secondary]

  return {
    r: Math.round((channels[0] + match) * 255),
    g: Math.round((channels[1] + match) * 255),
    b: Math.round((channels[2] + match) * 255),
  }
}

export function rgbCss(color: RgbColor): string {
  return `rgb(${color.r} ${color.g} ${color.b})`
}
