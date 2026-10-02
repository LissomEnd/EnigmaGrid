import math, json
from pathlib import Path
from string import ascii_uppercase as A
import numpy as np
from numba import njit, prange
from search.cpu_numba import FW,RV,NOTCH,IDX,encode,decode,plug_array

ROOT=Path(__file__).resolve().parents[2]
QFILE=ROOT/"data/language/german_quadgrams.txt"

def load_quadgrams(path=QFILE):
    counts=[]
    total=0
    with open(path,"r",encoding="ascii",errors="ignore") as f:
        for line in f:
            p=line.split()
            if len(p)!=2 or len(p[0])!=4: continue
            n=int(p[1]); counts.append((p[0],n)); total+=n
    floor=math.log10(0.01/total)
    tab=np.full(26**4,floor,dtype=np.float32)
    for g,n in counts:
        z=0
        for c in g: z=z*26+(ord(c)-65)
        tab[z]=math.log10(n/total)
    return tab,np.float32(floor)

def all_shells():
    out=[]
    for refl in ("Bthin","Cthin"):
        for greek in ("Beta","Gamma"):
            for a in range(8):
                for b in range(8):
                    if b==a: continue
                    for c in range(8):
                        if c==a or c==b: continue
                        out.append((IDX[refl],IDX[greek],a,b,c))
    return np.asarray(out,dtype=np.int16)

SHELLS=all_shells()
QTAB,QFLOOR=load_quadgrams()

@njit(inline="always",cache=True)
def _lcg(x):
    return (x*6364136223846793005 + 1442695040888963407) & np.uint64(0xffffffffffffffff)

@njit(inline="always",cache=True)
def _r26(x):
    return int((x >> np.uint64(32)) % np.uint64(26))

@njit(inline="always",cache=True)
def _rf(x,ridx,pos,ring):
    return (FW[ridx,(x+pos-ring)%26]-pos+ring)%26

@njit(inline="always",cache=True)
def _rr(x,ridx,pos,ring):
    return (RV[ridx,(x+pos-ring)%26]-pos+ring)%26

@njit(cache=True,nogil=True)
def decrypt_score(inp,shell,rings,pos,plug,qtab):
    p=pos.copy()
    out=np.empty(inp.size,dtype=np.uint8)
    refl,greek,m0,m1,m2=shell
    for i in range(inp.size):
        mn=NOTCH[m1,p[2]]!=0
        rn=NOTCH[m2,p[3]]!=0
        if mn: p[1]=(p[1]+1)%26
        if mn or rn: p[2]=(p[2]+1)%26
        p[3]=(p[3]+1)%26
        x=plug[inp[i]]
        x=_rf(x,m2,p[3],rings[3]); x=_rf(x,m1,p[2],rings[2]); x=_rf(x,m0,p[1],rings[1])
        x=_rf(x,greek,p[0],rings[0]); x=FW[refl,x]; x=_rr(x,greek,p[0],rings[0])
        x=_rr(x,m0,p[1],rings[1]); x=_rr(x,m1,p[2],rings[2]); x=_rr(x,m2,p[3],rings[3])
        out[i]=plug[x]
    s=np.float32(0.0)
    if out.size>=4:
        for i in range(out.size-3):
            z=((int(out[i])*26+int(out[i+1]))*26+int(out[i+2]))*26+int(out[i+3])
            s+=qtab[z]
        s/=np.float32(out.size-3)
    return s,out

@njit(cache=True)
def _pair_count(p):
    n=0
    for i in range(26):
        if p[i]!=i and i<p[i]: n+=1
    return n

@njit(cache=True)
def _unpair(p,a):
    b=int(p[a])
    if b!=a:
        p[a]=a; p[b]=b

@njit(cache=True)
def _mutate_plug(p,rng,max_pairs):
    q=p.copy()
    rng=_lcg(rng); a=_r26(rng)
    rng=_lcg(rng); b=_r26(rng)
    if a==b: b=(b+1)%26
    rng=_lcg(rng); op=int((rng>>np.uint64(33))%np.uint64(3))
    if op==0:
        _unpair(q,a); _unpair(q,b)
        if _pair_count(q)<max_pairs:
            q[a]=b; q[b]=a
    elif op==1:
        if q[a]!=a: _unpair(q,a)
        else:
            _unpair(q,b)
            if _pair_count(q)<max_pairs: q[a]=b; q[b]=a
    else:
        pa=int(q[a]); pb=int(q[b])
        _unpair(q,a); _unpair(q,b)
        if a!=pb and _pair_count(q)<max_pairs:
            q[a]=pb; q[pb]=a
        if b!=pa and _pair_count(q)<max_pairs and q[b]==b and q[pa]==pa:
            q[b]=pa; q[pa]=b
    return q,rng

@njit(cache=True)
def _random_plug(rng,min_pairs,max_pairs):
    p=np.arange(26,dtype=np.uint8)
    letters=np.arange(26,dtype=np.uint8)
    for i in range(25,0,-1):
        rng=_lcg(rng); j=int((rng>>np.uint64(32))%np.uint64(i+1))
        t=letters[i]; letters[i]=letters[j]; letters[j]=t
    span=max_pairs-min_pairs+1
    if span<1: span=1
    rng=_lcg(rng); pairs=min_pairs+int((rng>>np.uint64(32))%np.uint64(span))
    if pairs>13: pairs=13
    if pairs<0: pairs=0
    for k in range(pairs):
        a=int(letters[2*k]); b=int(letters[2*k+1]); p[a]=b; p[b]=a
    return p,rng

@njit(parallel=True,cache=True)
def stochastic_batch(inp,shells,qtab,start_seed,count,iterations,min_pairs,max_pairs):
    scores=np.empty(count,dtype=np.float32)
    shell_out=np.empty(count,dtype=np.int16)
    rings_out=np.empty((count,4),dtype=np.uint8)
    pos_out=np.empty((count,4),dtype=np.uint8)
    plug_out=np.empty((count,26),dtype=np.uint8)
    for t in prange(count):
        rng=np.uint64(start_seed+t+1)*np.uint64(0x9E3779B97F4A7C15)
        rng=_lcg(rng); si=int((rng>>np.uint64(32))%np.uint64(shells.shape[0]))
        rings=np.zeros(4,dtype=np.uint8)
        for j in range(1,4):
            rng=_lcg(rng); rings[j]=_r26(rng)
        pos=np.empty(4,dtype=np.uint8)
        for j in range(4):
            rng=_lcg(rng); pos[j]=_r26(rng)
        plug,rng=_random_plug(rng,min_pairs,max_pairs)
        score,_=decrypt_score(inp,shells[si],rings,pos,plug,qtab)
        best=score; best_si=si; best_r=rings.copy(); best_p=pos.copy(); best_pl=plug.copy()
        temp=np.float32(0.35)
        for it in range(iterations):
            rng=_lcg(rng); kind=int((rng>>np.uint64(32))%np.uint64(100))
            nsi=si; nr=rings.copy(); np0=pos.copy(); npl=plug.copy()
            if kind<72:
                npl,rng=_mutate_plug(plug,rng,max_pairs)
            elif kind<88:
                rng=_lcg(rng); j=int((rng>>np.uint64(32))%np.uint64(4))
                rng=_lcg(rng); np0[j]=_r26(rng)
            elif kind<97:
                rng=_lcg(rng); j=1+int((rng>>np.uint64(32))%np.uint64(3))
                rng=_lcg(rng); nr[j]=_r26(rng)
            else:
                rng=_lcg(rng); nsi=int((rng>>np.uint64(32))%np.uint64(shells.shape[0]))
            ns,_=decrypt_score(inp,shells[nsi],nr,np0,npl,qtab)
            accept=ns>=score
            if not accept:
                rng=_lcg(rng)
                u=np.float32(((rng>>np.uint64(11)) & np.uint64((1<<24)-1))/float(1<<24))
                d=(ns-score)/max(temp,np.float32(0.02))
                if d>-20 and u<np.exp(d): accept=True
            if accept:
                si=nsi; rings=nr; pos=np0; plug=npl; score=ns
                if score>best:
                    best=score; best_si=si; best_r=rings.copy(); best_p=pos.copy(); best_pl=plug.copy()
            temp=np.float32(max(0.02,float(temp)*0.997))
        scores[t]=best; shell_out[t]=best_si; rings_out[t]=best_r; pos_out[t]=best_p; plug_out[t]=best_pl
    return scores,shell_out,rings_out,pos_out,plug_out

def _letters(a): return ''.join(A[int(x)] for x in a)
def _pairs(p):
    out=[]
    for i in range(26):
        j=int(p[i])
        if j!=i and i<j: out.append(A[i]+A[j])
    return out

def candidate_from_arrays(inp,score,si,rings,pos,plug,assumptions,attempt):
    shell=SHELLS[int(si)]
    s,out=decrypt_score(inp,shell,rings,pos,plug,QTAB)
    rev={v:k for k,v in IDX.items()}
    return {
      "attempt":int(attempt),"score":float(score),"plaintext":decode(out),
      "key":{"reflector":rev[int(shell[0])],"greek":rev[int(shell[1])],
             "moving_rotors":[rev[int(shell[2])],rev[int(shell[3])],rev[int(shell[4])]],
             "rings":_letters(rings),"positions":_letters(pos),"plugboard":_pairs(plug)},
      "metrics":{"quadgram_per_window":float(s),"pairs":len(_pairs(plug))},
      "assumptions":list(assumptions)
    }

def run_stochastic(text,start_seed,count=128,iterations=240,topk=12,assumptions=("agnostic_stochastic",),min_pairs=0,max_pairs=13):
    inp=encode(text)
    scores,si,rings,pos,plug=stochastic_batch(inp,SHELLS,QTAB,np.uint64(start_seed),int(count),int(iterations),int(min_pairs),int(max_pairs))
    idx=np.argsort(scores)[-min(topk,count):][::-1]
    return [candidate_from_arrays(inp,scores[i],si[i],rings[i],pos[i],plug[i],assumptions,int(start_seed+i)) for i in idx]

def run_fixed_daily_key_positions(text,v,topk=20):
    # Exhaustive 26^4 position control with fixed daily wheel/ring/plug settings.
    inp=encode(text)
    shell=np.array([IDX[v["reflector"]],IDX[v["greek"]],IDX[v["moving_rotors"][0]],IDX[v["moving_rotors"][1]],IDX[v["moving_rotors"][2]]],dtype=np.int16)
    rings=encode(v["rings"]); plug=plug_array(v["plugboard"])
    n=26**4
    scores=np.empty(n,dtype=np.float32)
    # Chunk in Python to avoid a huge temporary plaintext matrix.
    @njit(parallel=True,cache=True)
    def scan(inp,shell,rings,plug,qtab,scores):
        for k in prange(scores.size):
            p=np.empty(4,dtype=np.uint8)
            p[3]=k%26
            p[2]=(k//26)%26
            p[1]=(k//676)%26
            p[0]=(k//17576)%26
            s,_=decrypt_score(inp,shell,rings,p,plug,qtab); scores[k]=s
    scan(inp,shell,rings,plug,QTAB,scores)
    ids=np.argsort(scores)[-topk:][::-1]
    out=[]
    for k in ids:
        z=int(k); p=np.empty(4,dtype=np.uint8)
        for j in range(3,-1,-1): p[j]=z%26; z//=26
        s,plain=decrypt_score(inp,shell,rings,p,plug,QTAB)
        out.append({"attempt":int(k),"score":float(s),"plaintext":decode(plain),
                    "key":{**{x:v[x] for x in ("reflector","greek","moving_rotors","rings","plugboard")},"positions":_letters(p)},
                    "metrics":{"quadgram_per_window":float(s)},"assumptions":["potsdam_control_same_daily_key_as_P1030684"]})
    return out
