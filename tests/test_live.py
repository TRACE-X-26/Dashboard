import unittest
from unittest.mock import patch

from diagnostic_platform.live import LiveMonitor


class LiveMonitorTests(unittest.TestCase):
    def test_default_never_opens_serial(self):
        with patch.object(LiveMonitor, '_open_serial', side_effect=AssertionError('must not open')):
            monitor = LiveMonitor()
            monitor.start()
            self.assertFalse(monitor.snapshot()['enabled'])
            self.assertFalse(monitor.snapshot()['hardware_control'])

    def test_asynchronous_legacy_values_are_not_fabricated_power(self):
        monitor = LiveMonitor()
        monitor.feed('Voltage: 12.276 V')
        monitor.feed('Current: 0.134 A')
        state = monitor.snapshot()
        self.assertEqual(state['channels']['voltage']['value'], 12.276)
        self.assertNotIn('input_power', state['channels'])
        self.assertIsNone(state['diagnosis']['health_score'])

    def test_stale_channel_and_failed_sensor_do_not_appear_current(self):
        monitor = LiveMonitor()
        with patch('diagnostic_platform.live.time.monotonic', return_value=100):
            monitor.feed('Temperature: 31.4 C')
        with patch('diagnostic_platform.live.time.monotonic', return_value=104):
            self.assertEqual(monitor.snapshot()['channels']['temperature']['quality'], 'STALE')
        monitor.feed('TEMPERATURE SENSOR: NOT DETECTED')
        self.assertNotIn('temperature', monitor.snapshot()['channels'])

    def test_structured_motor_values_and_circuit_exclusion(self):
        monitor = LiveMonitor()
        monitor.feed('{"mode":"MOTOR","motor_voltage_V":12,"motor_current_A":0.5}')
        self.assertEqual(monitor.snapshot()['channels']['input_power']['value'], 6)
        monitor.feed('{"mode":"CIRCUIT","voltage":5}')
        self.assertEqual(monitor.snapshot()['channels']['voltage']['value'], 12)
        self.assertIn('NON_MOTOR_ROW_EXCLUDED', monitor.snapshot()['warnings'])

    def test_reset_and_event_state(self):
        monitor = LiveMonitor()
        monitor.feed('MOTOR_START')
        monitor.feed('Motor RPM: 78')
        self.assertEqual(monitor.snapshot()['recorded_motor_phase'], 'RUNNING')
        monitor.feed('reboot')
        self.assertEqual(monitor.snapshot()['channels'], {})
        self.assertEqual(monitor.snapshot()['recorded_motor_phase'], 'UNKNOWN')
