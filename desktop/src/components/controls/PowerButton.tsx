import { Power } from 'lucide-react'

interface PowerButtonProps {
  deviceName: string
  enabled: boolean
  disabled?: boolean
  unknown?: boolean
  onToggle(): void
}

export function PowerButton({ deviceName, enabled, disabled = false, unknown = false, onToggle }: PowerButtonProps) {
  return (
    <button
      className={`power-button${enabled ? ' is-on' : ''}`}
      type="button"
      aria-label={unknown ? `Estado de energia desconhecido para ${deviceName}` : `${enabled ? 'Desligar' : 'Ligar'} ${deviceName}`}
      aria-pressed={unknown ? undefined : enabled}
      onClick={onToggle}
      disabled={disabled}
    >
      <Power size={17} strokeWidth={1.8} aria-hidden="true" />
    </button>
  )
}
