"""Procedures supported by evidence; unavailable entries are never run silently."""
from dataclasses import asdict, dataclass
from .motor_health import TEST_CATALOG

@dataclass(frozen=True)
class Procedure:
    id: str
    name: str
    pwm: int | None = None
    kind: str = 'motor'
    reason: str = ''

PROCEDURES = [Procedure('idle', 'Safe idle / stationary and zero-offset observations', 0)]
PROCEDURES += [Procedure(f'pwm_{p}', f'{p}% PWM operational response', p) for p in (10,25,50,75,100)]
PROCEDURES += [
    Procedure('pwm_ramp','Controlled PWM ramp',reason='Firmware supports one fixed duty per run; continuous ramp is not commissioned.'),
    Procedure('load_response','Load/friction response',reason='No automated load actuator or validated matched load protocol.'),
    Procedure('startup','Startup characteristics',reason='Acquisition timing/bandwidth and startup reference not validated.'),
    Procedure('noise','Electrical noise / sensor stability',reason='High-bandwidth acquisition and noise acceptance limits not validated.'),
    Procedure('baseline','Record healthy baseline',reason='Independent healthy labeling and repeated matched-run baseline approval required.'),
    Procedure('circuit_voltage','Circuit probe voltage',kind='circuit',reason='ADC scaling, protection, range and probe-state commissioning missing; use guided capture.'),
    Procedure('circuit_current','Circuit branch current',kind='circuit',reason='INA219 #2 identity and calibrated branch telemetry not commissioned.'),
    Procedure('continuity','Continuity / resistance',kind='circuit',reason='Verified excitation, isolation and input protection are not documented.'),
    Procedure('circuit_faults','Circuit 4 reference comparison',kind='circuit',reason='Use existing operator-guided Circuit 4 capture; rules remain provisional.'),
]
# CSV target labels exist for these exploratory duties, but no approved full protocol.
PROCEDURES += [Procedure(f'pwm_{p}',f'{p}% exploratory recording setpoint',p,
    reason='CSV target label only; duration, fixture and safety acceptance are not a validated procedure.') for p in (5,15,20)]
PROCEDURES += [Procedure(f'historical_test_{i:02d}',TEST_CATALOG.get(i,(f'Historical experiment test_{i:02d}',None))[0],
    reason='Historical run identifier is not an executable procedure; fixture/action/limits must be mapped and approved.') for i in range(1,16)]

REGISTRY = {p.id:p for p in PROCEDURES}
# These are existing simulation fault-injection scenarios, not physical fault commands.
SCENARIOS = ('healthy','overloaded','undervoltage','overheating','stalled','sensor_failure','communication_loss')

def registry(mode='simulation', fixed_pwm=None, ready=False):
    out=[]
    for p in PROCEDURES:
        reason=p.reason
        if mode=='hardware' and not reason:
            if not ready: reason='Hardware commissioning profile and operator authorization required.'
            elif p.pwm not in (0,fixed_pwm): reason='Not the single bench-approved fixed duty.'
        out.append({**asdict(p),'available':not reason,'unavailable_reason':reason})
    return out
