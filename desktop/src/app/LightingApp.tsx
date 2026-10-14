import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import type { DeviceController, LightingPatch, OperationScenario } from '../features/devices/types'
import { useLightingSession } from '../features/devices/useLightingSession'
import { resolveDeviceController } from '../features/devices/platformController'
import { lightingIntensity, selectedLightingColor } from '../lib/lightingVisuals'
import { DeviceArtwork } from '../components/lighting/DeviceArtwork'
import { PowerButton } from '../components/controls/PowerButton'
import { RangeControl } from '../components/controls/RangeControl'
import { AnimatePresence, motion, MotionConfig } from 'motion/react'
import { Activity, Check, ChevronDown, Lightbulb, Palette, SlidersHorizontal, WifiOff } from 'lucide-react'
import WindowControls from '../platform/WindowControls'
import { startDraggingPanel } from '../platform/tauriWindow'
import './LightingApp.css'

interface LightingAppProps {
  controller?: DeviceController
}

const scenarioNames: Record<OperationScenario, string> = {
  success: 'Sucesso', delay: 'Atraso', canceled: 'Cancelada', error: 'Erro', offline: 'Offline',
}

function operationLabel(status: string): string {
  if (status === 'pending') return 'Enviando…'
  if (status === 'confirmed') return 'Atualizado'
  if (status === 'canceled') return 'Operação cancelada'
  if (status === 'offline') return 'Offline'
  if (status === 'error') return 'Não foi possível atualizar'
  return 'Pronto para controlar'
}

export default function LightingApp({ controller: suppliedController }: LightingAppProps) {
  const [controller, setController] = useState<DeviceController | null>(null)
  const [startupError, setStartupError] = useState<string | null>(null)
  useEffect(() => {
    if (suppliedController) return
    let active = true
    void resolveDeviceController().then((resolved) => { if (active) setController(resolved) }).catch(() => {
      if (active) setStartupError('Não foi possível iniciar a integração selecionada')
    })
    return () => { active = false }
  }, [suppliedController])
  const activeController = suppliedController ?? controller
  if (startupError) return <main className="app-shell app-shell--loading"><Brand /><p role="alert">{startupError}</p></main>
  if (!activeController) return <main className="app-shell app-shell--loading"><Brand /><div className="loading-card" role="status">Iniciando Smart Home Tray…</div></main>
  return <LightingPanel controller={activeController} />
}

function LightingPanel({ controller }: { controller: DeviceController }) {
  const session = useLightingSession(controller)
  const [scenario, setScenario] = useState<OperationScenario>('success')
  const { devices, selectedDevice: device, selectedView: view, issue, loadError } = session

  if (loadError) return <main className="app-shell app-shell--loading"><Brand /><p role="alert">{loadError}</p></main>
  if (!device || !view) {
    return (
      <main className="app-shell app-shell--loading">
        <header
          className="topbar"
          title="Arraste para mover o painel"
          onMouseDown={(event) => { void startDraggingPanel(event.target, event.button) }}
        ><Brand /><span className="connection-badge"><i /> Conectando</span></header>
        <div className="loading-card" role="status">Carregando dispositivos…</div>
      </main>
    )
  }

  const state = view.preview
  const accent = selectedLightingColor(state)
  const ambientIntensity = lightingIntensity(state)
  const issueValue = (patch: LightingPatch) => issue(device.deviceId, patch, scenario)
  const statusText = operationLabel(view.status)

  return (
    <MotionConfig reducedMotion="user">
      <main className="app-shell" style={{ '--accent-color': accent, '--accent-intensity': ambientIntensity } as CSSProperties}>
        <header
          className="topbar"
          title="Arraste para mover o painel"
          onMouseDown={(event) => { void startDraggingPanel(event.target, event.button) }}
        >
          <Brand />
          <div className="topbar-actions">
            <div className={`connection-badge${device.connection === 'offline' ? ' is-offline' : ''}`}>
              {device.connection === 'offline' ? <WifiOff size={12} /> : <i aria-hidden="true" />}
              {device.connection === 'offline' ? 'Offline' : state.quality === 'unknown' ? 'Estado desconhecido' : state.quality === 'pending' ? 'Aguardando confirmação' : controller.mode === 'mock' ? 'Conectado · simulação' : controller.mode === 'fixture' ? 'Fixture · simulação' : 'Conectado'}
            </div>
            <WindowControls />
          </div>
        </header>

        <div className="device-heading">
          <div>
            <span className="eyebrow">CONTROLE DE ILUMINAÇÃO</span>
            <h2>{device.name}</h2>
          </div>
          <PowerButton deviceName={device.name} enabled={state.enabled} disabled={!device.capabilities.power} onToggle={() => issueValue({ enabled: !state.enabled })} />
        </div>

        <nav className="device-switcher" aria-label="Selecionar dispositivo">
          {devices.map((item) => (
            <button
              className={`device-tab${item.deviceId === device.deviceId ? ' is-selected' : ''}`}
              type="button"
              key={item.deviceId}
              aria-pressed={item.deviceId === device.deviceId}
              onClick={() => session.selectDevice(item.deviceId)}
            >
              {item.kind === 'bulb' ? <Lightbulb size={15} /> : <Activity size={15} />}
              {item.name}
              {item.deviceId === device.deviceId && <motion.span layoutId="tab-indicator" className="tab-indicator" />}
            </button>
          ))}
        </nav>

        <AnimatePresence mode="wait" initial={false}>
          <motion.section
            className="device-stage"
            key={device.deviceId}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -5 }}
            transition={{ duration: 0.22 }}
            aria-label={`Visualização ${device.name}`}
          >
            <DeviceArtwork device={device} state={state} />
            <div className="stage-caption">
              <span className="stage-mode"><Palette size={13} /> {state.mode === 'rgb' ? 'Espectro RGB' : 'Luz branca'}</span>
              <span className="stage-value">{state.enabled ? Math.round(state.mode === 'rgb' ? state.hsv.value : state.whiteBrightness) + '% intensidade' : 'Desligada'}</span>
            </div>
          </motion.section>
        </AnimatePresence>

        <motion.section
          className="control-card"
          aria-label="Controles da iluminação"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.28, delay: 0.08 }}
        >
          <div className="control-card-heading">
            <div className="control-heading-icon"><SlidersHorizontal size={15} /></div>
            <div><h3>Controles</h3><p>Ajuste a luz ao seu ambiente</p></div>
            <div className={`operation-indicator is-${view.status}`} role="status" aria-live="polite">
              {view.status === 'pending' ? <span className="pending-dot" /> : view.status === 'confirmed' ? <Check size={13} /> : view.status === 'offline' ? <WifiOff size={13} /> : null}
              <span>{statusText}</span>
            </div>
          </div>

          {device.capabilities.white && (
            <div className="mode-switch" role="group" aria-label="Modo de iluminação">
              <button type="button" className={state.mode === 'white' ? 'is-active' : ''} aria-pressed={state.mode === 'white'} onClick={() => issueValue({ mode: 'white' })}>Branco</button>
              <button type="button" className={state.mode === 'rgb' ? 'is-active' : ''} aria-pressed={state.mode === 'rgb'} onClick={() => issueValue({ mode: 'rgb' })}>RGB</button>
            </div>
          )}

          <div className="range-list">
            <motion.div
              key={`${device.deviceId}-${state.mode}`}
              className="mode-panel"
              data-testid="mode-panel"
              data-mode={state.mode}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18 }}
            >
              {state.mode === 'rgb' && device.capabilities.rgb ? (
                <>
                  <RangeControl label="Matiz" value={state.hsv.hue} max={360} suffix="°" variant="hue" onChange={(hue) => issueValue({ hsv: { hue } })} />
                  <RangeControl label="Saturação" value={state.hsv.saturation} onChange={(saturation) => issueValue({ hsv: { saturation } })} />
                  <RangeControl label="Intensidade RGB" value={state.hsv.value} onChange={(value) => issueValue({ hsv: { value } })} />
                </>
              ) : device.capabilities.white ? (
                <>
                  {device.capabilities.white && <RangeControl label="Brilho branco" value={state.whiteBrightness} onChange={(whiteBrightness) => issueValue({ whiteBrightness })} />}
                  {device.capabilities.temperature && <RangeControl label="Temperatura de branco" value={state.whiteTemperature} variant="temperature" onChange={(whiteTemperature) => issueValue({ whiteTemperature })} />}
                </>
              ) : (
                <RangeControl label="Matiz" value={state.hsv.hue} max={360} suffix="°" variant="hue" onChange={(hue) => issueValue({ hsv: { hue } })} />
              )}
            </motion.div>
          </div>

          {controller.mode === 'mock' && <details className="scenario-panel">
            <summary>Cenário de teste <ChevronDown size={14} aria-hidden="true" /></summary>
            <label htmlFor="scenario-select">Resposta simulada</label>
            <select id="scenario-select" value={scenario} onChange={(event) => setScenario(event.currentTarget.value as OperationScenario)}>
              {Object.entries(scenarioNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <p>Simulação local; nenhum dispositivo real é consultado.</p>
          </details>}

          {view.error && <p className="error-detail" role="alert">{view.error}</p>}
        </motion.section>

        <footer className="prototype-note"><span className="mock-mark" /> {controller.mode === 'mock' ? 'Protótipo visual · dispositivos simulados' : controller.mode === 'fixture' ? 'Processo fixture · dados simulados' : 'Controle local'}</footer>
      </main>
    </MotionConfig>
  )
}

function Brand() {
  return <div className="brand-lockup"><span className="brand-mark"><Lightbulb size={16} /></span><h1>Smart Home Tray</h1></div>
}
