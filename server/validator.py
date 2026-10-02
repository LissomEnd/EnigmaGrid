import hashlib
import json
import math
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/"solver"/"runtime"
if str(RUNTIME/"src") not in sys.path:
    sys.path.insert(0,str(RUNTIME/"src"))

def _stable(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=True)

def fingerprint(result):
    return hashlib.sha256(_stable(result).encode()).hexdigest()

def _round(x):
    return round(float(x),6)

def _demo_expected(lease):
    cfg=lease["config"]; rounds=int(cfg.get("hash_rounds",2000)); best=None
    for unit in range(int(lease["start_unit"]),int(lease["end_unit"])):
        h=f"{lease['segment_id']}:{unit}".encode()
        for _ in range(rounds): h=hashlib.sha256(h).digest()
        hx=h.hex()
        if best is None or hx<best["hash"]: best={"unit":unit,"hash":hx}
    return {"summary":{"engine":"demo_hash","best":best,"rounds":rounds}}
def _event_candidate(c,lease):
    import numpy as np
    from search.event_stochastic import (
        EVENT_NAMES,SHELLS,QTAB,decrypt_score_event,key_arrays
    )
    from search.cpu_numba import encode,decode
    if not isinstance(c,dict): raise ValueError("candidate_not_object")
    unit=int(c["unit"]); start=int(lease["start_unit"]); end=int(lease["end_unit"])
    if unit<start or unit>=end: raise ValueError("candidate_unit_outside_lease")
    cfg=lease["config"]; count=int(cfg.get("count_per_unit",32768))
    base=int(cfg.get("base_attempt",310000000)); attempt=int(c["attempt"])
    lo=base+unit*count
    if attempt<lo or attempt>=lo+count: raise ValueError("candidate_attempt_outside_unit")
    plain=str(c["plaintext"])
    if len(plain)!=72 or not plain.isalpha() or plain.upper()!=plain:
        raise ValueError("invalid_plaintext")
    key=c["key"]; si,rings,pos,plug=key_arrays(key)
    m=c.get("metrics",{}); ev=m.get("event",{})
    reverse={v:k for k,v in EVENT_NAMES.items()}
    kind=reverse.get(ev.get("kind"))
    if kind is None: raise ValueError("invalid_event_kind")
    at=int(ev.get("at",-1))
    if at<0 or at>=72: raise ValueError("invalid_event_at")
    param=int(ev.get("distance",1))
    rpos=pos.copy()
    if kind==6:
        rp=str(ev.get("restart_positions",""))
        if len(rp)!=4: raise ValueError("missing_restart_positions")
        rpos=encode(rp)
    msg=json.loads((RUNTIME/"data"/"messages"/"p1030680.json").read_text(encoding="utf-8"))
    inp=encode(msg["ciphertext"])
    obj,q,bal,out=decrypt_score_event(inp,SHELLS[si],rings,pos,plug,QTAB,
                                      int(kind),at,param,rpos)
    got=decode(out)
    if got!=plain: raise ValueError("plaintext_not_reproducible")
    score=float(c["score"])
    if not math.isfinite(score) or abs(score-float(obj))>0.0002:
        raise ValueError("score_not_reproducible")
    clean={
      "unit":unit,"attempt":attempt,"score":_round(obj),"plaintext":plain,
      "key":key,
      "metrics":{"objective":_round(obj),"quadgram_full":_round(q),
                 "balanced_segments":_round(bal),"pairs":len(key.get("plugboard",[])),
                 "event":ev}
    }
    return clean
def validate_result(engine,result,lease):
    if not isinstance(result,dict): raise ValueError("result_not_object")
    if engine=="demo_hash":
        expected=_demo_expected(lease)
        if result.get("summary")!=expected["summary"]:
            raise ValueError("demo_result_mismatch")
        clean=expected
        return clean,fingerprint(clean)
    if engine!="event_stochastic_v1":
        raise ValueError("unsupported_engine")
    summary=result.get("summary",{})
    if summary.get("engine")!="event_stochastic_v1":
        raise ValueError("engine_summary_mismatch")
    expected_units=int(lease["end_unit"])-int(lease["start_unit"])
    if int(summary.get("units",-1))!=expected_units:
        raise ValueError("unit_count_mismatch")
    candidates=result.get("candidates",[])
    if not isinstance(candidates,list) or len(candidates)>32:
        raise ValueError("candidate_count_invalid")
    topk=int(lease["config"].get("topk",6))
    expected_count=min(max(topk,12),topk*expected_units)
    if len(candidates)!=expected_count:
        raise ValueError("candidate_count_mismatch")
    clean_candidates=[_event_candidate(c,lease) for c in candidates]
    clean_candidates.sort(key=lambda x:(-x["score"],x["attempt"]))
    clean={"summary":{"engine":"event_stochastic_v1","units":expected_units},
           "candidates":clean_candidates}
    return clean,fingerprint(clean)
