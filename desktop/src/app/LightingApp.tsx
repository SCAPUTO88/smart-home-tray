import { useState } from 'react'
import { useApplicationSession } from './ApplicationSessionContext'
import { ApplicationSessionHost } from './ApplicationSessionHost'
import type { useLightingSession } from '../features/devices/useLightingSession'
import type { CSSProperties } from 'react'
import type { DeviceController, DeviceState, FieldKnowledge, LightingPatch, OperationStatus, OperationScenario } from '../features/devices/types'
import type { DeviceIntegration } from '../features/devices/platformController'
import { ManualRecoveryPanel } from '../features/recovery/ManualRecoveryPanel'
import type { RecoveryIntegration } from '../features/recovery/reconciliation'
import type { RecoveryPresentation } from '../features/recovery/recoveryPresentation'
import { lightingIntensity, selectedLightingColor } from '../lib/lightingVisuals'
import { DeviceArtwork } from '../components/lighting/DeviceArtwork'
import { PowerButton } from '../components/controls/PowerButton'
import { RangeControl } from '../components/controls/RangeControl'
import { AnimatePresence, motion, MotionConfig } from 'motion/react'
import { Activity, Check, ChevronDown, Lightbulb, Palette, RefreshCw, SlidersHorizontal, WifiOff } from 'lucide-react'
import WindowControls from '../platform/WindowControls'
import { startDraggingPanel } from '../platform/tauriWindow'
import './LightingApp.css'

interface LightingAppProps {
  controller?: DeviceController
  integration?: DeviceIntegration
}

const scenarioNames: Record<OperationScenario, string> = {
  success: 'Sucesso', delay: 'Atraso', canceled: 'Cancelada', error: 'Erro', offline: 'Offline',
}

function operationLabel(device: NonNullable<ReturnType<typeof useLightingSession>['selectedDevice']>, state: DeviceState, status: OperationStatus, pending: boolean, refreshing: boolean, refreshError: string | null, operationError: string | null): string {
  if (pending || refreshing || status === 'pending') return 'Enviando…'
  if (device.connection === 'offline' || status === 'offline') return 'Offline'
  if (operationError || status === 'error') return 'Não foi possível atualizar'
  if (status === 'canceled') return 'Operação cancelada'
  if (device.connection !== 'online') return 'Atualização necessária'
  const rgbPanel = state.mode === 'rgb' && device.capabilities.rgb
  const whitePanel = !rgbPanel && device.capabilities.white
  const modeFields: FieldKnowledge[] = rgbPanel || !whitePanel
    ? [state.knowledge.hsv]
    : [device.capabilities.white && state.knowledge.whiteBrightness, device.capabilities.temperature && state.knowledge.colorTemperature].filter((field): field is FieldKnowledge => Boolean(field))
  const availableModeFields = modeFields.filter((field) => field === 'observed').length
  if (modeFields.length > 0 && availableModeFields === 0) return 'Atualização necessária'
  if (availableModeFields < modeFields.length || device.capabilities.power && state.knowledge.power !== 'observed') return 'Controles limitados'
  if (status === 'confirmed') return 'Atualizado'
  if (refreshError) return 'Não foi possível atualizar'
  return 'Pronto para controlar'
}

export default function LightingApp({ controller: suppliedController, integration: suppliedIntegration }: LightingAppProps) {
  const inherited = useApplicationSession()
  if (!suppliedController && !suppliedIntegration && inherited) return <LightingAppContent />
  return <ApplicationSessionHost controller={suppliedController} integration={suppliedIntegration}><LightingAppContent /></ApplicationSessionHost>
}

export function LightingAppContent() {
  const application = useApplicationSession()
  if (!application || application.status === 'loading') return <main className="app-shell app-shell--loading"><Brand /><div className="loading-card" role="status">Iniciando Smart Home Tray…</div></main>
  if (application.status === 'error') return <main className="app-shell app-shell--loading"><Brand /><p role="alert">{application.message}</p></main>
  return <LightingPanel controller={application.controller} recovery={application.recovery} presentation={application.presentation} session={application.session} />
}

function LightingPanel({ controller, recovery, presentation, session }: { controller: DeviceController; recovery?: RecoveryIntegration; presentation?: RecoveryPresentation; session: ReturnType<typeof useLightingSession> }) {
  const [scenario, setScenario] = useState<OperationScenario>('success')
  const { devices, selectedDevice: device, selectedView: view, issue, loadError, refreshDevice, refreshing, refreshError } = session

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
  const stateUnavailable = device.connection !== 'online'
  const canWhiteMode = (device.capabilities.white && state.knowledge.whiteBrightness === 'observed') || (device.capabilities.temperature && state.knowledge.colorTemperature === 'observed')
  const canRgbMode = device.capabilities.rgb && state.knowledge.hsv === 'observed'
  const powerUnknown = state.knowledge.power !== 'observed'
  const accent = selectedLightingColor(state)
  const ambientIntensity = lightingIntensity(state)
  const issueValue = (patch: LightingPatch) => issue(device.deviceId, patch, scenario)
  const statusText = operationLabel(device, state, view.status, view.pendingOperations.length > 0, Boolean(refreshing[device.deviceId]), refreshError, view.error)
  const statusTone = statusText === 'Atualizado' ? 'confirmed' : statusText === 'Enviando…' ? 'pending' : statusText === 'Offline' ? 'offline' : statusText === 'Não foi possível atualizar' ? 'error' : statusText === 'Operação cancelada' ? 'canceled' : 'idle'

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
              {device.connection === 'offline' ? 'Offline' : device.connection === 'unknown' ? 'Conexao desconhecida' : state.quality === 'pending' ? 'Aguardando confirmacao' : controller.mode === 'mock' ? ('Conectado \u00b7 simula\u00e7\u00e3o') : controller.mode === 'fixture' ? ('Fixture \u00b7 simula\u00e7\u00e3o') : 'Conectado'}
            </div>
            <WindowControls />
          </div>
        </header>

        <div className="device-heading">
          <div>
            <span className="eyebrow">CONTROLE DE ILUMINAÇÃO</span>
            <h2>{device.name}</h2>
          </div>
          <PowerButton deviceName={device.name} enabled={state.enabled} disabled={!device.capabilities.power || stateUnavailable || powerUnknown} unknown={powerUnknown || device.connection !== 'online'} onToggle={() => issueValue({ enabled: !state.enabled })} />
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
              <span className="stage-mode"><Palette size={13} /> {stateUnavailable ? (device.connection === 'offline' ? 'Offline' : 'Conexão desconhecida') : state.knowledge.workMode === 'stale' ? 'Último modo observado' : state.knowledge.workMode !== 'observed' ? 'Modo desconhecido' : state.mode === 'rgb' ? 'Espectro RGB' : 'Luz branca'}</span>
              <span className="stage-value">{device.connection === 'offline' ? 'Offline' : device.connection === 'unknown' ? 'Estado desconhecido' : state.knowledge.power === 'stale' ? 'Último estado observado' : state.knowledge.power !== 'observed' ? 'Estado desconhecido' : !state.enabled ? 'Desligada' : state.mode === 'rgb' ? state.knowledge.colorValue === 'observed' ? Math.round(state.hsv.value) + '% intensidade' : 'Intensidade desconhecida' : state.knowledge.whiteBrightness === 'observed' ? Math.round(state.whiteBrightness) + '% intensidade' : 'Intensidade desconhecida'}</span>
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
            <div><h3>Controles</h3><p>{Object.values(state.knowledge).includes('stale') ? 'Últimos valores observados; atualização recomendada' : 'Ajuste a luz ao seu ambiente'}</p></div>
            {controller.refresh && <button className="refresh-action" type="button" aria-label="Atualizar estado do dispositivo" disabled={Boolean(refreshing[device.deviceId]) || view.pendingOperations.length > 0} onClick={() => void refreshDevice(device.deviceId)}>{refreshing[device.deviceId] ? "Atualizando..." : <><RefreshCw size={13} /> Atualizar</>}</button>}
            <div className={`operation-indicator is-${statusTone}`} role="status" aria-live="polite">
              {statusTone === 'pending' ? <span className="pending-dot" /> : statusTone === 'confirmed' ? <Check size={13} /> : statusTone === 'offline' ? <WifiOff size={13} /> : null}
              <span>{statusText}</span>
            </div>
          </div>

          {device.capabilities.white && (
            <div className="mode-switch" role="group" aria-label="Modo de iluminação">
              <button type="button" className={!stateUnavailable && state.mode === 'white' ? 'is-active' : ''} aria-pressed={stateUnavailable || state.knowledge.workMode !== 'observed' ? undefined : state.mode === 'white'} disabled={stateUnavailable || !canWhiteMode} onClick={() => issueValue({ mode: 'white' })}>Branco</button>
              <button type="button" className={!stateUnavailable && state.mode === 'rgb' ? 'is-active' : ''} aria-pressed={stateUnavailable || state.knowledge.workMode !== 'observed' ? undefined : state.mode === 'rgb'} disabled={stateUnavailable || !canRgbMode} onClick={() => issueValue({ mode: 'rgb' })}>RGB</button>
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
                  <RangeControl label="Matiz" value={state.hsv.hue} max={360} suffix="°" variant="hue" disabled={stateUnavailable || state.knowledge.hsv !== 'observed'} valueLabel={stateUnavailable || state.knowledge.hsv !== 'observed' ? '\u2014' : undefined} onChange={(hue) => issueValue({ hsv: { hue } })} />
                  <RangeControl label="Saturação" value={state.hsv.saturation} disabled={stateUnavailable || state.knowledge.hsv !== 'observed'} valueLabel={stateUnavailable || state.knowledge.hsv !== 'observed' ? '\u2014' : undefined} onChange={(saturation) => issueValue({ hsv: { saturation } })} />
                  <RangeControl label="Intensidade RGB" value={state.hsv.value} disabled={stateUnavailable || state.knowledge.hsv !== 'observed'} valueLabel={stateUnavailable || state.knowledge.hsv !== 'observed' ? '\u2014' : undefined} onChange={(value) => issueValue({ hsv: { value } })} />
                </>
              ) : device.capabilities.white ? (
                <>
                  {device.capabilities.white && <RangeControl label="Brilho branco" value={state.whiteBrightness} disabled={stateUnavailable || state.knowledge.whiteBrightness !== 'observed'} valueLabel={stateUnavailable || state.knowledge.whiteBrightness !== 'observed' ? '\u2014' : undefined} onChange={(whiteBrightness) => issueValue({ whiteBrightness })} />}
                  {device.capabilities.temperature && <RangeControl label="Temperatura de branco" value={state.whiteTemperature} variant="temperature" disabled={stateUnavailable || state.knowledge.colorTemperature !== 'observed'} valueLabel={stateUnavailable || state.knowledge.colorTemperature !== 'observed' ? '\u2014' : undefined} onChange={(whiteTemperature) => issueValue({ whiteTemperature })} />}
                </>
              ) : (
                <RangeControl label="Matiz" value={state.hsv.hue} max={360} suffix="°" variant="hue" disabled={stateUnavailable || state.knowledge.hsv !== 'observed'} valueLabel={stateUnavailable || state.knowledge.hsv !== 'observed' ? '\u2014' : undefined} onChange={(hue) => issueValue({ hsv: { hue } })} />
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

          {refreshError && <p className="error-detail" role="alert">{refreshError}</p>}
          {view.error && <p className="error-detail" role="alert">{view.error}</p>}
        </motion.section>

        {recovery && <ManualRecoveryPanel
          deviceId={device.deviceId}
          deviceName={device.name}
          eligibility={session.recoveryEligibility(device.deviceId)}
          store={presentation!}
          prepareRecovery={session.prepareRecovery}
          confirmRecovery={session.confirmRecovery}
          refreshDevice={controller.refresh ? refreshDevice : undefined}
          currentKnowledge={state.knowledge}
          refreshDisabled={Boolean(refreshing[device.deviceId]) || view.pendingOperations.length > 0}
          simulation={controller.mode === 'mock' || controller.mode === 'fixture'}
        />}

        <footer className="prototype-note"><span className="mock-mark" /> {controller.mode === 'mock' ? 'Protótipo visual · dispositivos simulados' : controller.mode === 'fixture' ? 'Processo fixture · dados simulados' : 'Controle local'}</footer>
      </main>
    </MotionConfig>
  )
}

function Brand() {
  return <div className="brand-lockup"><span className="brand-mark"><Lightbulb size={16} /></span><h1>Smart Home Tray</h1></div>
}
