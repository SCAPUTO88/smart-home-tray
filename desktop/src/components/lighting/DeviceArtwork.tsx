import { useId } from 'react'
import { motion } from 'motion/react'
import type { CSSProperties } from 'react'
import type { LightingDevice, DeviceState } from '../../features/devices/types'
import { lightingIntensity, selectedLightingColor } from '../../lib/lightingVisuals'

interface DeviceArtworkProps { device: LightingDevice; state: DeviceState }

export function DeviceArtwork({ device, state }: DeviceArtworkProps) {
  const color = selectedLightingColor(state)
  const intensity = lightingIntensity(state)
  const prefix = 'lighting-' + useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const id = (part: string) => prefix + '-' + part
  const url = (part: string) => 'url(#' + id(part) + ')'
  const style = { '--lamp-color': color, '--lamp-intensity': intensity } as CSSProperties

  return (
    <motion.div className={'device-art device-art--' + device.kind + (state.enabled ? ' is-on' : ' is-off')}
      style={style} role="img" aria-label={'Ilustração ' + device.name}
      data-hue={state.hsv.hue} data-value={state.mode === 'rgb' ? state.hsv.value : state.whiteBrightness}
      data-powered={state.enabled ? 'true' : 'false'}
      initial={{ opacity: 0, y: 10, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}>
      <div className="art-light art-light--ambient" aria-hidden="true" />
      <div className="art-light art-light--halo" aria-hidden="true" />
      {device.kind === 'bulb' ? (
        <svg className="bulb-svg" viewBox="0 0 240 260" aria-hidden="true">
          <defs>
            <linearGradient id={id('glass')} x1=".16" x2=".88" y1=".06" y2=".94">
              <stop offset="0" stopColor="#fff" stopOpacity=".78" /><stop offset=".2" stopColor="#dceafa" stopOpacity=".25" />
              <stop offset=".53" stopColor="var(--lamp-color)" stopOpacity=".18" /><stop offset=".78" stopColor="#697d98" stopOpacity=".26" />
              <stop offset="1" stopColor="#344258" stopOpacity=".72" />
            </linearGradient>
            <linearGradient id={id('glass-edge')} x1="0" x2="1" y1="0" y2="1">
              <stop offset="0" stopColor="#fff" stopOpacity=".88" /><stop offset=".4" stopColor="var(--lamp-color)" stopOpacity=".42" />
              <stop offset="1" stopColor="#9aabc1" stopOpacity=".52" />
            </linearGradient>
            <radialGradient id={id('inner-light')} cx="50%" cy="61%" r="58%">
              <stop offset="0" stopColor="#fff" stopOpacity=".88" /><stop offset=".18" stopColor="var(--lamp-color)" stopOpacity=".96" />
              <stop offset=".58" stopColor="var(--lamp-color)" stopOpacity=".48" /><stop offset="1" stopColor="var(--lamp-color)" stopOpacity="0" />
            </radialGradient>
            <linearGradient id={id('metal')} x1="0" x2="1" y1="0" y2="0">
              <stop offset="0" stopColor="#435064" /><stop offset=".14" stopColor="#8d9db0" /><stop offset=".29" stopColor="#d5dfeb" />
              <stop offset=".43" stopColor="#73849a" /><stop offset=".64" stopColor="#e1e8ef" /><stop offset=".82" stopColor="#8999ad" /><stop offset="1" stopColor="#3f4b5e" />
            </linearGradient>
            <linearGradient id={id('metal-edge')} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#f7fbff" stopOpacity=".72" /><stop offset=".2" stopColor="#94a4b9" stopOpacity=".34" />
              <stop offset=".5" stopColor="#172333" stopOpacity=".78" /><stop offset=".8" stopColor="#d9e2ed" stopOpacity=".52" /><stop offset="1" stopColor="#253142" />
            </linearGradient>
            <clipPath id={id('glass-clip')}><path d="M120 18c-44 0-79 35-79 78 0 28 13 48 31 68 9 10 15 21 18 34h60c3-13 9-24 18-34 18-20 31-40 31-68 0-43-35-78-79-78Z" /></clipPath>
          </defs>
          <ellipse className="bulb-contact-shadow" cx="120" cy="250" rx="33" ry="5" />
          <path className="bulb-inner-envelope" d="M120 26c-39 0-70 31-70 70 0 24 11 42 28 61 11 12 18 26 21 42h42c3-16 10-30 21-42 17-19 28-37 28-61 0-39-31-70-70-70Z" fill={url('inner-light')} />
          <path className="bulb-glass" d="M120 18c-44 0-79 35-79 78 0 28 13 48 31 68 9 10 15 21 18 34h60c3-13 9-24 18-34 18-20 31-40 31-68 0-43-35-78-79-78Z" fill={url('glass')} stroke={url('glass-edge')} />
          <g className="bulb-speculars" clipPath={url('glass-clip')}>
            <path className="bulb-side-highlight" d="M62 54c-10 15-14 34-11 52 2 13 7 23 13 32" />
            <path className="bulb-specular-arc" d="M78 32c-10 4-18 10-24 19" /><path className="bulb-soft-reflection" d="M172 47c17 14 25 34 23 54" />
            <ellipse className="bulb-reflection" cx="103" cy="46" rx="19" ry="5" transform="rotate(-32 103 46)" />
            <path className="bulb-lower-reflection" d="M94 177c17 7 35 7 52 0" />
          </g>
          <path className="bulb-emitter" d="M93 133c11 10 43 10 54 0l-4 24c-9 6-37 6-46 0l-4-24Z" fill={url('inner-light')} />
          <path className="bulb-filament" d="M98 129c8 7 36 7 44 0m-39 12c6 5 28 5 34 0" />
          <path className="bulb-neck" d="M91 197h58v16c0 5-4 9-9 9h-40c-5 0-9-4-9-9v-16Z" fill={url('metal')} />
          <path className="bulb-neck-rim" d="M92 199h56m-57 18h58" /><path className="bulb-screw-body" d="M93 220h54l-5 27h-44l-5-27Z" fill={url('metal-edge')} />
          <path className="bulb-screw" d="M94 223h52m-50 7h48m-46 7h44m-42 7h40" />
          <ellipse className="bulb-foot" cx="120" cy="249" rx="15" ry="4" fill={url('metal')} /><ellipse className="bulb-foot-highlight" cx="120" cy="248" rx="9" ry="1.2" />
        </svg>
      ) : (
        <div className="strip-art" aria-hidden="true">
          <div className="strip-track"><div className="strip-circuit" />
            <div className="strip-emitters">{Array.from({ length: 14 }, (_, index) => <span className="strip-emitter" key={index}><i /></span>)}</div>
            <div className="strip-diffuser" /><div className="strip-specular" />
          </div><div className="strip-reflection" />
        </div>
      )}
      <div className="art-label"><span>{device.kind === 'bulb' ? 'RGB + branco' : 'RGB contínuo'}</span><span>●</span></div>
    </motion.div>
  )
}
