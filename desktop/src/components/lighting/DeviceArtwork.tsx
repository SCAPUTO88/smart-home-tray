import { motion } from 'motion/react'
import type { CSSProperties } from 'react'
import type { LightingDevice, DeviceState } from '../../features/devices/types'
import { hsvToRgb, rgbCss } from '../../lib/color'

interface DeviceArtworkProps {
  device: LightingDevice
  state: DeviceState
}

function selectedColor(state: DeviceState): string {
  if (state.mode === 'rgb') return rgbCss(hsvToRgb(state.hsv))
  const warmth = state.whiteTemperature / 100
  const red = 255
  const green = Math.round(183 + warmth * 53)
  const blue = Math.round(115 + warmth * 140)
  return `rgb(${red} ${green} ${blue})`
}

export function DeviceArtwork({ device, state }: DeviceArtworkProps) {
  const color = selectedColor(state)
  const intensity = state.enabled ? (state.mode === 'rgb' ? state.hsv.value : state.whiteBrightness) / 100 : 0
  const style = { '--lamp-color': color, '--lamp-intensity': intensity } as CSSProperties

  return (
    <motion.div
      className={`device-art device-art--${device.kind}${state.enabled ? ' is-on' : ' is-off'}`}
      style={style}
      role="img"
      aria-label={`Ilustração ${device.name}`}
      data-hue={state.hsv.hue}
      data-value={state.mode === 'rgb' ? state.hsv.value : state.whiteBrightness}
      data-powered={state.enabled ? 'true' : 'false'}
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <div className="art-glow" />
      {device.kind === 'bulb' ? (
        <svg className="bulb-svg" viewBox="0 0 240 260" aria-hidden="true">
          <defs>
            <linearGradient id="bulb-glass" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0" stopColor="#f8fbff" stopOpacity=".95" />
              <stop offset=".48" stopColor="#aebdd0" stopOpacity=".42" />
              <stop offset="1" stopColor="#718099" stopOpacity=".78" />
            </linearGradient>
            <linearGradient id="bulb-base" x1="0" x2="1">
              <stop offset="0" stopColor="#64738a" />
              <stop offset=".5" stopColor="#d9e2ee" />
              <stop offset="1" stopColor="#68778d" />
            </linearGradient>
          </defs>
          <ellipse className="bulb-reflection" cx="120" cy="95" rx="68" ry="72" />
          <path className="bulb-glass" fill="url(#bulb-glass)" d="M120 20c-43 0-77 34-77 76 0 27 12 46 30 65 9 10 15 21 18 33h58c3-12 9-23 18-33 18-19 30-38 30-65 0-42-34-76-77-76Z" />
          <path className="bulb-core" d="M91 116c14 10 44 10 58 0m-51 15c11 8 33 8 44 0" />
          <path className="bulb-neck" d="M91 194h58v16c0 5-4 9-9 9h-40c-5 0-9-4-9-9v-16Z" />
          <path className="bulb-screw" d="M92 222h56m-52 9h48m-42 8h36m-30 8h24" />
          <ellipse className="bulb-foot" cx="120" cy="253" rx="12" ry="3" />
        </svg>
      ) : (
        <div className="strip-art" aria-hidden="true">
          <div className="strip-track">
            {Array.from({ length: 14 }, (_, index) => <span className="strip-segment" key={index} style={{ opacity: 0.36 + ((index % 4) * 0.16) }} />)}
          </div>
          <div className="strip-reflection" />
        </div>
      )}
      <div className="art-label"><span>{device.kind === 'bulb' ? 'RGB + branco' : 'RGB contínuo'}</span><span>●</span></div>
    </motion.div>
  )
}
