"""Conservative, deterministic summaries; no learned model or invented hardware thresholds."""
import math
import statistics

ALGORITHM='trace-x-matched-baseline-v1'

class PredictiveModel:
    """Optional interface; no model is instantiated or claimed trained."""
    def predict(self,features,context): raise NotImplementedError

def analyze(samples, *, completed, source, baselines=None, limits=None, test_id=None, context=None, required_channels=None):
    report=dict(algorithm_version=ALGORITHM,condition='INSUFFICIENT_DATA',health_score=None,
                source=source,findings=[],features={},model_trained=False)
    if not completed:report['condition']='TEST_INCOMPLETE';return report
    required=set(required_channels or ('voltage','current','rpm','power'))
    required.discard('temperature')
    if not required or not required <= {'voltage','current','rpm','power'}:
        report['findings']=['Invalid required feature configuration'];return report
    # Report available electrical observations even while encoder calibration is pending.
    # RPM remains excluded from a definitive assessment until calibrated.
    valid=[s for s in samples if not (set(s.get('quality',[]))-{'RPM_UNCALIBRATED'})]
    report['required_channels']=sorted(required)
    report['unverified_channels']=['rpm'] if any('RPM_UNCALIBRATED' in s.get('quality',[]) for s in samples) else []
    for channel in ('voltage','current','rpm','power'):
        unique={}
        for sample in valid:
            value=sample['values'].get(channel)
            timestamp=sample.get('raw',{}).get('measurements',{}).get(channel,{}).get('timestamp_ms')
            if type(value) in (int,float) and math.isfinite(value):
                key=timestamp if timestamp is not None else id(sample)
                unique.setdefault(key,value)
        values=list(unique.values())
        report['features'][channel]=dict(count=len(values),mean=statistics.fmean(values) if values else None,
            std=statistics.pstdev(values) if values else None,min=min(values) if values else None,max=max(values) if values else None)
    if len(valid)<5:
        report['findings']=['Too few valid, calibrated, in-window acquisition samples'];return report
    if any(report['features'][name]['count']<5 for name in required):
        report['findings']=['At least five distinct valid acquisitions per channel required'];return report
    baseline=(baselines or {}).get(test_id,{})
    if baseline.get('validated') is not True or type(baseline.get('independent_runs')) is not int or baseline.get('independent_runs',0)<3:
        report['findings']=['No approved baseline from at least three independent matched runs'];return report
    if context is not None and baseline.get('operating_context')!=context:
        report['findings']=['Baseline operating conditions/calibration do not match this run'];return report
    if source!='SIMULATION':
        evidence=baseline.get('evidence_run_ids',[])
        if not isinstance(evidence,list) or len(set(evidence))<3:
            report['findings']=['Independent healthy-run evidence identifiers required'];return report
    # The profile supplies approved per-channel acceptance envelopes; no estimated thresholds are promoted automatically.
    envelopes=baseline.get('ranges',{})
    if not required<=set(envelopes):
        report['findings']=['Incomplete baseline acceptance envelope'];return report
    stability=baseline.get('max_std',{})
    if not required<=set(stability):
        report['findings']=['Validated per-channel stability limits required'];return report
    penalties=0
    if required & set(report['unverified_channels']):
        report['findings']=['Required RPM calibration is unverified'];return report
    for channel in sorted(required):
        bounds=envelopes[channel]
        if not isinstance(bounds,(list,tuple)) or len(bounds)!=2:
            report['findings']=['Invalid baseline envelope'];return report
        low,high=bounds
        if not all(type(v) in (int,float) and math.isfinite(v) for v in bounds) or low>high:
            report['findings']=['Invalid baseline envelope'];return report
        feature=report['features'][channel]
        if feature['mean'] is None: return report
        max_std=stability.get(channel)
        if type(max_std) not in (int,float) or not math.isfinite(max_std) or max_std<0:
            report['findings']=['Invalid stability envelope'];return report
        if not low<=feature['mean']<=high or feature['std']>max_std:
            penalties+=1
            report['findings'].append(f'{channel} outside approved mean/stability envelope')
        report.setdefault('comparisons',[]).append(dict(channel=channel,observed=feature['mean'],
            reference_range=[low,high],difference_from_midpoint=feature['mean']-(low+high)/2,
            observed_std=feature['std'],approved_max_std=max_std,
            interpretation='Investigate operating load, supply and sensor validity before assigning a mechanical cause.'))
    report['health_score']=max(0,100-20*penalties) if source=='SIMULATION' else None
    report['condition']='HEALTHY' if not penalties else 'WARNING'
    report['score_basis']='Legacy simulation index.' if source=='SIMULATION' else 'No validated physical numerical scoring model; approved envelope classification only.'
    return report
