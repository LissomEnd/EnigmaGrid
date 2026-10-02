import numpy as np
from numba import njit
from search.cpu_numba import NOTCH, FW, IDX, encode, decode, plug_array
from search.stochastic_c2 import SHELLS, QTAB, _rf, _rr, _letters, _pairs
from search.event_stochastic import SHELL_MAP, _qavg

@njit(cache=True,inline="always")
def _step(p,m1,m2):
    mn=NOTCH[m1,p[2]]!=0
    rn=NOTCH[m2,p[3]]!=0
    if mn:p[1]=(p[1]+1)%26
    if mn or rn:p[2]=(p[2]+1)%26
    p[3]=(p[3]+1)%26

@njit(cache=True,nogil=True)
def decrypt_score_transition(inp,shell,rings,pos,plug_before,plug_after,qtab,event_at):
    p=pos.copy();out=np.empty(inp.size,dtype=np.uint8)
    refl,greek,m0,m1,m2=shell
    for i in range(inp.size):
        _step(p,m1,m2)
        plug=plug_before if i<event_at else plug_after
        x=plug[inp[i]]
        x=_rf(x,m2,p[3],rings[3]);x=_rf(x,m1,p[2],rings[2]);x=_rf(x,m0,p[1],rings[1])
        x=_rf(x,greek,p[0],rings[0]);x=FW[refl,x];x=_rr(x,greek,p[0],rings[0])
        x=_rr(x,m0,p[1],rings[1]);x=_rr(x,m1,p[2],rings[2]);x=_rr(x,m2,p[3],rings[3])
        out[i]=plug[x]
    full=_qavg(out,qtab,0,out.size)
    left=_qavg(out,qtab,0,event_at);right=_qavg(out,qtab,event_at,out.size)
    bal=min(left,right);obj=np.float32(0.72)*full+np.float32(0.28)*bal
    return obj,full,bal,out

def _after_remove(p,a,b):
    q=p.copy();q[a]=a;q[b]=b;return q

def _after_add(p,a,b):
    q=p.copy();q[a]=b;q[b]=a;return q

def run_transition_refine(text,key,topk=8,event_ats=None,max_variants=20000):
    inp=encode(text)
    target=(IDX[key["reflector"]],IDX[key["greek"]],IDX[key["moving_rotors"][0]],
            IDX[key["moving_rotors"][1]],IDX[key["moving_rotors"][2]])
    si=SHELL_MAP[tuple(int(x) for x in target)];shell=SHELLS[si]
    rings=encode(key["rings"]);pos=encode(key["positions"]);before=plug_array(key.get("plugboard",[]))
    ats=list(range(4,69,4)) if event_ats is None else [int(x) for x in event_ats]
    pairs=[(i,int(before[i])) for i in range(26) if i<int(before[i])]
    free=[i for i in range(26) if int(before[i])==i]
    variants=[]
    for at in ats:
        for a,b in pairs:
            variants.append((at,"remove",a,b,-1,-1,_after_remove(before,a,b)))
        if len(pairs)<13:
            for x in range(len(free)):
                for y in range(x+1,len(free)):
                    a,b=free[x],free[y]
                    variants.append((at,"add",-1,-1,a,b,_after_add(before,a,b)))
        for a,b in pairs:
            base=_after_remove(before,a,b)
            for f in free:
                variants.append((at,"move_a",a,b,a,f,_after_add(base,a,f)))
                variants.append((at,"move_b",a,b,b,f,_after_add(base,b,f)))
    if len(variants)>max_variants:
        stride=max(1,len(variants)//max_variants)
        variants=variants[::stride][:max_variants]
    scored=[]
    for at,kind,ra,rb,aa,ab,after in variants:
        obj,q,bal,plain=decrypt_score_transition(inp,shell,rings,pos,before,after,QTAB,int(at))
        scored.append((float(obj),float(q),float(bal),at,kind,ra,rb,aa,ab,decode(plain),after))
    scored.sort(reverse=True,key=lambda x:x[0])
    out=[]
    for obj,q,bal,at,kind,ra,rb,aa,ab,plain,after in scored[:topk]:
        change={"kind":kind,"at":int(at)}
        if ra>=0:change["removed"]=chr(65+ra)+chr(65+rb)
        if aa>=0:change["added"]=chr(65+aa)+chr(65+ab)
        out.append({"score":obj,"plaintext":plain,
                    "key":{**key,"plugboard_before":key.get("plugboard",[]),
                           "plugboard_after":_pairs(after)},
                    "metrics":{"objective":obj,"quadgram_full":q,"balanced_segments":bal,
                               "transition":change,"variant_count":len(variants)},
                    "assumptions":["c3_single_plugboard_transition"]})
    return out
