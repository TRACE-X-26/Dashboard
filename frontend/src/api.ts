import type { Baseline, CircuitProfile, CircuitReport, CommandAcknowledgment, MeterReading, MotorStatus, Profile, Session, SessionDetail } from './types'
import type { Recording, RecordingMetadata, RecordingSummary } from './types'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(body.detail ?? 'Request failed')
  }
  return response.json() as Promise<T>
}

export const api = {
  liveStatus: () => request<{ enabled: boolean; connected: boolean; stale: boolean }>('/api/live/status'),
  recordings: () => request<RecordingSummary[]>('/api/recordings'),
  recording: (id: number) => request<Recording>(`/api/recordings/${id}`),
  importRecording: (metadata: RecordingMetadata, content: string) => request<Recording>('/api/recordings', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...metadata, content }),
  }),
  health: () => request<{ status: string; mode: string; database: string; hardware_control: boolean; measurement_source: string }>('/api/health'),
  scenarios: () => request<string[]>('/api/scenarios'),
  profiles: () => request<Profile[]>('/api/profiles'),
  sessions: () => request<Session[]>('/api/sessions'),
  baselines: () => request<Baseline[]>('/api/baselines'),
  motorStatus: () => request<MotorStatus>('/api/motor/status'),
  meterReading: () => request<MeterReading>('/api/multimeter/readings'),
  circuitProfiles: () => request<{ profiles: CircuitProfile[]; scenarios: string[] }>('/api/circuits/profiles'),
  runCircuit: (profileId: string, mode: 'LEARN' | 'DIAGNOSE', scenario: string) =>
    request<CircuitReport>('/api/circuits/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile_id: profileId, mode, scenario }),
    }),
  motorCommand: (commandId: string, action: string, value?: number | string) =>
    request<CommandAcknowledgment>('/api/motor/commands', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command_id: commandId, action, value }),
    }),
  startMotorSequence: () => request<{ accepted: boolean; message: string }>('/api/motor/sequences/pwm-ramp', { method: 'POST' }),
  cancelMotorSequence: () => request<{ accepted: boolean; message: string }>('/api/motor/sequences/cancel', { method: 'POST' }),
  session: (id: number) => request<SessionDetail>(`/api/sessions/${id}`),
  createBaseline: (id: number) => request<Baseline>(`/api/sessions/${id}/baseline`, {
    method: 'POST',
  }),
  saveProfile: (profile: Profile) => request<Profile>('/api/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  }),
}

export function testSocket(): WebSocket {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
  return new WebSocket(`${protocol}://${location.host}/ws/tests`)
}
