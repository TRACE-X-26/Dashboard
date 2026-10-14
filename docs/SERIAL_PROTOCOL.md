# Raspberry Pi–STM32 Serial Protocol

## Current compatibility

The existing STM32 firmware is **not compatible** with this structured protocol. It only emits a one-second ASCII banner. This document specifies the backend interface and target firmware contract for controlled future implementation.

## Physical serial settings

| Setting | Value |
|---|---|
| Link | Nucleo ST-LINK virtual COM to STM32 USART2 |
| STM32 pins | PA2 TX, PA3 RX |
| Baud | 115200 |
| Data/parity/stop | 8-N-1 |
| Flow control | None |
| Pi default device | `/dev/ttyACM0` — must be confirmed |
| Frame boundary | One UTF-8 JSON object followed by `\n` |
| Maximum frame | 4096 bytes |
| Protocol version | 1 |
| Default read timeout | 0.25 seconds |
| Default command timeout | 1.5 seconds |

## Envelope

```json
{
  "version": 1,
  "type": "command",
  "seq": 18,
  "device_id": "raspberry-pi",
  "timestamp_ms": 1792000000000,
  "payload": {}
}
```

Required fields are version, type, sequence, device ID, nonnegative timestamp in milliseconds, and an object payload. Oversized, malformed, incomplete, incorrectly typed, or unsupported-version frames are rejected.

## Message types

- `hello`
- `status`
- `capabilities`
- `measurement`
- `command`
- `ack`
- `error`
- `heartbeat`

## Commands

| Command | Intended response | Current firmware support |
|---|---|---|
| `GET_STATUS` | state, faults, output state | None |
| `GET_CAPABILITIES` | firmware and supported functions | None |
| `READ_MEASUREMENTS` | available sensor values and quality | None |
| `START_TEST` | acknowledged bounded test transition | None |
| `STOP_TEST` | acknowledged test stop | None |
| `SET_PWM` | acknowledged PWM request | None; PWM unconfigured |
| `SET_DIRECTION` | acknowledged direction request | None; pin unconfigured |
| `STOP_MOTOR` | acknowledged immediate safe output | None |
| `GET_FAULTS` | latched/active faults | None |

## Example command

```json
{"version":1,"type":"command","seq":18,"device_id":"raspberry-pi","timestamp_ms":1792000000000,"payload":{"command":"GET_STATUS","arguments":{}}}
```

## Example acknowledgment

```json
{"version":1,"type":"ack","seq":44,"device_id":"STM32-ADS","timestamp_ms":1792000000010,"payload":{"reply_to":18,"result":{"state":"READY","faults":[]}}}
```

## Example error

```json
{"version":1,"type":"error","seq":45,"device_id":"STM32-ADS","timestamp_ms":1792000000011,"payload":{"reply_to":19,"code":"INVALID_STATE","message":"Motor is not armed"}}
```

## Response correlation and stale data

Every request uses a monotonically increasing sequence number. Responses identify the request with `payload.reply_to`. The backend ignores responses for a different request and ignores messages from a different device ID. If no matching response arrives by the command deadline, it raises a communication timeout.

The backend also implements a versioned `heartbeat` request using the same
sequence/reply correlation. The current firmware does not respond to it; the
simulation adapter does.

## Error handling

- Device `error` messages become explicit backend exceptions containing code and message.
- Invalid JSON, types, versions, frame sizes, or response bodies become protocol errors.
- An empty read is retried only until the bounded deadline.
- Motor-control commands are rejected locally before any serial write unless control is explicitly enabled in code after verification.

## Safe disconnect

The current release never enables physical motor control. When future verified control is enabled, disconnect first sends `STOP_MOTOR` and requires an acknowledgment. The serial port is closed even if acknowledgment fails, but the backend raises `SafeDisconnectError` so the loss of confirmed safe state cannot be hidden. Reconnection must begin stopped and unarmed; it must never restore the preceding PWM value.

## Simulation adapter

`SimulatedSTM32Connection` implements status, capabilities, measurements, supported commands, faults, and stop-on-disconnect without a serial port. Simulated RPM is intentionally `null` because no RPM sensor is configured in the real firmware/hardware evidence.
