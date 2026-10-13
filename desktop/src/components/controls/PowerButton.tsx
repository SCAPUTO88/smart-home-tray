import { Power } from 'lucide-react'

interface PowerButtonProps {
  deviceName: string
  enabled: boolean
  onToggle(): void
}

export function PowerButton({ deviceName, enabled, onToggle }: PowerButtonProps) {
  return (
    <button
      className={`power-button${enabled ? ' is-on' : ''}`}
      type="button"
      aria-label={`${enabled ? 'Desligar' : 'Ligar'} ${deviceName}`}
      aria-pressed={enabled}
      onClick={onToggle}
    >
      <Power size={17} strokeWidth={1.8} aria-hidden="true" />
    </button>
  )
}
