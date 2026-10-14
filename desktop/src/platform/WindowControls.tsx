import { PanelTopClose } from 'lucide-react'
import { hidePanel, isTauriRuntime } from './tauriWindow'

export default function WindowControls() {
  if (!isTauriRuntime()) return null

  return (
    <button
      className="window-hide-button"
      type="button"
      aria-label="Ocultar painel"
      title="Ocultar painel"
      onClick={() => { void hidePanel() }}
    >
      <PanelTopClose size={14} aria-hidden="true" />
    </button>
  )
}
