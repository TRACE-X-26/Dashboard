"""Conservative, deterministic summaries; no learned model or invented hardware thresholds."""
import math
import statistics

ALGORITHM='trace-x-matched-baseline-v1'

class PredictiveModel:
    """Optional interface; no model is instantiated or claimed trained."""
    def predict(self,features,context): raise NotImplementedError

def analyze(samples, *, completed, source, baselines=None, limits=None, test_id=None, context=None):
    report=dict(algorithm_version=ALGORITHM,condition='INSUFFICIENT_DATA',health_score=None,
                source=source,findings=[],features={},model_trained=False)
    if not completed:report['condition']='TEST_INCOMPLETE';return report
    valid=[s for s in samples if not s.get('quality')]
    for channel in ('voltage','current','rpm','temperature','power'):
        unique={}
        for sample in valid:
            value=sample['values'].get(channel)
            timestamp=sample.get('raw',{}).get('measurements',{}).get(channel,{}).get('timestamp_ms')
            if value is not None:unique[(timestamp,value)]=value
        values=list(unique.values())
        report['features'][channel]=dict(count=len(values),mean=statistics.fmean(values) if values else None,
            std=statistics.pstdev(values) if values else None,min=min(values) if values else None,max=max(values) if values else None)
    if len(valid)<5:
        report['findings']=['Too few valid, calibrated, in-window acquisition samples'];return report
    if any(f['count']<5 for f in report['features'].values()):
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
    required={'voltage','current','rpm','temperature','power'}
    if set(envelopes)!=required:
        report['findings']=['Incomplete baseline acceptance envelope'];return report
    stability=baseline.get('max_std',{})
    if set(stability)!=required:
        report['findings']=['Validated per-channel stability limits required'];return report
    penalties=0
    for channel,bounds in envelopes.items():
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
            penalties+=1;report['findings'].append(f'{channel} outside approved mean/stability envelope')
    report['health_score']=max(0,100-20*penalties)
    report['condition']='HEALTHY' if not penalties else 'WARNING'
    report['score_basis']='20-point penalty per channel mean or standard deviation outside the approved envelope; engineering index, not probability.'
    return report
