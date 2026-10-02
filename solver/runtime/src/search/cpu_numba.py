import numpy as np
from numba import njit, prange
from string import ascii_uppercase as A
from reference.enigma_m4 import W,N

ORDER=["I","II","III","IV","V","VI","VII","VIII","Beta","Gamma","Bthin","Cthin"]
IDX={n:i for i,n in enumerate(ORDER)}
FW=np.empty((len(ORDER),26),dtype=np.int16)
RV=np.empty_like(FW)
NOTCH=np.zeros((8,26),dtype=np.uint8)
for n,i in IDX.items():
    w=np.array([A.index(c) for c in W[n]],dtype=np.int16); FW[i]=w
    inv=np.empty(26,dtype=np.int16)
    for j,x in enumerate(w): inv[x]=j
    RV[i]=inv
for n,s in N.items():
    for c in s: NOTCH[IDX[n],A.index(c)]=1

@njit(cache=True,inline="always")
def rf(x,ridx,pos,ring,fw):
    return (fw[ridx,(x+pos-ring)%26]-pos+ring)%26
@njit(cache=True,inline="always")
def rr(x,ridx,pos,ring,rv):
    return (rv[ridx,(x+pos-ring)%26]-pos+ring)%26

@njit(cache=True)
def crypt_numeric(inp,reflector,greek,m0,m1,m2,pos,ring,plug,fw,rv,notch):
    p=pos.copy(); out=np.empty(inp.size,dtype=np.uint8)
    for i in range(inp.size):
        mn=notch[m1,p[2]]!=0; rn=notch[m2,p[3]]!=0
        if mn: p[1]=(p[1]+1)%26
        if mn or rn: p[2]=(p[2]+1)%26
        p[3]=(p[3]+1)%26
        x=plug[inp[i]]
        x=rf(x,m2,p[3],ring[3],fw); x=rf(x,m1,p[2],ring[2],fw); x=rf(x,m0,p[1],ring[1],fw)
        x=rf(x,greek,p[0],ring[0],fw); x=fw[reflector,x]; x=rr(x,greek,p[0],ring[0],rv)
        x=rr(x,m0,p[1],ring[1],rv); x=rr(x,m1,p[2],ring[2],rv); x=rr(x,m2,p[3],ring[3],rv)
        out[i]=plug[x]
    return out

def encode(s): return np.array([A.index(c) for c in s],dtype=np.uint8)
def decode(x): return "".join(A[int(i)] for i in x)
def plug_array(pairs):
    p=np.arange(26,dtype=np.uint8)
    for q in pairs:
        a,b=A.index(q[0]),A.index(q[1]); p[a]=b; p[b]=a
    return p

def decrypt(text,reflector,greek,moving,positions,rings,plugboard):
    return decode(crypt_numeric(encode(text),IDX[reflector],IDX[greek],IDX[moving[0]],IDX[moving[1]],IDX[moving[2]],
        encode(positions),encode(rings),plug_array(plugboard),FW,RV,NOTCH))

@njit(parallel=True,cache=True)
def match_score_positions(inp,expected,reflector,greek,m0,m1,m2,rings,plug,fw,rv,notch,start,end,scores):
    # Encodes four rotor start positions as a base-26 integer [Greek,left,middle,right].
    for k in prange(start,end):
        z=k
        pos=np.empty(4,dtype=np.uint8)
        for j in range(3,-1,-1):
            pos[j]=z%26; z//=26
        out=crypt_numeric(inp,reflector,greek,m0,m1,m2,pos,rings,plug,fw,rv,notch)
        s=0
        for i in range(expected.size):
            if out[i]==expected[i]: s+=1
        scores[k-start]=s

@njit(parallel=True,cache=True)
def ioc_scores_positions(inp,reflector,greek,m0,m1,m2,rings,fw,rv,notch,start,end,scores):
    for k in prange(start,end):
        z=k
        pos=np.empty(4,dtype=np.uint8)
        for j in range(3,-1,-1):
            pos[j]=z%26; z//=26
        hist=np.zeros(26,dtype=np.int16)
        for q in range(inp.size):
            mn=notch[m1,pos[2]]!=0; rn=notch[m2,pos[3]]!=0
            if mn: pos[1]=(pos[1]+1)%26
            if mn or rn: pos[2]=(pos[2]+1)%26
            pos[3]=(pos[3]+1)%26
            x=inp[q]
            x=rf(x,m2,pos[3],rings[3],fw); x=rf(x,m1,pos[2],rings[2],fw); x=rf(x,m0,pos[1],rings[1],fw)
            x=rf(x,greek,pos[0],rings[0],fw); x=fw[reflector,x]; x=rr(x,greek,pos[0],rings[0],rv)
            x=rr(x,m0,pos[1],rings[1],rv); x=rr(x,m1,pos[2],rings[2],rv); x=rr(x,m2,pos[3],rings[3],rv)
            hist[x]+=1
        num=0
        for i in range(26):
            num += hist[i]*(hist[i]-1)
        n=inp.size
        scores[k-start]=num/(n*(n-1)) if n>1 else 0.0

def scan_ioc(text,reflector,greek,moving,rings,start=0,end=26**4,top_k=16):
    inp=encode(text); rrings=encode(rings)
    scores=np.empty(end-start,dtype=np.float32)
    ioc_scores_positions(inp,IDX[reflector],IDX[greek],IDX[moving[0]],IDX[moving[1]],IDX[moving[2]],rrings,FW,RV,NOTCH,start,end,scores)
    k=min(int(top_k),len(scores))
    if k<=0:return []
    ix=np.argpartition(scores,-k)[-k:]
    ix=ix[np.argsort(scores[ix])[::-1]]
    return [{"position_index":int(start+i),"ioc":float(scores[i])} for i in ix]
