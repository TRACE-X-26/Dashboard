"""Opt-in passive telemetry receiver. Contains no motor/serial write operation."""
from __future__ import annotations

import csv
import io
import json
import math
import threading
import time
from datetime import datetime, timezone

from .history import FIELDS, parse_csv
from .text_telemetry import PlainTextMotorParser, SerialLineDecoder


class LiveMonitor:
    def __init__(self, port: str = '', baud: int = 115200, transport_factory=None):
        self.port, self.baud = port, baud
        self._external_active=False
        self.transport_factory = transport_factory or self._open_serial
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._connected = False
        self._error = None
        self._channels = {}
        self._circuit_channels = {}
        self._ina219 = {}
        self._sequence = 0
        self._phase = 'UNKNOWN'
        self._warnings = []
        self._last_receive = None
        self._text_motor = PlainTextMotorParser()
        self._motor_sample = None
        self._motor_sample_received = None
        self._complete_motor_frames = 0
        self._motor_format = 'UNKNOWN'

    @staticmethod
    def _open_serial(port, baud):
        import fcntl
        import termios
        import serial
        transport = serial.Serial(port, baud, timeout=.25, exclusive=True)
        try:
            # Kernel exclusion rejects subsequent opens, including non-cooperating readers.
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
                self._error = None
                self._invalidate_motor()
                self._channels.clear()
                self._circuit_channels.clear()
                self._text_motor.reset()
            decoder = SerialLineDecoder()
            last_byte = time.monotonic()
            while not self._stop.is_set():
                chunk = transport.read(256)
                if not chunk:
                    if time.monotonic() - last_byte > 3:
                        decoder.reset()
                        with self._lock:
                            self._text_motor.reset()
                            self._warnings = ['SERIAL_TELEMETRY_TIMEOUT']
                    continue
                last_byte = time.monotonic()
                lines, errors = decoder.feed(chunk)
                if errors:
                    decoder.reset()
                    with self._lock:
                        self._invalidate_motor()
                        self._text_motor.reset()
                        self._warnings = errors
                    continue  # Corruption order within this chunk is unknown; reject the entire chunk.
                for line in lines:
                    self.feed(line)
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            try:
                if transport:
                    transport.close()
            finally:
                with self._lock:
                    self._connected = False

    def _invalidate_motor(self):
        self._motor_sample = None
        self._motor_sample_received = None
        for key in ('voltage', 'current', 'rpm', 'recorded_power', 'input_power', 'encoder_status', 'ina219_status'):
            self._channels.pop(key, None)

    def _json_motor_sample(self, sample, timestamp, received, frame_format):
        self._channels.pop('encoder_status', None)
        self._channels.pop('ina219_status', None)
        power = sample.get('recorded_power')
        if power is None:
            power = sample.get('input_power')
        values = {'voltage': sample.get('voltage'), 'current': sample.get('current'),
                  'power': power, 'motor_rpm': sample.get('rpm')}
        self._motor_format = frame_format
        self._motor_sample = None
        if all(type(v) in (int, float) and math.isfinite(v) for v in values.values()):
            self._motor_sample = {**values, 'encoder_status': 'NOT_REPORTED', 'ina219_status': 'NOT_REPORTED',
                                  'timestamp': timestamp, 'timestamp_basis': 'HOST_RECEIVE_TIME',
                                  'source': 'stm32_serial', 'format': frame_format, 'quality': 'UNCALIBRATED',
                                  'power_origin': 'REPORTED_BY_STM32' if sample.get('recorded_power') is not None else 'CALCULATED_FROM_SAME_JSON_MESSAGE',
                                  'association': 'STRUCTURED_MESSAGE'}
            self._motor_sample_received = received
            self._complete_motor_frames += 1

    def feed(self, line: str):
        """Normalize one frame, retaining independent per-channel receipt times."""
        from .protocol import unprotect_frame
        try: line=unprotect_frame(line.encode('utf-8')).decode('utf-8')
        except ValueError:
            with self._lock:
                self._invalidate_motor();self._ina219.clear();self._warnings=['CRC32_INVALID']
            return
        timestamp = datetime.now(timezone.utc).isoformat()
        received = time.monotonic()
        row = {'received_at': timestamp, 'raw_message': line.strip()}
        text_warnings = []
        if not line.lstrip().startswith('{'):
            with self._lock:
                update = self._text_motor.feed(line, received=received, timestamp=timestamp)
                text_warnings = update.warnings
                if update.invalidate:
                    self._invalidate_motor()
                if update.recognized:
                    self._motor_format = 'plain_text'
                    self._sequence += 1
                    self._last_receive = received
                    self._warnings = update.warnings
                    if update.changes.get('temperature_status') not in (None,'CONNECTED'):
                        self._channels.pop('temperature',None)
                    mapping = {'motor_rpm': 'rpm', 'power': 'recorded_power'}
                    for field, value in update.changes.items():
                        self._channels[mapping.get(field, field)] = {'value': value, 'timestamp': timestamp, '_received': received}
                    if update.sample is not None:
                        self._motor_sample = update.sample
                        self._motor_sample_received = received
                        self._complete_motor_frames += 1
                    return
        if line.lstrip().startswith('{'):
            try:
                frame = json.loads(line)
                if not isinstance(frame, dict):
                    raise ValueError('Expected JSON object')
                payload = frame.get('payload', {})
                values = payload.get('result', frame) if isinstance(payload, dict) else frame
                if not isinstance(values, dict):
                    raise ValueError('Expected measurement object')
                if str(values.get('mode', '')).upper() == 'CIRCUIT':
                    self._feed_circuit(values, timestamp, received)
                    return
                if 'measurements' in values:
                    from .protocol import decode_message, MessageType
                    from .collector import validate_measurements
                    message = decode_message(line)
                    if message.message_type is not MessageType.MEASUREMENT or message.device_id != 'STM32-ADS':
                        raise ValueError('Unexpected measurement source')
                    measurements = validate_measurements(values)
                    from .ina219 import normalize_branches
                    branches=normalize_branches(values)
                    mapping = {'voltage': 'voltage', 'current': 'current', 'power': 'recorded_power',
                               'temperature': 'temperature', 'rpm': 'rpm'}
                    with self._lock:
                        self._text_motor.reset()
                        self._sequence += 1
                        self._last_receive = received
                        self._warnings = []
                        self._ina219={name:{**branch,'timestamp':timestamp,'_received':received} for name,branch in branches.items()}
                        for name, item in measurements.items():
                            key = mapping[name]
                            if item['valid']:
                                self._channels[key] = {'value': item['value'], 'timestamp': timestamp,
                                                       'timestamp_ms': item['timestamp_ms'], '_received': received}
                            else:
                                self._channels.pop(key, None)
                                self._warnings.append(name.upper() + '_INVALID')
                        self._json_motor_sample({mapping[name]: item['value'] if item['valid'] else None
                                                 for name, item in measurements.items()}, timestamp, received, 'ads_json_v1')
                        if 'ina219' in values:
                            self._channels['ina219_status']={'value':branches['MOTOR']['status'],'timestamp':timestamp,'_received':received}
                            if self._motor_sample is not None:self._motor_sample['ina219_status']=branches['MOTOR']['status']
                    return
                if any(key in values for aliases in FIELDS.values() for key in aliases):
                    with self._lock:
                        self._text_motor.reset()
                        self._invalidate_motor()
                row.update({k: v for k, v in values.items() if isinstance(v, (str, int, float))})
                row['received_at'], row['raw_message'] = timestamp, ''
            except (ValueError, TypeError):
                with self._lock:
                    self._invalidate_motor()
                    self._text_motor.reset()
                    self._ina219.clear()
                    self._warnings = ['INVALID_JSON_FRAME']
                return
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader(); writer.writerow(row)
        parsed = parse_csv(stream.getvalue(), {})
        with self._lock:
            self._sequence += 1
            self._last_receive = received
            self._warnings = sorted({w['code'] for w in parsed['warnings']} | set(text_warnings))
            for event in parsed['events']:
                self._phase = 'RUNNING' if event['event'] == 'MOTOR_START' else 'AFTER_STOP'
            if 'DEVICE_RESET' in self._warnings:
                self._phase = 'UNKNOWN'
                self._channels.clear()
                self._circuit_channels.clear()
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
                        if type(sample[key]) in (int, float) and not math.isfinite(sample[key]):
                            self._channels.pop(key, None)
                            self._warnings.append(key.upper() + '_INVALID')
                            continue
                        self._channels[key] = {'value': sample[key], 'timestamp': timestamp, '_received': received}
                if line.lstrip().startswith('{'):
                    self._text_motor.reset()
                    self._json_motor_sample(sample, timestamp, received, 'flat_json')

    def _feed_circuit(self, values, timestamp, received):
        asset, point = values.get('asset_id'), values.get('test_point_id')
        if not isinstance(asset, str) or not 1 <= len(asset) <= 80 or not isinstance(point, str) or not 1 <= len(point) <= 40:
            with self._lock:
                self._warnings = ['NON_MOTOR_ROW_EXCLUDED', 'CIRCUIT_IDENTIFIERS_REQUIRED']
            return
        mapping = {'test_point_voltage_V': 'test_point_voltage', 'circuit_supply_voltage_V': 'circuit_supply_voltage',
                   'circuit_current_A': 'circuit_current', 'circuit_power_W': 'circuit_power'}
        with self._lock:
            self._text_motor.reset()
            self._sequence += 1
            self._last_receive = received
            self._warnings = []
            for field, channel in mapping.items():
                if field not in values:
                    continue
                key = (asset, point, channel)
                value = values[field]
                if type(value) not in (int, float) or not math.isfinite(value) or values.get('valid', True) is not True:
                    self._circuit_channels.pop(key, None)
                    self._warnings.append(channel.upper() + '_INVALID')
                    continue
                self._circuit_channels[key] = {'asset_id': asset, 'point_id': point, 'channel': channel,
                                               'value': value, 'timestamp': timestamp, '_received': received,
                                               'calibration_version': str(values.get('calibration_version', ''))[:80] or None}
            while len(self._circuit_channels) > 128:
                self._circuit_channels.pop(next(iter(self._circuit_channels)))

    def publish_acquisition(self,result):
        """Only the validated hardware command owner calls this, never simulation."""
        with self._lock:
            self._external_active=result is not None
            self._connected=result is not None
        if result is not None:
            self.feed(json.dumps(dict(version=1,type='measurement',seq=result.get('sample_sequence',0),
                device_id='STM32-ADS',timestamp_ms=0,payload={'result':result})))

    def snapshot(self):
        with self._lock:
            now = time.monotonic()
            channels = {k: {'value': v['value'], 'timestamp': v['timestamp'],
                            'age_seconds': round(now - v['_received'], 3),
                            'quality': 'STALE' if now - v['_received'] > 3 or not self._connected else 'UNCALIBRATED'}
                        for k, v in self._channels.items()}
            stale = self._last_receive is None or now - self._last_receive > 3
            motor_sample = None
            if self._motor_sample is not None:
                age = now - self._motor_sample_received
                motor_sample = {**self._motor_sample, 'hardware_connected': self._connected,
                                'age_seconds': round(age, 3), 'stale': age > 3 or not self._connected,
                                'quality': 'STALE' if age > 3 or not self._connected else 'UNCALIBRATED'}
            circuit_channels = [{k: v for k, v in channel.items() if k != '_received'} |
                                {'age_seconds': round(now - channel['_received'], 3),
                                 'quality': 'STALE' if now - channel['_received'] > 3 or not self._connected else 'UNCALIBRATED'}
                                for channel in self._circuit_channels.values()]
            ina219={}
            for name,branch in self._ina219.items():
                age=now-branch['_received'];expired=not self._connected or age>3
                view={k:v for k,v in branch.items() if k!='_received'}
                view.update(age_seconds=round(age,3),stale=expired)
                if expired:
                    view.update(status='STALE',reported_status=branch['status'],connected=False,valid=False,
                        measurements={k:{**v,'valid':False,'value':None} for k,v in branch['measurements'].items()})
                ina219[name]=view
            return {'source': 'HARDWARE_UNVERIFIED', 'enabled': bool(self.port) or self._external_active,
                    'connected': self._connected, 'stale': stale, 'error': self._error,
                    'sequence': self._sequence, 'recorded_motor_phase': self._phase,
                    'channels': channels, 'warnings': list(self._warnings),
                    'circuit_channels': circuit_channels,
                    'ina219': ina219,
                    'hardware_connected': self._connected, 'motor_sample': motor_sample,
                    'motor_format': self._motor_format, 'complete_motor_frames': self._complete_motor_frames,
                    'pending_motor_fields': self._text_motor.missing_fields,
                    'diagnosis': {'status': 'INSUFFICIENT_CALIBRATION', 'health_score': None,
                                  'reason': 'Live channels are not synchronized or calibrated. Motor limits/baseline and circuit asset/test-point mapping require verification.'},
                    'hardware_control': False}
