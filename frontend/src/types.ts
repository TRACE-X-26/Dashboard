export type Profile = {
  device_id: string
  rated_voltage: number
  rated_current: number
  rated_rpm: number
  winding_resistance: number
  max_current: number
  max_temperature: number
}

export type RecordingMetadata = {
  filename: string
  device_id: string
  condition: string
  attached_mass_g: number | null
  fixture_description: string
  target_pwm_percent: number | null
  filename_mass_label_g?: number | null
  recorded_target_pwm_labels?: string[]
}
export type RecordingSummary = { id: number; imported_at: string; metadata: RecordingMetadata }
export type Recording = {
  id: number
  metadata: RecordingMetadata
  source: string
  analysis_status: string
  running_samples: number
  samples: { sequence: number; line: number; timestamp: string; phase: string; warnings: string[];
    direction: string | null;
    voltage: number | null; current: number | null; rpm: number | null; temperature: number | null;
    input_power: number | null; recorded_power: number | null }[]
  warnings: { line: number; code: string }[]
  limitations: string[]
  features: Record<string, { count: number; mean: number | null; min: number | null; max: number | null; std: number | null }>
  recorded_features?: Recording['features']
  timestamp_basis?: string
}

export type Measurement = {
  sequence: number
  timestamp: string
  voltage: number | null
  current: number | null
  rpm: number | null
  temperature: number | null
  resistance: number | null
  vibration_rms: number | null
  input_power: number | null
}

export type Finding = {
  code: string
  severity: 'PASS' | 'WARNING' | 'CRITICAL'
  message: string
  possible_causes?: string[]
}

export type Report = {
  device_id: string
  health_score: number
  condition: 'HEALTHY' | 'WARNING' | 'CRITICAL'
  findings: Finding[]
}

export type Session = {
  id: number
  device_id: string
  scenario: string
  started_at: string
  completed_at: string | null
  state: string
  condition: string | null
  health_score: number | null
  sample_count: number
}

export type SessionDetail = {
  summary: Session
  measurements: Measurement[]
  findings: Finding[]
}

export type Baseline = {
  device_id: string
  created_at: string
  sample_count: number
  voltage_mean: number
  current_mean: number
  rpm_mean: number
  temperature_mean: number
  current_std: number
  rpm_std: number
}

export type MotorState = {
  enabled: boolean
  direction: 'FORWARD' | 'REVERSE'
  pwm_percent: number
  emergency_stop: boolean
  sequence: number
  updated_at: number
}

export type MotorTelemetry = {
  voltage: number
  current: number
  rpm: number
  temperature: number
  power: number
}

export type MotorStatus = {
  state: MotorState
  telemetry: MotorTelemetry
  mode: string
  sequence: MotorSequenceStatus
}

export type MotorSequenceStatus = {
  running: boolean
  name: string | null
  step_index: number
  total_steps: number
  message: string
}

export type CommandAcknowledgment = {
  command_id: string
  accepted: boolean
  message: string
  state: MotorState
}

export type MeterChannel = {
  channel: string
  label: string
  sensor: string
  value: number
  unit: string
  status: string
}

export type MeterReading = {
  timestamp: number
  sample_id: number
  motor_enabled: boolean
  channels: MeterChannel[]
}

export type CircuitTestPoint = {
  point_id: string
  label: string
  instruction: string
  sensor: string
  unit: string
  minimum: number
  maximum: number
}

export type CircuitProfile = {
  profile_id: string
  name: string
  description: string
  test_points: CircuitTestPoint[]
}

export type CircuitStepResult = CircuitTestPoint & {
  measured: number
  expected_min: number
  expected_max: number
  result: 'PASS' | 'FAIL' | 'LEARNED'
  explanation: string
}

export type CircuitReport = {
  profile_id: string
  mode: 'LEARN' | 'DIAGNOSE'
  scenario: string
  condition: 'HEALTHY' | 'FAULT' | 'LEARNED'
  conclusion: string
  uses_learned_baseline: boolean
  steps: CircuitStepResult[]
}
