import type { CSSProperties } from 'react'

interface RangeControlProps {
  label: string
  value: number
  min?: number
  max?: number
  step?: number
  suffix?: string
  variant?: 'standard' | 'hue' | 'temperature'
  onChange(value: number): void
}

export function RangeControl({ label, value, min = 0, max = 100, step = 1, suffix = '%', variant = 'standard', onChange }: RangeControlProps) {
  const progress = ((value - min) / (max - min)) * 100
  const style = { '--range-progress': `${progress}%` } as CSSProperties

  return (
    <div className="range-control">
      <div className="range-heading">
        <label htmlFor={`range-${label}`}>{label}</label>
        <span className="range-value" aria-hidden="true">{Math.round(value)}{suffix}</span>
      </div>
      <input
        id={`range-${label}`}
        aria-label={label}
        className={`range-input range-input--${variant}`}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        style={style}
        onChange={(event) => onChange(Number(event.currentTarget.value))}
      />
    </div>
  )
}
