import math
import numpy as np
from numba import njit, prange
from search.cpu_numba import NOTCH, FW, IDX, encode, decode, plug_array
from search.stochastic_c2 import (
    SHELLS, QTAB, _lcg, _r26, _random_plug, _mutate_plug, _rf, _rr,
    _letters, _pairs
)

EVENT_NAMES={1:"missed_step",2:"extra_step",3:"partial_rewind",
             4:"middle_shift_plus",5:"middle_shift_minus",6:"restart"}
DEFAULT_ATS=np.asarray(list(range(4,69,4)),dtype=np.uint8)
SHELL_MAP={tuple(int(x) for x in SHELLS[i]):i for i in range(len(SHELLS))}

@njit(cache=True, inline="always")
def _step(p,m1,m2):
    mn=NOTCH[m1,p[2]]!=0
    rn=NOTCH[m2,p[3]]!=0
    if mn: p[1]=(p[1]+1)%26
    if mn or rn: p[2]=(p[2]+1)%26
    p[3]=(p[3]+1)%26

@njit(cache=True, inline="always")
def _qavg(out,qtab,start,end):
    if end-start<4:return np.float32(-20.0)
    s=np.float32(0.0); n=0
    for i in range(start,end-3):
        z=((int(out[i])*26+int(out[i+1]))*26+int(out[i+2]))*26+int(out[i+3])
        s+=qtab[z]; n+=1
    return s/np.float32(max(1,n))

@njit(cache=True,nogil=True)
def decrypt_score_event(inp,shell,rings,pos,plug,qtab,event_kind,event_at,event_param,restart_pos):
    p=pos.copy()
    out=np.empty(inp.size,dtype=np.uint8)
    refl,greek,m0,m1,m2=shell
    for i in range(inp.size):
        steps=1
        if i==event_at:
            if event_kind==1:
                steps=0
            elif event_kind==2:
                steps=2
            elif event_kind==3:
                d=max(1,min(4,int(event_param)))
                for _ in range(d): _step(p,m1,m2)
                p[3]=(p[3]-d)%26
            elif event_kind==4:
                p[2]=(p[2]+1)%26
            elif event_kind==5:
                p[2]=(p[2]-1)%26
            elif event_kind==6:
                p=restart_pos.copy()
        for _ in range(steps): _step(p,m1,m2)
        x=plug[inp[i]]
        x=_rf(x,m2,p[3],rings[3]); x=_rf(x,m1,p[2],rings[2]); x=_rf(x,m0,p[1],rings[1])
        x=_rf(x,greek,p[0],rings[0]); x=FW[refl,x]; x=_rr(x,greek,p[0],rings[0])
        x=_rr(x,m0,p[1],rings[1]); x=_rr(x,m1,p[2],rings[2]); x=_rr(x,m2,p[3],rings[3])
        out[i]=plug[x]
    full=_qavg(out,qtab,0,out.size)
    left=_qavg(out,qtab,0,max(0,event_at))
    right=_qavg(out,qtab,min(out.size,event_at),out.size)
    balanced=min(left,right)
    obj=np.float32(0.72)*full+np.float32(0.28)*balanced
    return obj,full,balanced,out

@njit(parallel=True,cache=True)
def event_batch(inp,shells,qtab,event_kinds,event_ats,start_seed,count,iterations,min_pairs,max_pairs):
    objbest=np.empty(count,dtype=np.float32); qbest=np.empty(count,dtype=np.float32)
    bbest=np.empty(count,dtype=np.float32); shell_out=np.empty(count,dtype=np.int16)
    rings_out=np.empty((count,4),dtype=np.uint8); pos_out=np.empty((count,4),dtype=np.uint8)
    plug_out=np.empty((count,26),dtype=np.uint8); kind_out=np.empty(count,dtype=np.uint8)
    at_out=np.empty(count,dtype=np.uint8); param_out=np.empty(count,dtype=np.uint8)
    restart_out=np.empty((count,4),dtype=np.uint8)
    for t in prange(count):
        rng=np.uint64(start_seed+t+1)*np.uint64(0x9E3779B97F4A7C15)
        rng=_lcg(rng); si=int((rng>>np.uint64(32))%np.uint64(shells.shape[0]))
        rings=np.zeros(4,dtype=np.uint8)
        for j in range(1,4):
            rng=_lcg(rng); rings[j]=_r26(rng)
        pos=np.empty(4,dtype=np.uint8); rpos=np.empty(4,dtype=np.uint8)
        for j in range(4):
            rng=_lcg(rng); pos[j]=_r26(rng)
            rng=_lcg(rng); rpos[j]=_r26(rng)
        plug,rng=_random_plug(rng,min_pairs,max_pairs)
        rng=_lcg(rng); kind=int(event_kinds[int((rng>>np.uint64(32))%np.uint64(event_kinds.size))])
        rng=_lcg(rng); at=int(event_ats[int((rng>>np.uint64(32))%np.uint64(event_ats.size))])
        rng=_lcg(rng); param=1+int((rng>>np.uint64(32))%np.uint64(4))
        obj,q,bal,_=decrypt_score_event(inp,shells[si],rings,pos,plug,qtab,kind,at,param,rpos)
        bo=obj; bq=q; bb=bal; bsi=si; br=rings.copy(); bp=pos.copy(); bpl=plug.copy()
        bk=kind; ba=at; bpar=param; brp=rpos.copy(); temp=np.float32(0.38)
        for _ in range(iterations):
            rng=_lcg(rng); k=int((rng>>np.uint64(32))%np.uint64(100))
            nsi=si; nr=rings.copy(); np0=pos.copy(); npl=plug.copy()
            nk=kind; na=at; npar=param; nrp=rpos.copy()
            if k<58:
                npl,rng=_mutate_plug(plug,rng,max_pairs)
            elif k<70:
                rng=_lcg(rng); j=int((rng>>np.uint64(32))%np.uint64(4)); rng=_lcg(rng); np0[j]=_r26(rng)
            elif k<78:
                rng=_lcg(rng); j=1+int((rng>>np.uint64(32))%np.uint64(3)); rng=_lcg(rng); nr[j]=_r26(rng)
            elif k<82:
                rng=_lcg(rng); nsi=int((rng>>np.uint64(32))%np.uint64(shells.shape[0]))
            elif k<88:
                rng=_lcg(rng); nk=int(event_kinds[int((rng>>np.uint64(32))%np.uint64(event_kinds.size))])
            elif k<94:
                rng=_lcg(rng); na=int(event_ats[int((rng>>np.uint64(32))%np.uint64(event_ats.size))])
            elif k<97:
                rng=_lcg(rng); npar=1+int((rng>>np.uint64(32))%np.uint64(4))
            else:
                rng=_lcg(rng); j=int((rng>>np.uint64(32))%np.uint64(4)); rng=_lcg(rng); nrp[j]=_r26(rng)
            no,nq,nb,_=decrypt_score_event(inp,shells[nsi],nr,np0,npl,qtab,nk,na,npar,nrp)
            accept=no>=obj
            if not accept:
                rng=_lcg(rng)
                u=np.float32(((rng>>np.uint64(11)) & np.uint64((1<<24)-1))/float(1<<24))
                d=(no-obj)/max(temp,np.float32(0.025))
                if d>-20 and u<np.exp(d): accept=True
            if accept:
                si=nsi; rings=nr; pos=np0; plug=npl; kind=nk; at=na; param=npar; rpos=nrp
                obj=no; q=nq; bal=nb
                if obj>bo:
                    bo=obj; bq=q; bb=bal; bsi=si; br=rings.copy(); bp=pos.copy(); bpl=plug.copy()
                    bk=kind; ba=at; bpar=param; brp=rpos.copy()
            temp=np.float32(max(0.025,float(temp)*0.997))
        objbest[t]=bo; qbest[t]=bq; bbest[t]=bb; shell_out[t]=bsi
        rings_out[t]=br; pos_out[t]=bp; plug_out[t]=bpl; kind_out[t]=bk
        at_out[t]=ba; param_out[t]=bpar; restart_out[t]=brp
    return objbest,qbest,bbest,shell_out,rings_out,pos_out,plug_out,kind_out,at_out,param_out,restart_out
def _candidate(inp,obj,q,bal,si,rings,pos,plug,kind,at,param,rpos,assumptions,attempt):
    shell=SHELLS[int(si)]
    _,_,_,plain=decrypt_score_event(inp,shell,rings,pos,plug,QTAB,int(kind),int(at),int(param),rpos)
    rev={v:k for k,v in IDX.items()}
    event={"kind":EVENT_NAMES[int(kind)],"at":int(at)}
    if int(kind)==3:event["distance"]=int(param)
    if int(kind)==6:event["restart_positions"]=_letters(rpos)
    return {
      "attempt":int(attempt),"score":float(obj),"plaintext":decode(plain),
      "key":{"reflector":rev[int(shell[0])],"greek":rev[int(shell[1])],
             "moving_rotors":[rev[int(shell[2])],rev[int(shell[3])],rev[int(shell[4])]],
             "rings":_letters(rings),"positions":_letters(pos),"plugboard":_pairs(plug)},
      "metrics":{"objective":float(obj),"quadgram_full":float(q),"balanced_segments":float(bal),
                 "pairs":len(_pairs(plug)),"event":event},
      "assumptions":list(assumptions)+["c3_dynamic_event"]
    }

def run_event_stochastic(text,start_seed,count=1024,iterations=700,topk=6,
                         min_pairs=0,max_pairs=13,event_kinds=(1,2,3,4,5),event_ats=None,
                         assumptions=("c3_event_stochastic",)):
    inp=encode(text)
    kinds=np.asarray(event_kinds,dtype=np.uint8)
    ats=DEFAULT_ATS if event_ats is None else np.asarray(event_ats,dtype=np.uint8)
    out=event_batch(inp,SHELLS,QTAB,kinds,ats,np.uint64(start_seed),int(count),int(iterations),
                    int(min_pairs),int(max_pairs))
    obj,q,bal,si,rings,pos,plug,kind,at,param,rpos=out
    ids=np.argsort(obj)[-min(int(topk),int(count)):][::-1]
    return [_candidate(inp,obj[i],q[i],bal[i],si[i],rings[i],pos[i],plug[i],
                       kind[i],at[i],param[i],rpos[i],assumptions,start_seed+int(i)) for i in ids]

def key_arrays(k):
    target=(IDX[k["reflector"]],IDX[k["greek"]],IDX[k["moving_rotors"][0]],
            IDX[k["moving_rotors"][1]],IDX[k["moving_rotors"][2]])
    si=SHELL_MAP[tuple(int(x) for x in target)]
    rings=encode(k["rings"]); pos=encode(k["positions"]); plug=plug_array(k.get("plugboard",[]))
    return si,rings,pos,plug

def score_key_events(text,k,event_kinds=(1,2,3,4,5),event_ats=None,topk=4):
    inp=encode(text); si,rings,pos,plug=key_arrays(k)
    ats=list(range(4,69,4)) if event_ats is None else [int(x) for x in event_ats]
    rpos=pos.copy(); scored=[]
    for kind in event_kinds:
        params=(1,2,3,4) if int(kind)==3 else (1,)
        for at in ats:
            for param in params:
                obj,q,bal,plain=decrypt_score_event(inp,SHELLS[si],rings,pos,plug,QTAB,
                                                    int(kind),int(at),int(param),rpos)
                scored.append((float(obj),float(q),float(bal),int(kind),int(at),int(param),decode(plain)))
    scored.sort(reverse=True,key=lambda x:x[0])
    out=[]
    for obj,q,bal,kind,at,param,plain in scored[:topk]:
        event={"kind":EVENT_NAMES[kind],"at":at}
        if kind==3:event["distance"]=param
        out.append({"score":obj,"plaintext":plain,"key":k,
                    "metrics":{"objective":obj,"quadgram_full":q,"balanced_segments":bal,
                               "pairs":len(k.get("plugboard",[])),"event":event},
                    "assumptions":["c3_c2_frontier_reuse","dynamic_event"]})
    return out
