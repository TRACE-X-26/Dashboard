"""Opt-in passive telemetry receiver. Contains no motor/serial write operation."""
from __future__ import annotations

import csv
import io
import json
import threading
import time
from datetime import datetime, timezone

from .history import parse_csv


class LiveMonitor:
    def __init__(self, port: str = '', baud: int = 115200, transport_factory=None):
        self.port, self.baud = port, baud
        self.transport_factory = transport_factory or self._open_serial
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._connected = False
        self._error = None
        self._channels = {}
        self._sequence = 0
        self._phase = 'UNKNOWN'
        self._warnings = []
        self._last_receive = None

    @staticmethod
    def _open_serial(port, baud):
        import fcntl
        import termios
        import serial
        transport = serial.Serial(port, baud, timeout=.25, exclusive=True)
        try:
            # Kernel exclusion also rejects non-cooperating collector processes.
            fcntl.ioctl(transport.fileno(), termios.TIOCEXCL)
        except Exception:
            transport.close()
            raise
        return transport

    def start(self):
        if not self.port or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='stm32-passive-reader')
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        transport = None
        try:
            transport = self.transport_factory(self.port, self.baud)
            with self._lock:
                self._connected = True
            buffer = b''
            dropping = False
            while not self._stop.is_set():
                chunk = transport.read(256)
                for byte in chunk:
                    if byte == 10:
                        if dropping:
                            with self._lock:
                                self._warnings = ['FRAME_TOO_LARGE']
                        elif buffer:
                            try:
                                self.feed(buffer.decode('utf-8'))
                            except UnicodeDecodeError:
                                with self._lock:
                                    self._warnings = ['INVALID_UTF8']
                        buffer, dropping = b'', False
                    elif not dropping:
                        buffer += bytes([byte])
                        if len(buffer) > 4096:
                            buffer, dropping = b'', True
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            if transport:
                transport.close()
            with self._lock:
                self._connected = False

    def feed(self, line: str):
        """Normalize one frame, retaining independent per-channel receipt times."""
        timestamp = datetime.now(timezone.utc).isoformat()
        received = time.monotonic()
        row = {'received_at': timestamp, 'raw_message': line.strip()}
        if line.lstrip().startswith('{'):
            try:
                frame = json.loads(line)
                if not isinstance(frame, dict):
                    raise ValueError('Expected JSON object')
                payload = frame.get('payload', {})
                values = payload.get('result', frame) if isinstance(payload, dict) else frame
                if not isinstance(values, dict):
                    raise ValueError('Expected measurement object')
                if 'measurements' in values:
                    from .protocol import decode_message, MessageType
                    from .collector import validate_measurements
                    message = decode_message(line)
                    if message.message_type is not MessageType.MEASUREMENT or message.device_id != 'STM32-ADS':
                        raise ValueError('Unexpected measurement source')
                    measurements = validate_measurements(values)
                    mapping = {'voltage': 'voltage', 'current': 'current', 'power': 'recorded_power',
                               'temperature': 'temperature', 'rpm': 'rpm'}
                    with self._lock:
                        self._sequence += 1
                        self._last_receive = received
                        self._warnings = []
                        for name, item in measurements.items():
                            key = mapping[name]
                            if item['valid']:
                                self._channels[key] = {'value': item['value'], 'timestamp': timestamp,
                                                       'timestamp_ms': item['timestamp_ms'], '_received': received}
                            else:
                                self._channels.pop(key, None)
                                self._warnings.append(name.upper() + '_INVALID')
                    return
                row.update({k: v for k, v in values.items() if isinstance(v, (str, int, float))})
                row['received_at'], row['raw_message'] = timestamp, ''
            except (ValueError, TypeError):
                with self._lock:
                    self._warnings = ['INVALID_JSON_FRAME']
                return
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader(); writer.writerow(row)
        parsed = parse_csv(stream.getvalue(), {})
        with self._lock:
            self._sequence += 1
            self._last_receive = received
            self._warnings = sorted({w['code'] for w in parsed['warnings']})
            for event in parsed['events']:
                self._phase = 'RUNNING' if event['event'] == 'MOTOR_START' else 'AFTER_STOP'
            if 'DEVICE_RESET' in self._warnings:
                self._phase = 'UNKNOWN'
                self._channels.clear()
            if 'SENSOR_OR_COMMUNICATION_MESSAGE' in self._warnings:
                # Do not keep showing a failed sensor's previous value as current.
                if any(s in line.upper() for s in ('TEMP', 'DS18')):
                    self._channels.pop('temperature', None)
                if 'INA219' in line.upper():
                    for key in ('voltage', 'current', 'recorded_power', 'input_power'):
                        self._channels.pop(key, None)
            for sample in parsed['samples']:
                for key in ('voltage', 'current', 'rpm', 'temperature', 'recorded_power', 'input_power', 'direction'):
                    if sample.get(key) is not None:
                        self._channels[key] = {'value': sample[key], 'timestamp': timestamp, '_received': received}

    def snapshot(self):
        with self._lock:
            now = time.monotonic()
            channels = {k: {'value': v['value'], 'timestamp': v['timestamp'],
                            'age_seconds': round(now - v['_received'], 3),
                            'quality': 'STALE' if now - v['_received'] > 3 or not self._connected else 'UNCALIBRATED'}
                        for k, v in self._channels.items()}
            stale = self._last_receive is None or now - self._last_receive > 3
            return {'source': 'HARDWARE_UNVERIFIED', 'enabled': bool(self.port),
                    'connected': self._connected, 'stale': stale, 'error': self._error,
                    'sequence': self._sequence, 'recorded_motor_phase': self._phase,
                    'channels': channels, 'warnings': list(self._warnings),
                    'diagnosis': {'status': 'INSUFFICIENT_CALIBRATION', 'health_score': None,
                                  'reason': 'Live channels are not synchronized or calibrated. Motor limits/baseline and circuit asset/test-point mapping require verification.'},
                    'hardware_control': False}
