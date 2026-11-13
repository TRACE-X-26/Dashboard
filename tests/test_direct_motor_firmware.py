"""Production firmware regression: optional quality versus electrical protection."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from tests import test_bounded_motor as bounded

ROOT=Path(__file__).resolve().parents[1]

class DirectMotorFirmwareTests(unittest.TestCase):
    def test_both_firmware_trees_keep_electrical_protection_without_optional_sensors(self):
        cc=shutil.which('cc')
        if not cc:self.skipTest('Host C compiler unavailable')
        with tempfile.TemporaryDirectory() as directory:
            for tree in ('ADS','FinalFirmware/ADS'):
                with self.subTest(tree=tree):
                    source=ROOT/tree/'Core/Src'
                    exe=Path(directory)/'sensors'
                    subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror',
                        '-I',str(ROOT/'tests/hal_stub'),'-I',str(ROOT/tree/'Core/Inc'),
                        '-DADS_SENSOR_WIRING_VERIFIED=0','-DADS_INA219_CALIBRATED=1','-DADS_PROTECTION_LIMITS_VERIFIED=1',
                        '-DADS_TEMPERATURE_ENABLED=1','-DADS_TEMPERATURE_CALIBRATED=0',
                        '-DSENSOR_SOURCE="'+str(source/'ads_sensors.c')+'"',
                        str(ROOT/'tests/optional_motor_sensors_harness.c'),
                        str(source/'ads_acquisition.c'),str(source/'ads_ina219.c'),
                        str(source/'ads_protection.c'),'-o',str(exe)],check=True,capture_output=True)
                    subprocess.run([str(exe)],check=True)

    def test_downstream_supervised_motor_needs_no_confirmation_but_still_needs_power_check(self):
        harness=bounded.BoundedMotorTests()
        bounded.BoundedMotorTests.setUpClass()
        try:
            replies=harness.circuit_results([harness.heartbeat(),harness.frame('ARM_TEST',2),
                harness.frame('START_TEST',3,pwm_percent=10,duration_ms=1000,direction='FORWARD'),
                harness.frame('PREPARE_TEST_POWER',4),b'+',
                harness.frame('START_TEST',5,pwm_percent=10,duration_ms=1000,direction='FORWARD'),
                harness.frame('EMERGENCY_STOP',6),harness.frame('GET_STATUS',7)],'downstream-supervised')
            self.assertTrue(replies[2]['accepted'])
            self.assertEqual(replies[3]['reason'],'POWER_CHECK_REQUIRED')
            self.assertTrue(replies[5]['accepted'])
            self.assertEqual(replies[7]['state'],'LOCKOUT')
            self.assertEqual(replies[7]['applied_pwm_percent'],0)
        finally:bounded.BoundedMotorTests.tearDownClass()
