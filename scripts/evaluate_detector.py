"""Compare legacy rules and temporal detection on labeled local videos, without saving frames.

Example: python scripts/evaluate_detector.py --fall data/fall.mp4 --normal data/sitting.mp4
Labels are clip-level. This reports events, not clinical accuracy or fall-onset latency.
"""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.config import load_settings
from backend.fall_detector import TemporalFallDetector, features
from backend.model_loader import MediaPipePoseEstimator
from backend.risk import assess


def evaluate_video(path, label, settings, sample_fps):
    import cv2
    path=Path(path)
    if not path.is_file(): raise ValueError(f"No existe el video: {path}")
    video=cv2.VideoCapture(str(path))
    fps=video.get(cv2.CAP_PROP_FPS)
    if not video.isOpened() or not fps>0:
        video.release()
        raise ValueError(f"No se pudo abrir el video o leer sus FPS: {path}")
    estimator=MediaPipePoseEstimator(Path(settings.models.pose.model_path))
    temporal=TemporalFallDetector()
    history=deque(maxlen=settings.pipeline.history_size)
    result={"file":path.name,"label":label,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "source_fps":fps,"sampling_fps":sample_fps,"samples":0,"legacy_usable":0,"temporal_usable":0,
            "legacy_first_event_s":None,"temporal_first_event_s":None,"transitions":[],"pose_ms":[]}
    frame_number=0
    stride=max(1,round(fps/sample_fps))
    try:
        while True:
            valid,frame=video.read()
            if not valid: break
            at=frame_number/fps
            frame_number+=1
            if (frame_number-1)%stride: continue
            ok,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,85])
            if not ok: raise ValueError("No se pudo codificar el frame")
            started=time.perf_counter()
            pose=estimator.estimate(jpeg.tobytes(),at)
            result["pose_ms"].append((time.perf_counter()-started)*1000)
            result["samples"]+=1
            if pose is None: history.clear()
            else: history.append(pose)
            while history and at-history[0].timestamp>settings.pipeline.history_seconds: history.popleft()
            legacy=assess(list(history),settings.risk)
            if "no_pose" not in legacy.reasons: result["legacy_usable"]+=1
            if features(pose,at,settings.risk): result["temporal_usable"]+=1
            previous=temporal.phase
            updated=temporal.update(pose,at,settings.risk)
            if previous!=temporal.phase:
                result["transitions"].append({"at":round(at,3),"state":temporal.phase})
            for name,event in (("legacy",legacy),("temporal",updated)):
                key=name+"_first_event_s"
                if event.level=="critical" and result[key] is None: result[key]=round(at,3)
    finally:
        estimator.close();video.release()
    if not result["samples"]: raise ValueError(f"Video sin muestras: {path}")
    latencies=sorted(result.pop("pose_ms"))
    result["pose_p95_ms"]=round(latencies[min(len(latencies)-1,int(len(latencies)*.95))],1)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fall',action='append',default=[])
    parser.add_argument('--normal',action='append',default=[])
    parser.add_argument('--sample-fps',type=float,default=15)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/detector-video-comparison.json')
    args=parser.parse_args()
    if not args.fall or not args.normal or not 0<args.sample_fps<=60:
        parser.error('Incluye videos --fall y --normal; sample-fps debe estar entre 0 y 60')
    settings=load_settings()
    sources=[ROOT/'backend'/name for name in ('risk.py','fall_detector.py','model_loader.py')]
    frozen={str(path.relative_to(ROOT)):path.read_bytes() for path in sources}
    # Frozen settings for both algorithms; videos and frames never go to a notifier.
    rows=[evaluate_video(path,label,settings,args.sample_fps)
          for label,paths in (("fall",args.fall),("normal",args.normal)) for path in paths]
    summary={name:{
        "TP":sum(r['label']=='fall' and r[name+'_first_event_s'] is not None for r in rows),
        "FN":sum(r['label']=='fall' and r[name+'_first_event_s'] is None for r in rows),
        "FP":sum(r['label']=='normal' and r[name+'_first_event_s'] is not None for r in rows),
        "TN":sum(r['label']=='normal' and r[name+'_first_event_s'] is None for r in rows),
    } for name in ('legacy','temporal')}
    output={"scope":"Exploratory clip-level comparison; no clinical validation; no tuning on these clips",
            "implementation_sha256":{name:hashlib.sha256(data).hexdigest() for name,data in frozen.items()},
            "thresholds":settings.risk.model_dump(),"summary":summary,"videos":rows}
    if any((ROOT/name).read_bytes()!=data for name,data in frozen.items()):
        raise RuntimeError('El código cambió durante la evaluación; repite con una versión congelada')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary))


if __name__=='__main__': main()
