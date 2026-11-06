"""Production C controller/protocol over fake outputs; never drives a board."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from diagnostic_platform.protocol import CommandName, MessageType, ProtocolMessage, command_message, encode_message, decode_message

ROOT = Path(__file__).resolve().parents[1]

# Synthetic configuration for tests only; not electrical bench evidence.
FAKE_BOARD_DEFINES=['ADS_PHYSICAL_OUTPUT_ENABLED=1','ADS_MOTOR_WIRING_VERIFIED=1',
            'ADS_KILL_SWITCH_VERIFIED=1','ADS_COMM_LOSS_STOP_VERIFIED=1',
            'ADS_SENSOR_WIRING_VERIFIED=1','ADS_INA219_CALIBRATED=1',
            'ADS_ENCODER_CALIBRATED=1','ADS_TEMPERATURE_CALIBRATED=1',
            'ADS_ENCODER_A_COUNTS_PER_REV=400','ADS_ENCODER_GEAR_NUM=1','ADS_ENCODER_GEAR_DEN=1',
            'ADS_BENCH_PWM_PERCENT=10','ADS_BENCH_MAX_DURATION_MS=1000','ADS_FORWARD_GPIO_LEVEL=0',
            'ADS_MOTOR_MIN_VOLTAGE_MV=9000','ADS_MOTOR_MAX_VOLTAGE_MV=15000','ADS_MOTOR_MAX_CURRENT_MA=1000','ADS_MOTOR_MAX_TEMPERATURE_MC=50000',
            'ADS_RELAY_POWER_PATH_VERIFIED=1','ADS_RELAY_POLARITY_VERIFIED=1','ADS_RELAY_SAFE_OUTPUT_VERIFIED=1']

class BoundedMotorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler missing')
        cls.temp = tempfile.TemporaryDirectory()
        cls.exe = str(Path(cls.temp.name) / 'bounded')
        subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror',
            '-I', str(ROOT/'ADS/Core/Inc'),
            *(str(ROOT/'ADS/Core/Src'/f) for f in ['ads_protocol.c','ads_test.c','ads_acquisition.c']),
            str(ROOT/'tests/bounded_motor_harness.c'), '-o', cls.exe], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def exchange(self, requests, mode='enabled'):
        out = subprocess.check_output([self.exe, mode], input=b''.join(requests))
        return [decode_message(line) for line in out.splitlines()]

    def frame(self, command, seq, **args):
        return encode_message(command_message(CommandName(command),seq,arguments=args))

    def heartbeat(self, seq=1):
        return encode_message(ProtocolMessage(MessageType.HEARTBEAT,seq,'raspberry-pi',{},0))

    def test_controller_deadlines_faults_rearm_limits_and_sensor_conversions(self):
        subprocess.run([self.exe],check=True)

    def test_default_disabled_and_stop_is_safe(self):
        out=self.exchange([self.heartbeat(),self.frame('ARM_TEST',2),self.frame('STOP_TEST',3)],'disabled')
        self.assertFalse(out[1].payload['result']['accepted'])
        self.assertEqual(out[1].payload['result']['reason'],'CONTROL_DISABLED')
        self.assertTrue(out[2].payload['result']['accepted'])
        self.assertEqual(out[2].payload['result']['applied_pwm_percent'],0)

    def test_correlated_commands_staging_duplicate_and_timed_events(self):
        start=self.frame('START_TEST',4,pwm_percent=10,duration_ms=1000,direction='FORWARD')
        out=self.exchange([self.heartbeat(),self.frame('ARM_TEST',2),
            self.frame('SET_PWM',3,pwm_percent=10),start,start,b'@',self.frame('GET_STATUS',5)])
        replies=[m for m in out if m.message_type is not MessageType.EVENT]
        self.assertEqual([m.payload['reply_to'] for m in replies],[1,2,3,4,4,5])
        self.assertEqual(replies[2].payload['result']['applied_pwm_percent'],0)
        self.assertTrue(replies[3].payload['result']['accepted'])
        self.assertFalse(replies[4].payload['result']['accepted'])
        events=[m for m in out if m.message_type is MessageType.EVENT]
        self.assertEqual([m.payload['event'] for m in events],['MOTOR_START','MOTOR_STOP'])
        self.assertEqual([m.timestamp_ms for m in events],[0,1000])
        self.assertEqual(events[1].payload['reason'],'COMPLETED')
        self.assertEqual(replies[-1].payload['result']['applied_pwm_percent'],0)

    def test_heartbeat_loss_latches_and_reconnect_needs_explicit_arm(self):
        out=self.exchange([self.heartbeat(),self.frame('ARM_TEST',2),b'@@',self.heartbeat(3),
            self.frame('START_TEST',4,pwm_percent=10,duration_ms=1000,direction='FORWARD'),
            self.frame('ARM_TEST',5)])
        self.assertEqual(out[-2].payload['result']['state'],'LOCKOUT')
        self.assertFalse(out[-2].payload['result']['accepted'])
        self.assertTrue(out[-1].payload['result']['accepted'])

    def test_cancel_repeated_stop_and_bad_pwm(self):
        out=self.exchange([self.heartbeat(),self.frame('ARM_TEST',2),
            self.frame('SET_PWM',3,pwm_percent=25),
            self.frame('START_TEST',4,pwm_percent=10,duration_ms=1000,direction='FORWARD'),
            self.frame('STOP_TEST',5),self.frame('STOP_TEST',5)])
        self.assertEqual(out[2].payload['result']['reason'],'PWM_OUT_OF_RANGE')
        events=[m for m in out if m.message_type is MessageType.EVENT]
        self.assertEqual(len(events),2)
        self.assertEqual(events[-1].payload['reason'],'CANCELLED')
        self.assertTrue(out[-1].payload['result']['accepted'])

    def test_argument_types_and_nested_values_cannot_override_limits(self):
        for args in [dict(pwm_percent=True,duration_ms=1000,direction='FORWARD'),
                     dict(pwm_percent=-10,duration_ms=1000,direction='FORWARD'),
                     dict(pwm_percent=10,duration_ms=0,direction='FORWARD'),
                     dict(pwm_percent=10,duration_ms=1000,direction='REVERSE'),
                     dict(nested=dict(pwm_percent=10),duration_ms=1000,direction='FORWARD')]:
            with self.subTest(args=args):
                out=self.exchange([self.heartbeat(),self.frame('ARM_TEST',2),self.frame('START_TEST',3,**args)])
                self.assertFalse(out[-1].payload.get('result',{}).get('accepted',False))
                self.assertFalse(any(m.message_type is MessageType.EVENT for m in out))

    def test_measurement_zero_values_sequence_and_electrical_pair(self):
        out=self.exchange([self.frame('READ_MEASUREMENTS',1)])[0].payload['result']
        self.assertGreater(out['sample_sequence'],0)
        self.assertEqual(out['electrical_sequence'],1)
        self.assertTrue(out['voltage_current_calibrated'])
        self.assertEqual(out['encoder_direction'],'STATIONARY')
        for key in ['current','power','rpm','temperature']:
            self.assertEqual(out['measurements'][key]['value'],0)
            self.assertTrue(out['measurements'][key]['valid'])

    def test_crc_firmware_interoperability_and_corrupt_frame_shutdown(self):
        good=encode_message(command_message(CommandName.GET_CAPABILITIES,1),checksum=True)
        out=self.exchange([good],'crc')
        self.assertEqual(out[0].payload['result']['integrity'],'CRC32')
        bad=good.replace(b'GET_CAPABILITIES',b'GET_DEVICE_INFO')
        out=self.exchange([bad,self.frame('GET_STATUS',2)],'crc')
        self.assertEqual(out[0].payload['code'],'CRC32_REQUIRED_OR_INVALID')
        self.assertEqual(out[1].payload['code'],'CRC32_REQUIRED_OR_INVALID')


class GatedOutputTests(unittest.TestCase):
    def test_actual_motor_adapter_with_fake_registers_and_both_relay_polarities(self):
        cc=shutil.which('cc')
        if not cc:
            self.skipTest('host compiler missing')
        # Synthetic compiler configuration ONLY for fake register testing, never a bench approval.
        flags=FAKE_BOARD_DEFINES
        with tempfile.TemporaryDirectory() as d:
            for active in [0,1]:
                exe=str(Path(d)/'output')
                subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror',
                    '-I',str(ROOT/'tests/hal_stub'),'-I',str(ROOT/'ADS/Core/Inc'),
                    *('-D'+f for f in flags),f'-DADS_RELAY_ACTIVE_LEVEL={active}',
                    str(ROOT/'ADS/Core/Src/ads_motor.c'),str(ROOT/'tests/bounded_output_harness.c'),
                    '-o',exe],check=True,capture_output=True)
                subprocess.run([exe],check=True)

    def test_gated_sources_compile_for_real_f401_headers_when_toolchain_available(self):
        candidates=list(Path('/Applications/STM32CubeIDE.app/Contents/Eclipse/plugins').glob(
            'com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.*/tools/bin/arm-none-eabi-gcc'))
        cc=shutil.which('arm-none-eabi-gcc') or (str(candidates[0]) if candidates else None)
        if not cc:
            self.skipTest('ARM GCC unavailable')
        includes=['Core/Inc','Drivers/STM32F4xx_HAL_Driver/Inc',
            'Drivers/STM32F4xx_HAL_Driver/Inc/Legacy','Drivers/CMSIS/Include',
            'Drivers/CMSIS/Device/ST/STM32F4xx/Include']
        # Syntax only: no output-enabled ELF is produced.
        for temperature_enabled in (0,1):
            subprocess.run([cc,'-mcpu=cortex-m4','-mthumb','-mfpu=fpv4-sp-d16',
            '-mfloat-abi=hard','-std=gnu11','-Wall','-Wextra','-Werror','-fsyntax-only',
            '-DUSE_HAL_DRIVER','-DSTM32F401xE',
            *('-I'+i for i in includes),*('-D'+d for d in FAKE_BOARD_DEFINES),
            '-DADS_RELAY_ACTIVE_LEVEL=0',f'-DADS_TEMPERATURE_ENABLED={temperature_enabled}',
            *(str(p.relative_to(ROOT/'ADS')) for p in (ROOT/'ADS/Core/Src').glob('*.c'))],
            cwd=ROOT/'ADS',check=True,capture_output=True)
