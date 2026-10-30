import { useEffect, useState } from 'react'

type LiveState = {
  enabled: boolean; connected: boolean; stale: boolean; error: string | null;
  sequence: number; recorded_motor_phase: string; warnings: string[];
  channels: Record<string, { value: number | string; quality: string; timestamp: string; age_seconds: number }>;
  diagnosis: { status: string; reason: string };
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
  return <>
    <header><div><p className="eyebrow">STM32 SENSOR MONITOR</p><h1>Live sensor measurements</h1><p>Pi USB receiver → network → this dashboard. Physical control remains disabled.</p></div></header>
    <section className="panel"><h2>Connection</h2>
      <p>{!online ? 'Dashboard stream disconnected' : !state?.enabled ? 'Pi serial monitoring is not configured' : !state.connected ? 'Serial disconnected' : state.stale ? 'Serial open; telemetry missing or stale' : 'Receiving unverified hardware telemetry'}</p>
      <p>Recorded motor event state: {online ? state?.recorded_motor_phase : 'Unknown'} · Received frames: {state?.sequence ?? 0}</p>
      {state?.error && <p role="alert">{state.error}</p>}
      <p>Branch voltage/current/power are measured before the driver. Values below retain separate receipt times; they are not a synchronized sample.</p>
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
