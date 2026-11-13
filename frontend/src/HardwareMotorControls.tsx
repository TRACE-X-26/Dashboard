import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import INA219Readings from './INA219Readings'
import type { AutomatedRun } from './types'

type HardwareStatus = {
  operating_mode: string; power_feedback_installed: boolean; electrical_limits_enabled: boolean | null; protection_limits_verified: boolean; supply_sensing_verified: boolean;
  warnings: string[]; profile_ready: boolean; reason: string; asset_id: string; fixed_pwm_percent: number | null;
  max_duration_ms: number; active_run: AutomatedRun | null;
  hardware_control_enabled: boolean; hardware_control: boolean; firmware_hardware_control: boolean | null;
  preflight: { ready: boolean; reason: string; stale: boolean };
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
  async function preflight() {
    setPending(true); setError('')
    try {
      await api.hardwareMotorPreflight()
      setStatus(await api.hardwareMotorStatus())
    } catch (err) { setError(String(err)) }
    finally { setPending(false) }
  }
  async function start() {
    setPending(true); setError('')
    try {
      const next = await api.startAutomated({ mode: 'hardware', device_id: status?.asset_id,
        tests: [`pwm_${pwm}`], duration_ms: Math.round(duration * 1000) })
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
    <div className="panel-title"><div><h2>STM32 motor test</h2><p>JGA25-371 · relay-on voltage check at zero PWM before motor start</p></div><span className="mode-chip">HARDWARE</span></div>
    <p>Start sends a motor-test request. The STM32 decides whether physical protections permit output.</p>
    <p>Pi operating mode: <strong>{status?.operating_mode ?? 'UNKNOWN'}</strong> · Power feedback: {status?.power_feedback_installed ? 'installed; verification required' : 'NOT INSTALLED'} · Voltage/current protection: {status?.electrical_limits_enabled === true ? 'configured on Pi; actual limits reported by STM32' : 'Pi configuration unverified'} · Downstream sensing: {status?.supply_sensing_verified ? 'relay-on check required · PWM stays zero' : 'configuration pending'}</p>
    <p>Circuit runtime opt-in: {status?.hardware_control_enabled ? 'explicitly enabled' : 'disabled'} · STM32 output permission: {status?.firmware_hardware_control == null ? 'not checked' : status.firmware_hardware_control ? 'reported enabled' : 'reported disabled'}</p>
    <p role="status">{status?.preflight.reason ?? 'No STM32 snapshot yet; Start Test remains available.'}</p>
    {status?.warnings?.map((warning, i) => <p role="status" key={i}>Warning: {warning}</p>)}
    <button className="secondary" disabled={active || pending} onClick={preflight}>Check hardware · no motor commands</button>
    <div className="control-bar">
      <label>PWM<select value={pwm} disabled={active || pending} onChange={e => setPwm(Number(e.target.value))}>{[10, 25, 50, 75, 100].map(p => <option key={p} value={p}>{p}%</option>)}</select></label>
      <label>Duration (seconds)<input type="number" min="0.1" max={30} step="0.1" value={duration} disabled={active || pending} onChange={e => setDuration(Number(e.target.value))}/></label>
      <button className="primary" disabled={active || pending || !Number.isFinite(duration) || duration < 0.1 || duration > 30} onClick={start}>Start Test</button>
      <button className="secondary" disabled={!active} onClick={() => stop()}>Stop Test</button>
      <button className="estop" disabled={!active} onClick={() => stop(true)}>EMERGENCY STOP</button>
    </div>
    <p>STM32 operating mode: {run?.operating_mode ?? 'Not yet reported'} · Feedback state: {run?.power_feedback_state ?? 'Not yet reported'}</p>
    <div className="driver-state"><div><span>Motor command state</span><strong>{run?.device_state ?? 'UNKNOWN'}</strong></div><div><span>Requested PWM</span><strong>{run?.requested_pwm_percent == null ? '—' : `${run.requested_pwm_percent}%`}</strong></div><div><span>STM32-applied PWM</span><strong>{run?.applied_pwm_percent == null ? '—' : `${run.applied_pwm_percent}%`}</strong></div></div>
    <section className="metric-grid motor-metrics">
      <div className="metric"><span>Voltage</span><strong>{value(sample?.voltage)}<small> V</small></strong></div>
      <div className="metric"><span>Current</span><strong>{value(sample?.current)}<small> A</small></strong></div>
      <div className="metric"><span>Output RPM · {sample?.rpm_calibrated ? 'calibrated' : 'provisional / uncalibrated'}</span><strong>{value(sample?.rpm, 0)}</strong></div>
      <div className="metric"><span>Input power</span><strong>{value(sample?.input_power)}<small> W</small></strong></div>
    </section>
    <INA219Readings branches={sample?.ina219} fresh={active}/>
    <p>{run ? `${run.state} · ${(run.elapsed_seconds ?? 0).toFixed(1)} s · ${run.stop_confirmed ? 'STM32 zero-output acknowledged' : 'Stopped state not confirmed'}` : 'No hardware run selected. No simulated values are shown here.'}</p>
    {run?.warnings?.map((warning, i) => <p role="status" key={i}>Warning: {warning}</p>)}
    {run?.latest_measurement?.quality?.length ? <p role="status">Telemetry quality: {run.latest_measurement.quality.join(', ')}</p> : null}
    {run?.firmware_acknowledgments?.length ? <details open><summary>Actual STM32 acknowledgments</summary>{run.firmware_acknowledgments.map((ack, i) => <pre key={i}>{ack.command}: {JSON.stringify(ack.result)}</pre>)}</details> : null}
    {run?.faults?.length ? <p role="alert">Faults: {run.faults.join(', ')}</p> : null}
    {(error || run?.reason) && <p role="alert">{error || run?.reason}</p>}
    {run && <a className="secondary" href={`/api/automated/runs/${run.id}/csv`}>Download motor CSV</a>}
    <p>Applied PWM is the STM32 output setting, not a measured waveform. Encoder scaling assumes 374 A-channel rising edges per output revolution. Leaving this page cancels an active hardware test.</p>
  </section>
}
