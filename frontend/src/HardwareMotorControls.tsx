import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import INA219Readings from './INA219Readings'
import type { AutomatedRun } from './types'

type HardwareStatus = {
  profile_ready: boolean; reason: string; asset_id: string; fixed_pwm_percent: number | null;
  max_duration_ms: number; active_run: AutomatedRun | null;
}
const terminal = (run: AutomatedRun | null) => !run || !!run.ended_at
const value = (v: number | null | undefined, digits = 2) => v == null ? '—' : v.toFixed(digits)

export default function HardwareMotorControls() {
  const [status, setStatus] = useState<HardwareStatus | null>(null)
  const [run, setRun] = useState<AutomatedRun | null>(null)
  const [pwm, setPwm] = useState(50)
  const [duration, setDuration] = useState(30)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const socketRef = useRef<WebSocket | null>(null)
  useEffect(() => {
    let mounted = true
    async function refresh() {
      try {
        const next = await api.hardwareMotorStatus()
        if (!mounted) return
        setStatus(next)
        if (next.active_run) setRun(next.active_run)
      } catch (err) { if (mounted) setError(String(err)) }
    }
    refresh()
    const timer = window.setInterval(refresh, 1000)
    return () => { mounted = false; window.clearInterval(timer) }
  }, [])
  const runId = run?.id
  useEffect(() => {
    if (!runId) return
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/automated/${runId}`)
    socketRef.current = socket
    socket.onmessage = event => {
      const next: AutomatedRun = JSON.parse(event.data)
      setRun(next)
      if (next.ended_at) socket.close()
    }
    socket.onerror = () => setError('STM32 test stream unavailable. Stop is not confirmed; check saved status.')
    return () => { socket.close(); socketRef.current = null }
  }, [runId])
  const active = !terminal(run)
  async function start() {
    if (!window.confirm(`Start the real motor at ${pwm}% PWM for ${duration} seconds? Keep the physical power switch accessible.`)) return
    setPending(true); setError('')
    try {
      const next = await api.startAutomated({ mode: 'hardware', device_id: status?.asset_id,
        tests: [`pwm_${pwm}`], duration_ms: Math.round(duration * 1000), operator_authorized: true })
      setRun(next)
    } catch (err) { setError(String(err)) }
    finally { setPending(false) }
  }
  async function stop(emergency = false) {
    if (!run) return
    try { await api.stopAutomated(run.id, emergency) }
    catch (err) { setError(String(err)) }
  }
  const sample = run?.latest_measurement
  return <section className="panel motor-controls">
    <div className="panel-title"><div><h2>STM32 motor test</h2><p>JGA25-371 · real USB serial commands · temperature disabled</p></div><span className="mode-chip">HARDWARE</span></div>
    <p>{status?.profile_ready ? 'Pi profile ready. STM32 identity, protection and sensor checks must still pass before starting.' : status?.reason ?? 'Checking Pi hardware configuration…'}</p>
    <div className="control-bar">
      <label>PWM<select value={pwm} disabled={active || pending} onChange={e => setPwm(Number(e.target.value))}>{[10, 25, 50, 75, 100].map(p => <option key={p} value={p} disabled={!status?.profile_ready || p !== status.fixed_pwm_percent}>{p}%{p !== status?.fixed_pwm_percent ? ' · requires approval' : ''}</option>)}</select></label>
      <label>Duration (seconds)<input type="number" min="0.1" max={Math.min(30, (status?.max_duration_ms || 30000) / 1000)} step="0.1" value={duration} disabled={active || pending} onChange={e => setDuration(Number(e.target.value))}/></label>
      <button className="primary" disabled={!status?.profile_ready || active || pending || pwm !== status.fixed_pwm_percent || !Number.isFinite(duration) || duration < 0.1 || duration * 1000 > status.max_duration_ms} onClick={start}>Start Motor</button>
      <button className="secondary" disabled={!active} onClick={() => stop()}>Stop Motor</button>
      <button className="estop" disabled={!active} onClick={() => stop(true)}>EMERGENCY STOP</button>
    </div>
    <div className="driver-state"><div><span>Motor command state</span><strong>{run?.device_state ?? 'UNKNOWN'}</strong></div><div><span>Requested PWM</span><strong>{run?.requested_pwm_percent == null ? '—' : `${run.requested_pwm_percent}%`}</strong></div><div><span>STM32-applied PWM</span><strong>{run?.applied_pwm_percent == null ? '—' : `${run.applied_pwm_percent}%`}</strong></div></div>
    <section className="metric-grid motor-metrics">
      <div className="metric"><span>Voltage</span><strong>{value(sample?.voltage)}<small> V</small></strong></div>
      <div className="metric"><span>Current</span><strong>{value(sample?.current)}<small> A</small></strong></div>
      <div className="metric"><span>Output RPM · {sample?.rpm_calibrated ? 'calibrated' : 'provisional / uncalibrated'}</span><strong>{value(sample?.rpm, 0)}</strong></div>
      <div className="metric"><span>Input power</span><strong>{value(sample?.input_power)}<small> W</small></strong></div>
    </section>
    <INA219Readings branches={sample?.ina219} fresh={active}/>
    <p>{run ? `${run.state} · ${(run.elapsed_seconds ?? 0).toFixed(1)} s · ${run.stop_confirmed ? 'STM32 zero-output acknowledged' : 'Stopped state not confirmed'}` : 'No hardware run selected. No simulated values are shown here.'}</p>
    {run?.faults?.length ? <p role="alert">Faults: {run.faults.join(', ')}</p> : null}
    {(error || run?.reason) && <p role="alert">{error || run?.reason}</p>}
    {run && <a className="secondary" href={`/api/automated/runs/${run.id}/csv`}>Download motor CSV</a>}
    <p>Applied PWM is the STM32 output setting, not a measured waveform. Encoder scaling assumes 374 A-channel rising edges per output revolution. Leaving this page cancels an active hardware test.</p>
  </section>
}
