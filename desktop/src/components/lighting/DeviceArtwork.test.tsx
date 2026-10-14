import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DeviceArtwork } from './DeviceArtwork'
import type { DeviceKind, DeviceState, LightingDevice } from '../../features/devices/types'

function state(overrides: Partial<DeviceState> = {}): DeviceState {
  return {
    enabled: true,
    mode: 'rgb',
    hsv: { hue: 180, saturation: 100, value: 50 },
    whiteBrightness: 40,
    whiteTemperature: 0,
    quality: 'confirmed',
    ...overrides,
  }
}

function device(deviceId: string, kind: DeviceKind, name: string): LightingDevice {
  return {
    deviceId,
    name,
    kind,
    connection: 'online',
    capabilities: { power: true, rgb: true, white: kind === 'bulb', temperature: kind === 'bulb' },
    state: state(),
  }
}

describe('DeviceArtwork', () => {
  it('uses warm white temperature and white brightness for the bulb preview', () => {
    render(<DeviceArtwork device={device('desk', 'bulb', 'Luz Mesa')} state={state({ mode: 'white' })} />)
    const artwork = screen.getByRole('img', { name: 'Ilustração Luz Mesa' })
    expect(artwork.style.getPropertyValue('--lamp-color')).toBe('rgb(255 174 100)')
    expect(artwork.style.getPropertyValue('--lamp-intensity')).toBe('0.4')
  })

  it('isolates the selected color for each device artwork', () => {
    render(
      <>
        <DeviceArtwork device={device('desk', 'bulb', 'Luz Mesa')} state={state()} />
        <DeviceArtwork device={device('strip', 'led-strip', 'Fita LED')} state={state({ hsv: { hue: 270, saturation: 100, value: 80 } })} />
      </>,
    )
    expect(screen.getByRole('img', { name: 'Ilustração Luz Mesa' }).style.getPropertyValue('--lamp-color')).toBe('rgb(0 128 128)')
    expect(screen.getByRole('img', { name: 'Ilustração Fita LED' }).style.getPropertyValue('--lamp-color')).toBe('rgb(102 0 204)')
  })

  it('removes emission on power off without changing the selected color', () => {
    render(<DeviceArtwork device={device('strip', 'led-strip', 'Fita LED')} state={state({ enabled: false })} />)
    const artwork = screen.getByRole('img', { name: 'Ilustração Fita LED' })
    expect(artwork.style.getPropertyValue('--lamp-color')).toBe('rgb(0 128 128)')
    expect(artwork.style.getPropertyValue('--lamp-intensity')).toBe('0')
    expect(artwork).toHaveClass('is-off')
    expect(artwork.querySelectorAll('.strip-emitter i')).toHaveLength(14)
    expect(artwork.querySelector('.strip-diffuser')).toBeInTheDocument()
    expect(artwork.querySelector('.strip-specular')).toBeInTheDocument()
    expect(artwork.querySelector('.strip-track')).toBeInTheDocument()
    expect(artwork.querySelector('.strip-circuit')).toBeInTheDocument()
  })

  it('renders physical glass reflections and metallic base with instance-scoped SVG definitions', () => {
    render(
      <>
        <DeviceArtwork device={device('desk', 'bulb', 'Luz Mesa')} state={state()} />
        <DeviceArtwork device={device('second', 'bulb', 'Luz Secundária')} state={state({ hsv: { hue: 270, saturation: 100, value: 60 } })} />
      </>,
    )
    const first = screen.getByRole('img', { name: 'Ilustração Luz Mesa' })
    const second = screen.getByRole('img', { name: 'Ilustração Luz Secundária' })
    expect(first.querySelector('.bulb-side-highlight')).toBeInTheDocument()
    expect(first.querySelector('.bulb-reflection')).toBeInTheDocument()
    expect(first.querySelector('.bulb-screw-body')).toBeInTheDocument()
    const ids = [...document.querySelectorAll('.bulb-svg [id]')].map((element) => element.id)
    expect(ids.length).toBeGreaterThan(0)
    expect(new Set(ids).size).toBe(ids.length)
    expect(first.querySelector('svg')).not.toBe(second.querySelector('svg'))
  })

  it('keeps emitters bound to selected HSV color at full intensity', () => {
    render(<DeviceArtwork device={device('strip', 'led-strip', 'Fita LED')} state={state({ hsv: { hue: 270, saturation: 100, value: 100 } })} />)
    const artwork = screen.getByRole('img', { name: /Fita LED/ })
    expect(artwork.style.getPropertyValue('--lamp-color')).toBe('rgb(128 0 255)')
    expect(artwork.style.getPropertyValue('--lamp-intensity')).toBe('1')
    expect(artwork.querySelectorAll('.strip-emitter i')).toHaveLength(14)
  })

  it('renders one selected HSV color beneath the LED diffuser', () => {
    render(<DeviceArtwork device={device('strip', 'led-strip', 'Fita LED')} state={state({ hsv: { hue: 270, saturation: 100, value: 10 } })} />)
    const artwork = screen.getByRole('img', { name: 'Ilustração Fita LED' })
    expect(artwork.style.getPropertyValue('--lamp-color')).toBe('rgb(13 0 26)')
    expect(artwork.style.getPropertyValue('--lamp-intensity')).toBe('0.1')
    expect(artwork.querySelectorAll('.strip-emitter')).toHaveLength(14)
    expect(artwork.querySelector('.strip-diffuser')).toBeInTheDocument()
    expect(artwork.querySelector('.strip-specular')).toBeInTheDocument()
  })
})
