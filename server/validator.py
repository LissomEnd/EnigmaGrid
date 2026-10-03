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

def _letters(value, length):
    return isinstance(value,str) and len(value)==length and all("A"<=c<="Z" for c in value)

def _validate_key(key):
    # Validate before entering native code: encoded values index fixed-size arrays.
    if not isinstance(key,dict):raise ValueError("invalid_key")
    if not _letters(key.get("rings"),4) or not _letters(key.get("positions"),4):
        raise ValueError("invalid_key_positions")
    rotors=key.get("moving_rotors")
    if not isinstance(rotors,list) or len(rotors)!=3 or any(not isinstance(r,str) for r in rotors) or len(set(rotors))!=3:
        raise ValueError("invalid_moving_rotors")
    if not isinstance(key.get("reflector"),str) or not isinstance(key.get("greek"),str):
        raise ValueError("invalid_shell")
    pairs=key.get("plugboard",[])
    if not isinstance(pairs,list) or len(pairs)>13 or any(not _letters(p,2) for p in pairs):
        raise ValueError("invalid_plugboard")
    letters="".join(pairs)
    if len(set(letters))!=len(letters):raise ValueError("invalid_plugboard")

def _demo_expected(lease):
    cfg=lease["config"]; rounds=int(cfg.get("hash_rounds",2000)); best=None
    for unit in range(int(lease["start_unit"]),int(lease["end_unit"])):
        h=f"{lease['segment_id']}:{unit}".encode()
        for _ in range(rounds): h=hashlib.sha256(h).digest()
        hx=h.hex()
        if best is None or hx<best["hash"]: best={"unit":unit,"hash":hx}
    return {"summary":{"engine":"demo_hash","best":best,"rounds":rounds}}
def _event_candidate(c,lease,engine="event_stochastic_v1"):
    import numpy as np
    from search.event_stochastic import (
        EVENT_NAMES,SHELLS,QTAB,decrypt_score_event,key_arrays
    )
    from search.cpu_numba import encode,decode
    if not isinstance(c,dict): raise ValueError("candidate_not_object")
    unit=int(c["unit"]); start=int(lease["start_unit"]); end=int(lease["end_unit"])
    if unit<start or unit>=end: raise ValueError("candidate_unit_outside_lease")
    cfg=lease["config"]; portable=engine=="portable_event_v1"
    count=int(cfg.get("count_per_unit",4096 if portable else 32768))
    base=int(cfg.get("base_attempt",71000000000 if portable else 310000000)); attempt=int(c["attempt"])
    lo=base+unit*count
    if attempt<lo or attempt>=lo+count: raise ValueError("candidate_attempt_outside_unit")
    plain=str(c["plaintext"])
    if not _letters(plain,72):
        raise ValueError("invalid_plaintext")
    key=c["key"]; _validate_key(key)
    try:si,rings,pos,plug=key_arrays(key)
    except (KeyError,ValueError,TypeError,IndexError) as exc:raise ValueError("invalid_shell") from exc
    m=c.get("metrics",{})
    if not isinstance(m,dict):raise ValueError("invalid_metrics")
    ev=m.get("event",{})
    if not isinstance(ev,dict):raise ValueError("invalid_event")
    reverse={v:k for k,v in EVENT_NAMES.items()}
    kind=reverse.get(ev.get("kind"))
    if kind is None: raise ValueError("invalid_event_kind")
    if kind not in cfg.get("event_kinds",[1,2,3,4,5,6] if portable else [1,2,3,4,5]):raise ValueError("event_outside_campaign")
    pairs=len(key.get("plugboard",[]))
    if not int(cfg.get("min_pairs",0)) <= pairs <= int(cfg.get("max_pairs",13)):
        raise ValueError("plugboard_outside_campaign")
    at=int(ev.get("at",-1))
    if at<0 or at>=72: raise ValueError("invalid_event_at")
    param=int(ev.get("distance",1))
    if kind==3 and not 1<=param<=4:raise ValueError("invalid_rewind_distance")
    rpos=pos.copy()
    if kind==6:
        rp=str(ev.get("restart_positions",""))
        if not _letters(rp,4): raise ValueError("invalid_restart_positions")
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
def validate_result(engine,result,lease,*,allow_experimental=False):
    if not isinstance(result,dict): raise ValueError("result_not_object")
    if engine=="bounded_crib_v1" and allow_experimental:
        # Only isolated callers opt in. Production HTTP callers leave this
        # disabled; do not perform an experimental search in their request path.
        from search.research_validation import verify
        if type(lease.get('start_unit')) is not int or type(lease.get('end_unit')) is not int or lease['end_unit']!=lease['start_unit']+1:
            raise ValueError('experimental_lease_must_have_one_job')
        if set(result)!={'receipt'}:raise ValueError('invalid_experimental_result')
        job=lease['config']['research_job']
        verify(job,result['receipt'])
        # Preserve unknown-budget status; a matching receipt is not an
        # exhaustive negative and this function itself never issues credit.
        clean={'receipt':result['receipt']}
        return clean,fingerprint(clean)
    if engine=="demo_hash":
        expected=_demo_expected(lease)
        if result.get("summary")!=expected["summary"]:
            raise ValueError("demo_result_mismatch")
        clean=expected
        return clean,fingerprint(clean)
    if engine not in {"event_stochastic_v1","portable_event_v1"}:
        raise ValueError("unsupported_engine")
    summary=result.get("summary",{})
    if not isinstance(summary,dict):raise ValueError("invalid_summary")
    if summary.get("engine")!=engine:
        raise ValueError("engine_summary_mismatch")
    expected_units=int(lease["end_unit"])-int(lease["start_unit"])
    if int(summary.get("units",-1))!=expected_units:
        raise ValueError("unit_count_mismatch")
    candidates=result.get("candidates",[])
    if not isinstance(candidates,list) or len(candidates)>32:
        raise ValueError("candidate_count_invalid")
    topk=int(lease["config"].get("topk",8 if engine=="portable_event_v1" else 6))
    expected_count=min(max(topk,12),topk*expected_units)
    if len(candidates)!=expected_count:
        raise ValueError("candidate_count_mismatch")
    clean_candidates=[_event_candidate(c,lease,engine) for c in candidates]
    clean_candidates.sort(key=lambda x:(-x["score"],x["attempt"]))
    clean={"summary":{"engine":engine,"units":expected_units},
           "candidates":clean_candidates}
    return clean,fingerprint(clean)
