"""Single-owner bounded test orchestration. Default simulation uses ADS v1 on both sides."""
from __future__ import annotations
import copy
import json
import math
import os
import threading
import time
from pathlib import Path
from uuid import uuid4
from .automated_storage import RunStore, utcnow, run_summary
from .collector import validate_measurements
from .device_simulator import STM32Simulator
from .health_analysis import analyze
from .protocol import encode_message, ProtocolError
from .stm32 import STM32SerialConnection, CommunicationTimeout
from .test_registry import REGISTRY, registry
from .hardware_runtime import HardwareRuntime, RunRejected

TERMINAL={'COMPLETED','FAILED','CANCELLED','EMERGENCY_STOP','DISCONNECTED'}
TRANSITIONS={
 'IDLE':{'PRECHECK'},'PRECHECK':{'ARMED'},'ARMED':{'RUNNING'},'RUNNING':{'STOPPING'},
 'STOPPING':{'ANALYZING'},'ANALYZING':{'PRECHECK','COMPLETED'},
}
class InterruptedRun(Exception):pass

def load_hardware_profile(path):
    if not path:raise RunRejected('Hardware disabled: no commissioning profile configured')
    profile=json.loads(Path(path).read_text())
    if not isinstance(profile,dict):raise RunRejected('Hardware profile must be a JSON object')
    mode=profile.get('operating_mode','NORMAL')
    if mode not in ('NORMAL','SUPERVISED_TEST'):raise RunRejected('Unknown motor operating mode')
    required=('wiring_verified','relay_verified','kill_switch_verified',
              'communication_stop_verified','calibration_verified','operator_enable','protection_limits_verified')
    if mode=='NORMAL':required+=('interlock_verified','power_feedback_installed','power_feedback_wiring_verified')
    else:required+=('supervised_testing_approved',)
    if type(profile.get('power_feedback_installed',False)) is not bool:
        raise RunRejected('power_feedback_installed must be a boolean')
    if profile.get('power_feedback_installed') is True and profile.get('power_feedback_wiring_verified') is not True:
        raise RunRejected('Installed power feedback wiring requires verification')
    missing=[k for k in required if profile.get(k) is not True]
    if missing:raise RunRejected('Hardware blocked: '+', '.join(missing))
    if not all(profile.get(k) for k in ('evidence_id','calibration_id','firmware_version','asset_id','fixture_id')):
        raise RunRejected('Commissioning evidence, calibration and firmware identity required')
    if profile.get('device_id')!='STM32-ADS' or not profile.get('serial_identity'):
        raise RunRejected('Validated physical device identity required')
    if type(profile.get('fixed_pwm_percent')) is not int or not 1<=profile['fixed_pwm_percent']<=100:
        raise RunRejected('Approved fixed duty required')
    if type(profile.get('max_duration_ms')) is not int or not 1<=profile['max_duration_ms']<=30000:
        raise RunRejected('Approved duration required')
    limits=profile.get('limits',{})
    if type(profile.get('temperature_enabled', True)) is not bool:
        raise RunRejected('temperature_enabled must be a boolean')
    for k in ('max_current','min_voltage','max_voltage') + (('max_temperature',) if profile.get('temperature_enabled', True) else ()):
        v=limits.get(k)
        if type(v) not in (int,float) or not math.isfinite(v) or v<=0:raise RunRejected('Validated positive physical limit required: '+k)
    if limits['min_voltage']>=limits['max_voltage']:raise RunRejected('Invalid voltage limits')
    return profile

class AutomatedTestEngine:
    def __init__(self,path,*,hardware_profile_path='',connection_factory=None,publish=None,
                 hardware_control_enabled=False, serial_baud=115200, serial_read_timeout=.25,
                 serial_command_timeout=.35):
        import fcntl
        path=Path(path).resolve()
        self._owner_file=open(str(path)+'.automation.lock','a+')
        try: fcntl.flock(self._owner_file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self._owner_file.close();raise RuntimeError('Another backend owns automated testing')
        self.store=RunStore(path);self.hardware_profile_path=hardware_profile_path
        self.connection_factory=connection_factory;self.publish=publish
        self.hardware_runtime=HardwareRuntime(enabled=hardware_control_enabled,baud=serial_baud,
            read_timeout=serial_read_timeout,command_timeout=serial_command_timeout)
        self._mutex=threading.Lock();self._data_lock=threading.RLock();self._cancel=threading.Event()
        self._emergency=threading.Event();self._thread=None;self.current=None
    def recover(self):self.store.recover()
    def available(self,mode):
        if mode not in {'simulation','hardware'}:raise RunRejected('Unknown mode')
        if mode=='simulation':return registry(mode)
        try:
            self.hardware_runtime.require_permission()
            p=load_hardware_profile(self.hardware_profile_path)
        except (ValueError,OSError) as exc:
            return [{**item,'available':False,'unavailable_reason':str(exc)} for item in registry(mode)]
        procedures=registry(mode,p['fixed_pwm_percent'],True)
        preflight=self.hardware_runtime.snapshot()
        if not preflight['ready']:
            return [{**item,'available':False,'unavailable_reason':item.get('unavailable_reason') or preflight['reason']}
                    for item in procedures]
        return procedures
    def start(self,request):
        mode=request.get('mode','simulation')
        if mode not in {'simulation','hardware'}:raise RunRejected('Unknown mode')
        if mode=='hardware':self.hardware_runtime.require_permission()
        profile=load_hardware_profile(self.hardware_profile_path) if mode=='hardware' else {
            'limits':{'max_current':10.,'max_temperature':80.,'min_voltage':9.,'max_voltage':15.},
            'baselines':{},'evidence_id':'SOFTWARE_SIMULATION_ONLY','calibration_id':'SYNTHETIC'}
        if mode=='hardware' and request.get('device_id')!=profile['asset_id']:
            raise RunRejected('Requested motor does not match commissioned asset')
        if mode=='hardware' and profile.get('operating_mode','NORMAL')=='SUPERVISED_TEST' and request.get('supervised_confirmed') is not True:
            raise RunRejected('Fresh supervised operator / physical cutoff confirmation required')
        if mode=='hardware' and request.get('operator_authorized') is not True:
            raise RunRejected('Fresh operator authorization required for this sequence')
        # An explicitly authorized API request can attempt fresh preflight even
        # without a cached probe. No ARM is sent until in-thread checks pass.
        procedures=registry(mode,profile['fixed_pwm_percent'],True) if mode=='hardware' else self.available(mode)
        eligible={p['id']:p for p in procedures if p['available']}
        tests=request.get('tests')
        if request.get('run_all') is True:tests=list(eligible)
        if not isinstance(tests,list) or not tests or len(tests)>20 or len(set(tests))!=len(tests):
            raise RunRejected('Select a nonempty unique list of at most 20 procedures')
        for test in tests:
            if test not in eligible:raise RunRejected(f'Unavailable procedure {test}: see registry')
        duration=request.get('duration_ms',30000)
        if type(duration) is not int or not 100<=duration<=min(30000,profile.get('max_duration_ms',30000)):
            raise RunRejected('Duration outside approved bounds (100–30000 ms)')
        if not self._mutex.acquire(blocking=False):raise RunRejected('Another sequence is active')
        try:
            self._cancel.clear();self._emergency.clear()
            run=dict(id=str(uuid4()),state='IDLE',mode=mode,source='SIMULATION' if mode=='simulation' else 'stm32_serial',
                device_id=request.get('device_id','MOTOR-001'),created_at=utcnow(),ended_at=None,
                configuration={'tests':tests,'duration_ms':duration,'scenario':None if mode=='hardware' else request.get('scenario','healthy'),
                    'operating_mode':profile.get('operating_mode','SIMULATION'),
                    'supervised_confirmed':request.get('supervised_confirmed') is True},
                commissioning=profile,progress=0,active_test=None,steps=[],outcome=None,health_score=None,
                algorithm_version='trace-x-matched-baseline-v1',stop_confirmed=False,report_reference=None)
            self.store.create(run)
            with self._data_lock:self.current=run
            self._thread=threading.Thread(target=self._run,args=(run,profile),daemon=True,name='trace-x-test-owner')
            self._thread.start();return copy.deepcopy(run)
        except Exception:self._mutex.release();raise
    def snapshot(self):
        with self._data_lock:return copy.deepcopy(run_summary(self.current))
    def stop(self,emergency=False):
        if emergency:self._emergency.set()
        self._cancel.set()
        return {'accepted':True,'state':'STOP_REQUESTED','physical_stop_confirmed':False}
    def close(self):
        self.stop()
        if self._thread:self._thread.join(timeout=4)
        if self._thread and self._thread.is_alive(): raise RuntimeError('Test owner failed to shut down')
        self._owner_file.close()
    def _save(self,run):
        with self._data_lock:self.store.save(run)
    def _transition(self,run,state):
        old=run['state']
        if old in TERMINAL or (state not in TERMINAL-{'COMPLETED'} and state not in TRANSITIONS.get(old,set())):
            raise RuntimeError(f'Invalid transition {old} -> {state}')
        with self._data_lock:
            run['state']=state;self.store.event(run['id'],{'from':old,'to':state,'timestamp':utcnow()});self.store.save(run)
    def _check_cancel(self):
        if self._cancel.is_set():raise InterruptedRun('Emergency stop' if self._emergency.is_set() else 'Operator cancelled')
    def read_sensors(self,port,connection_factory=None):
        if not self._mutex.acquire(blocking=False):return None
        connection=None
        try:
            connection=(connection_factory() if connection_factory else
                STM32SerialConnection(port=port,require_crc=True,allow_motor_control=False,command_timeout=.7))
            connection.connect()
            return connection.execute('READ_MEASUREMENTS')
        finally:
            try:
                if connection:connection.disconnect()
            finally:self._mutex.release()

    def preflight(self):
        """Explicit read-only probe; never ARM, heartbeat, PWM or STOP writes."""
        if not self._mutex.acquire(blocking=False):
            raise RunRejected('A test or sensor acquisition owns the serial port; retry when idle')
        connection=None
        report=dict(ready=False,reason='',firmware_hardware_control=None,source='stm32_serial',
                    read_only=True,capabilities=None,status=None)
        try:
            profile=load_hardware_profile(self.hardware_profile_path)
            connection=(self.connection_factory('hardware',REGISTRY[f"pwm_{profile['fixed_pwm_percent']}"],
                        'healthy',profile) if self.connection_factory else self.hardware_runtime.connection(profile))
            # A newly created injected transport must obey the same read-only
            # rule, including disconnect (which otherwise sends STOP_MOTOR).
            connection.allow_motor_control=False
            connection.connect()
            caps=self._read(connection,'GET_CAPABILITIES')
            report.update(capabilities=caps,firmware_hardware_control=caps.get('hardware_control'))
            status=self._read(connection,'GET_STATUS');report['status']=status
            self.hardware_runtime.validate_contract(profile,caps,status,profile['max_duration_ms'])
            raw=self._read(connection,'READ_MEASUREMENTS')
            # Read a later MCU tick instead of comparing ticks with host time.
            self._read(connection,'GET_STATUS')
            self.hardware_runtime.validate_sensors(profile,raw,connection.last_timestamp_ms)
            self.hardware_runtime.require_permission()
            report.update(ready=True,reason='Read-only preflight passed; Start still requires fresh authorization and repeated checks')
        except Exception as exc:
            report['reason']=str(exc)
        finally:
            try:
                if connection:connection.disconnect()
            finally:self._mutex.release()
        return self.hardware_runtime.remember(report)

    def _connection(self,mode,procedure,scenario,profile):
        if self.connection_factory:return self.connection_factory(mode,procedure,scenario,profile)
        if mode=='simulation':
            sim=STM32Simulator(procedure.pwm or 10,scenario)
            return STM32SerialConnection(port='SIMULATION',device_id=sim.device_id,allow_motor_control=True,
                require_crc=True,command_timeout=.35,transport_factory=lambda *_:sim)
        return self.hardware_runtime.connection(profile,control=True)
    def _read(self,connection,command):
        for attempt in range(2):
            try:return connection.execute(command)
            except CommunicationTimeout:
                if attempt:raise
                if self.current:self.store.event(self.current['id'],{'event':'READ_RETRY','command':command,'attempt':attempt+1})
                # Read-only retry; never retry a start/arm or reconnect into a run.
    def _command(self,connection,command,args=None):
        if command not in {'STOP_TEST','STOP_MOTOR','EMERGENCY_STOP'}:self._check_cancel()
        result=connection.execute(command,args)
        if result.get('accepted') is not True:raise RunRejected(f'{command}: {result.get("reason","rejected")}')
        return result
    def _events(self,connection,run):
        events=connection.drain_events()
        for event in events:self.store.event(run['id'],{**event.to_dict(),'test_id':run['active_test']})
        return events
    def _measure(self,connection,run,procedure,step,started):
        raw=self._read(connection,'READ_MEASUREMENTS')
        from .ina219 import normalize_branches
        branches=normalize_branches(raw)
        raw={**raw,'protocol_frame':connection.last_response_frame,'test_id':procedure.id,'device_session_id':step['device_session_id']}
        quality=[]
        try:channels=validate_measurements(raw)
        except ValueError:
            self.store.sample(run['id'],raw,['INVALID_CHANNELS']);raise
        values={k:(v['value'] if v['valid'] else None) for k,v in channels.items()}
        temperature_enabled=run['commissioning'].get('temperature_enabled',True)
        required_channels=('voltage','current','power','rpm') + (('temperature',) if temperature_enabled else ())
        if not all(channels[name]['valid'] for name in required_channels):quality.append('INVALID_SENSOR_DATA')
        if type(raw.get('electrical_sequence')) is not int:quality.append('INVALID_SENSOR_DATA')
        if raw.get('voltage_current_calibrated') is not True or (temperature_enabled and raw.get('temperature_calibrated') is not True):
            quality.append('CALIBRATION_UNVERIFIED')
        if raw.get('encoder_calibrated') is not True:quality.append('RPM_UNCALIBRATED')
        # Completion/sample ages are MCU ticks, independent of host delivery time.
        status=self._read(connection,'GET_STATUS')
        received_tick=connection.last_timestamp_ms
        with self._data_lock:
            run['requested_pwm_percent']=status.get('requested_pwm_percent')
            run['applied_pwm_percent']=status.get('applied_pwm_percent')
            run['device_state']=status.get('state')
            run['faults']=status.get('faults',[])
            run['operating_mode']=status.get('operating_mode',run['commissioning'].get('operating_mode','SIMULATION'))
            run['power_feedback_installed']=status.get('power_feedback_installed',False)
            run['power_feedback_state']=status.get('power_feedback_state','NOT_REPORTED')
            run['measured_pwm_percent']=None
        for name,item in channels.items():
            if name not in required_channels:continue
            if ((received_tick-item['timestamp_ms'])&0xffffffff)>(3000 if name=='temperature' else 1500):quality.append('STALE_'+name.upper())
        prefixes=('electrical','encoder') + (('temperature',) if temperature_enabled else ())
        for prefix in prefixes:
            begin=raw.get(prefix+'_started_ms');end=raw.get(prefix+'_completed_ms')
            if type(begin) is not int or type(end) is not int:quality.append('MISSING_ACQUISITION_INTERVAL');continue
            if started is not None and ((begin-started)&0xffffffff)>0x7fffffff:quality.append('PRE_START_INTERVAL')
            if ((end-begin)&0xffffffff)>3000:quality.append('INVALID_ACQUISITION_INTERVAL')
        if any(s['raw'].get('sample_sequence')==raw.get('sample_sequence') for s in step['samples']):
            quality.append('REPEATED_ACQUISITION')
        raw.update(requested_pwm_percent=status.get('requested_pwm_percent'),
            applied_pwm_percent=status.get('applied_pwm_percent'),motor_state=status.get('state'),
            shutdown_reason=status.get('stop_reason'),stm32_status_timestamp_ms=received_tick,
            operating_mode=run.get('operating_mode'),power_feedback_state=run.get('power_feedback_state'),
            power_feedback_installed=run.get('power_feedback_installed'))
        record={'values':values,'quality':sorted(set(quality)),'raw':raw,'procedure':procedure.id}
        record['sample_id']=self.store.sample(run['id'],raw,record['quality']);step['samples'].append(record)
        if values.get('voltage') is not None and values.get('current') is not None and not quality:
            record['values']['power']=values['voltage']*values['current']
        with self._data_lock:
            run['latest_measurement']={**values,'input_power':values.get('power'),'sequence':len(step['samples']),
                'timestamp':utcnow(),'quality':record['quality'],'source':run['source'],
                'rpm_calibrated':raw.get('encoder_calibrated') is True,'temperature_enabled':temperature_enabled,
                'ina219':branches}
        if self.publish:self.publish(raw,run['source'])
        if 'INVALID_SENSOR_DATA' in quality or 'CALIBRATION_UNVERIFIED' in quality or any(q.startswith('STALE') for q in quality):
            raise RunRejected('Sensor acquisition invalid or stale; motor condition unknown')
        limits=run['commissioning']['limits']
        faults=[]
        if abs(values['current'])>=limits['max_current']:faults.append('OVERCURRENT')
        if temperature_enabled and values['temperature']>=limits['max_temperature']:faults.append('OVERHEATING')
        if not limits['min_voltage']<=values['voltage']<=limits['max_voltage']:faults.append('SUPPLY_OUT_OF_RANGE')
        if procedure.pwm==0 and values['rpm']!=0:faults.append('NOT_STATIONARY')
        if faults:
            run['confirmed_limit_faults']=faults
            raise RunRejected(','.join(faults))
        if run['mode']=='hardware':
            self.hardware_runtime.validate_sensors(run['commissioning'],raw,received_tick)
        return status
    def _run(self,run,profile):
        connection=None;completed=False
        try:
            for index,identifier in enumerate(run['configuration']['tests']):
                self._check_cancel();procedure=REGISTRY[identifier];self._transition(run,'PRECHECK')
                run['active_test']=identifier
                run['stop_confirmed']=False
                step=dict(test_id=identifier,device_session_id=str(uuid4()),samples=[],result=None);run['steps'].append(step)
                connection=self._connection(run['mode'],procedure,run['configuration']['scenario'],profile)
                connection.connect()
                caps=self._read(connection,'GET_CAPABILITIES');status=self._read(connection,'GET_STATUS')
                run['firmware_version']=caps.get('firmware_version');run['device_capabilities']=caps
                if caps.get('integrity')!='CRC32':raise RunRejected('CRC32-capable firmware required')
                if run['mode']=='hardware':
                    self.hardware_runtime.validate_contract(profile,caps,status,run['configuration']['duration_ms'])
                if status.get('applied_pwm_percent')!=0:raise RunRejected('Output not initially disabled')
                connection.seed_sequence(status.get('last_control_seq',0))
                # Sensors need their first acquisition after boot. Only read while
                # output is confirmed zero; never retry a motor start.
                warmup_deadline=time.monotonic()+2.5
                while True:
                    connection.heartbeat()
                    try:self._measure(connection,run,procedure,step,None);break
                    except RunRejected as exc:
                        if run['mode']!='hardware' or not str(exc).startswith('Sensor acquisition invalid or stale') or time.monotonic()>=warmup_deadline:raise
                        self._check_cancel();self._cancel.wait(.1)
                self._transition(run,'ARMED');started=None;device_run_id=None
                if procedure.pwm:
                    arm_args={'supervised_confirmed':True} if profile.get('operating_mode')=='SUPERVISED_TEST' else None
                    self._command(connection,'ARM_TEST',arm_args)
                    self._command(connection,'SET_PWM',{'pwm_percent':procedure.pwm})
                    response=self._command(connection,'START_TEST',dict(pwm_percent=procedure.pwm,duration_ms=run['configuration']['duration_ms'],direction='FORWARD'))
                    if (response.get('state')!='RUNNING' or response.get('applied_pwm_percent')!=procedure.pwm or
                        response.get('requested_pwm_percent')!=procedure.pwm or type(response.get('started_ms')) is not int or
                        type(response.get('run_id')) is not int):
                        raise RunRejected('START_TEST acknowledgment did not confirm requested/applied PWM and running state')
                    started=response['started_ms'];device_run_id=response['run_id']
                    connection.heartbeat()
                    events=self._events(connection,run)
                    if not any(e.payload.get('event')=='MOTOR_START' and e.payload.get('run_id')==device_run_id and
                               e.timestamp_ms==started and e.payload.get('applied_pwm_percent')==procedure.pwm for e in events):
                        raise RunRejected('Confirmed start event missing')
                self._transition(run,'RUNNING');deadline=time.monotonic()+run['configuration']['duration_ms']/1000
                last_heartbeat=0.;step['samples']=[];stop_event=None
                while time.monotonic()<deadline:
                    self._check_cancel()
                    if time.monotonic()-last_heartbeat>=.4:
                        connection.heartbeat();last_heartbeat=time.monotonic()
                    status=self._measure(connection,run,procedure,step,started)
                    for event in self._events(connection,run):
                        if event.payload.get('event')=='MOTOR_STOP' and event.payload.get('run_id')==device_run_id:stop_event=event
                    if procedure.pwm and status.get('state')=='LOCKOUT':raise RunRejected('STM32 lockout')
                    if stop_event:
                        if stop_event.payload.get('reason')!='COMPLETED':raise RunRejected('STM32 stopped unexpectedly')
                        break
                    with self._data_lock:
                        elapsed=run['configuration']['duration_ms']/1000-(deadline-time.monotonic())
                        run['elapsed_seconds']=round(max(0,elapsed),3)
                        run['progress']=min(99,int(100*(index+max(0,elapsed)/(run['configuration']['duration_ms']/1000))/len(run['configuration']['tests'])))
                    self._save(run)
                    self._cancel.wait(.05)
                self._transition(run,'STOPPING')
                # Allow bounded normal completion before an idempotent stop confirmation.
                if procedure.pwm and stop_event is None:
                    self._cancel.wait(.05);connection.heartbeat()
                    events=self._events(connection,run)
                    stop_event=next((e for e in events if e.payload.get('event')=='MOTOR_STOP' and e.payload.get('run_id')==device_run_id),None)
                response=self._command(connection,'STOP_TEST')
                if not self._stopped(response):raise RunRejected('Stopped state and zero output not acknowledged')
                if procedure.pwm and (stop_event is None or stop_event.payload.get('reason')!='COMPLETED'):
                    raise RunRejected('Normal completion event missing')
                run['stop_confirmed']=True
                run['applied_pwm_percent']=0;run['device_state']=response.get('state','STOPPED')
                if stop_event:
                    stopped=stop_event.timestamp_ms
                    for sample in step['samples']:
                        if any(((sample['raw'][p+'_completed_ms']-stopped)&0xffffffff)<0x80000000 for p in (('electrical','encoder','temperature') if profile.get('temperature_enabled',True) else ('electrical','encoder'))):
                            sample['quality'].append('AFTER_STOP_INTERVAL')
                            self.store.update_quality(sample['sample_id'],sample['quality'])
                self._transition(run,'ANALYZING')
                step['result']=analyze(step['samples'],completed=True,source=run['source'],baselines=profile.get('baselines'),test_id=identifier,context={
                    'device_id':run['device_id'],'calibration_id':profile['calibration_id'],
                    'fixture_id':profile.get('fixture_id'),'pwm_percent':procedure.pwm,'direction':'FORWARD'})
                # Raw records remain even when analysis excludes acquisition intervals.
                self.store.event(run['id'],{'test_id':identifier,'analysis':step['result']})
                connection.disconnect();connection=None
            completed=True;run['progress']=100;run['outcome']='COMPLETED'
            reports=[s['result'] for s in run['steps']]
            run['condition']='INSUFFICIENT_DATA' if any(r['health_score'] is None for r in reports) else ('WARNING' if any(r['condition']=='WARNING' for r in reports) else 'HEALTHY')
            run['health_score']=None if any(r['health_score'] is None for r in reports) else min(r['health_score'] for r in reports)
            self._transition(run,'COMPLETED')
        except InterruptedRun as exc:
            run['reason']=str(exc);run['outcome']='TEST_INCOMPLETE'
            self._transition(run,'EMERGENCY_STOP' if self._emergency.is_set() else 'CANCELLED')
        except (ConnectionError,CommunicationTimeout,ProtocolError) as exc:
            run['reason']=str(exc);run['outcome']='TEST_INCOMPLETE';self._transition(run,'DISCONNECTED')
        except Exception as exc:
            run['reason']=str(exc);run['outcome']='TEST_INCOMPLETE';self._transition(run,'FAILED')
        finally:
            if connection:
                try:
                    command='EMERGENCY_STOP' if self._emergency.is_set() else 'STOP_TEST'
                    result=self._command(connection,command)
                    run['stop_confirmed']=self._stopped(result)
                    if run['stop_confirmed']:
                        run['applied_pwm_percent']=0;run['device_state']=result.get('state','STOPPED')
                except Exception as exc:run['stop_error']=str(exc);run['stop_confirmed']=False
                try:connection.disconnect()
                except Exception as exc:run['disconnect_error']=str(exc)
            run['report_reference']=f'/api/automated/runs/{run["id"]}/report'
            if not completed:
                run['health_score']=None
                run['condition']='FAULT' if run.get('confirmed_limit_faults') else 'TEST_INCOMPLETE'
            if self.publish and run['mode']=='hardware':self.publish(None,run['source'])
            try:
                with self._data_lock:
                    run['ended_at']=utcnow()
                    from .motor_csv import render_motor_csv
                    destination=Path(self.store.path).parent/'automated_csv'/(run['id']+'.csv')
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    journal=self.store.get(run['id'])
                    destination.write_text(render_motor_csv({**journal,**run}),encoding='utf-8')
                    run['csv_path']=str(destination)
                    self._save(run)
            except Exception as exc:
                run['ended_at']=utcnow();run['state']='FAILED';run['outcome']='TEST_INCOMPLETE';run['reason']='Persistence failed: '+str(exc)
                run['health_score']=None
            finally:
                try:self.store.release(run['id'])
                finally:self._mutex.release()

    @staticmethod
    def _stopped(response):
        return (response.get('accepted') is True and type(response.get('applied_pwm_percent')) is int and
                response['applied_pwm_percent']==0 and response.get('state') in {'STOPPED','DISARMED','LOCKOUT'})
