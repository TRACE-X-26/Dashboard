import { useEffect, useState } from 'react'

type LiveState = {
  enabled: boolean; connected: boolean; stale: boolean; error: string | null;
  sequence: number; recorded_motor_phase: string; warnings: string[];
  channels: Record<string, { value: number | string; quality: string; timestamp: string; age_seconds: number }>;
  diagnosis: { status: string; reason: string };
  hardware_connected: boolean; motor_format: string; complete_motor_frames: number; pending_motor_fields: string[];
  motor_sample: null | { motor_rpm: number; voltage: number; current: number; power: number;
    encoder_status: string; ina219_status: string; source: string; format: string;
    timestamp: string; timestamp_basis: string; age_seconds: number; stale: boolean; power_origin: string };
}

export default function LiveSensors() {
  const [state, setState] = useState<LiveState | null>(null)
  const [online, setOnline] = useState(false)
  useEffect(() => {
    let socket: WebSocket | undefined
    let retry: number | undefined
    let disposed = false
    function connect() {
      if (disposed) return
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/live`)
      socket.onmessage = event => { setState(JSON.parse(event.data)); setOnline(true) }
      socket.onclose = () => { setOnline(false); if (!disposed) retry = window.setTimeout(connect, 2000) }
      socket.onerror = () => setOnline(false)
    }
    connect()
    return () => { disposed = true; window.clearTimeout(retry); socket?.close() }
  }, [])
  const sample = state?.motor_sample
  const fresh = online && state?.hardware_connected && sample && !sample.stale
  const show = (value: number | undefined, digits: number) => fresh && value != null ? value.toFixed(digits) : '—'
  const status = (key: string, fallback?: string) => !online || !state?.hardware_connected ? 'Disconnected' :
    state.channels[key]?.quality === 'STALE' ? 'STALE' : state.channels[key]?.value ?? fallback ?? 'Not reported'
  return <>
    <header><div><p className="eyebrow">ACTUAL STM32 TELEMETRY · READ ONLY</p><h1>Live motor measurements</h1><p>STM32 USB → Pi backend → dashboard. No simulated values or motor commands on this page.</p></div></header>
    <section className="metric-grid" aria-label="Actual STM32 motor measurements">
      <div className="metric"><span>Motor RPM</span><strong>{show(sample?.motor_rpm, 1)}<small> RPM</small></strong></div>
      <div className="metric"><span>Branch voltage</span><strong>{show(sample?.voltage, 3)}<small> V</small></strong></div>
      <div className="metric"><span>Branch current</span><strong>{show(sample?.current, 3)}<small> A</small></strong></div>
      <div className="metric"><span>Input power</span><strong>{show(sample?.power, 3)}<small> W</small></strong></div>
    </section>
    <section className="panel"><h2>Connection</h2>
      <p>{!online ? 'Dashboard stream disconnected' : !state?.enabled ? 'Pi serial monitoring is not configured' : !state.connected ? 'Serial disconnected' : state.stale ? 'Serial open; telemetry missing or stale' : 'Receiving unverified hardware telemetry'}</p>
      <p>Recorded motor event state: {online ? state?.recorded_motor_phase : 'Unknown'} · Received frames: {state?.sequence ?? 0}</p>
      <p>Protocol: {state?.motor_format ?? 'UNKNOWN'} · Complete motor cycles: {state?.complete_motor_frames ?? 0}</p>
      <p>Latest status observations · Encoder: {status('encoder_status', sample?.encoder_status)} · INA219: {status('ina219_status', sample?.ina219_status)}</p>
      {sample && <p>Source: {sample.source} · Last complete cycle: {new Date(sample.timestamp).toLocaleTimeString()} · {online ? `${sample.age_seconds.toFixed(2)} s old` : 'stream disconnected'} · Power: {sample.power_origin}</p>}
      {!fresh && <p role="status">Waiting for a complete, fresh hardware cycle. Incomplete or stale readings are not shown as current values.</p>}
      {!sample && !!state?.pending_motor_fields?.length && <p>Missing cycle fields: {state.pending_motor_fields.join(', ')}</p>}
      {state?.error && <p role="alert">{state.error}</p>}
      <p>Branch voltage/current/power are measured before the driver. Plain-text cycles are grouped within three seconds using unique fields; this is receive-time association, not proof of simultaneous acquisition. Calibration remains unverified.</p>
      <h2>Individual channel observations</h2><p>Partial readings below are separate from the complete-cycle tiles.</p>
      <div className="table-wrap"><table><thead><tr><th>Channel</th><th>Last reported value</th><th>Quality</th><th>Age (s)</th></tr></thead><tbody>
        {Object.entries(state?.channels ?? {}).map(([key, c]) => <tr key={key}><td>{key}</td><td>{c.value} {({ voltage: 'V', current: 'A', rpm: 'RPM', temperature: '°C', recorded_power: 'W', input_power: 'W' } as Record<string, string>)[key] ?? ''}</td><td>{online ? c.quality : 'DISCONNECTED'}</td><td>{online ? c.age_seconds.toFixed(2) : 'Unknown'}</td></tr>)}
      </tbody></table></div>
      {!Object.keys(state?.channels ?? {}).length && <p>No sensor values received.</p>}
      <p>{state?.warnings.join(' · ')}</p>
    </section>
    <section className="panel"><h2>Diagnostic readiness</h2><p>{state?.diagnosis.status ?? 'NO_DATA'}</p><p>{state?.diagnosis.reason ?? 'Connect the Pi receiver to begin checking measurement quality.'}</p>
      <p>Sensor availability and freshness can be checked now. Motor or circuit health requires the correct asset definition, verified measurement channels, and calibrated limits/baselines. No hardware health percentage is assigned.</p>
    </section>
  </>
}
