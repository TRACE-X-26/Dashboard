from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .models import MotorMeasurement


PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 4096


class ProtocolError(ValueError):
    pass


class MessageType(str, Enum):
    HELLO = "hello"
    STATUS = "status"
    CAPABILITIES = "capabilities"
    MEASUREMENT = "measurement"
    COMMAND = "command"
    ACK = "ack"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


class CommandName(str, Enum):
    GET_STATUS = "GET_STATUS"
    GET_CAPABILITIES = "GET_CAPABILITIES"
    READ_MEASUREMENTS = "READ_MEASUREMENTS"
    START_TEST = "START_TEST"
    STOP_TEST = "STOP_TEST"
    SET_PWM = "SET_PWM"
    SET_DIRECTION = "SET_DIRECTION"
    STOP_MOTOR = "STOP_MOTOR"
    GET_FAULTS = "GET_FAULTS"


@dataclass(frozen=True)
class ProtocolMessage:
    message_type: MessageType
    sequence: int
    device_id: str
    payload: dict
    timestamp_ms: int
    version: int = PROTOCOL_VERSION

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "type": self.message_type.value,
            "seq": self.sequence,
            "device_id": self.device_id,
            "timestamp_ms": self.timestamp_ms,
            "payload": self.payload,
        }


def encode_message(message: ProtocolMessage) -> bytes:
    if message.version != PROTOCOL_VERSION:
        raise ProtocolError("Unsupported protocol version")
    if message.sequence < 0 or not message.device_id:
        raise ProtocolError("Invalid message identity")
    frame = json.dumps(
        message.to_dict(), separators=(",", ":"), allow_nan=False
    ).encode("utf-8") + b"\n"
    if len(frame) > MAX_FRAME_BYTES:
        raise ProtocolError("Protocol frame exceeds maximum size")
    return frame


def decode_message(frame: bytes | str) -> ProtocolMessage:
    raw = frame.encode("utf-8") if isinstance(frame, str) else frame
    if len(raw) > MAX_FRAME_BYTES:
        raise ProtocolError("Protocol frame exceeds maximum size")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Invalid JSON protocol frame") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("Protocol frame must be a JSON object")
    if payload.get("version") != PROTOCOL_VERSION:
        raise ProtocolError("Unsupported protocol version")
    try:
        message_type = MessageType(payload["type"])
        sequence = int(payload["seq"])
        device_id = str(payload["device_id"])
        timestamp_ms = int(payload["timestamp_ms"])
        body = payload["payload"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError("Incomplete or invalid protocol frame") from exc
    if sequence < 0 or timestamp_ms < 0 or not device_id or not isinstance(body, dict):
        raise ProtocolError("Invalid protocol frame fields")
    return ProtocolMessage(message_type, sequence, device_id, body, timestamp_ms)


def command_message(
    command: CommandName,
    sequence: int,
    *,
    device_id: str = "raspberry-pi",
    arguments: dict | None = None,
) -> ProtocolMessage:
    return ProtocolMessage(
        MessageType.COMMAND,
        sequence,
        device_id,
        {"command": command.value, "arguments": arguments or {}},
        int(time.time() * 1000),
    )


def encode_measurement(measurement: MotorMeasurement) -> str:
    """Backward-compatible version-1 motor measurement frame."""
    payload = {
        "type": "measurement",
        "version": PROTOCOL_VERSION,
        "seq": measurement.sequence,
        "timestamp": measurement.timestamp.isoformat(),
        "motor_voltage_v": measurement.voltage,
        "motor_current_a": measurement.current,
        "rpm": measurement.rpm,
        "temperature_c": measurement.temperature,
        "resistance_ohm": measurement.resistance,
        "vibration_rms": measurement.vibration_rms,
    }
    return json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n"


def decode_measurement(line: str) -> MotorMeasurement:
    if len(line.encode("utf-8")) > MAX_FRAME_BYTES:
        raise ProtocolError("Measurement frame exceeds maximum size")
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError("Invalid JSON measurement frame") from exc
    if payload.get("type") != "measurement" or payload.get("version") != PROTOCOL_VERSION:
        raise ProtocolError("Unsupported measurement frame")
    try:
        measurement = MotorMeasurement(
            voltage=payload.get("motor_voltage_v"),
            current=payload.get("motor_current_a"),
            rpm=payload.get("rpm"),
            temperature=payload.get("temperature_c"),
            resistance=payload.get("resistance_ohm"),
            vibration_rms=payload.get("vibration_rms"),
            sequence=int(payload["seq"]),
            timestamp=datetime.fromisoformat(payload["timestamp"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError("Incomplete or invalid measurement frame") from exc
    numeric_values = (
        measurement.voltage,
        measurement.current,
        measurement.rpm,
        measurement.temperature,
        measurement.resistance,
        measurement.vibration_rms,
    )
    if any(value is not None and not math.isfinite(value) for value in numeric_values):
        raise ProtocolError("Measurement values must be finite")
    return measurement
