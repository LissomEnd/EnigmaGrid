"""Research-only no-event baseline. Separate semantics from portable_event_v1.

CPU scoring uses full-message integer quadgrams. No production worker routing.
"""
import numpy as np
from numba import njit, prange
from search.portable_search import initial_keys, mutate, BLOCK, QTAB_INT
from search.event_stochastic import SHELLS, QTAB, decrypt_score_event
from search.cpu_numba import encode, decode

@njit(cache=True, parallel=True)
def costs(inp, keys):
    result=np.empty(len(keys),dtype=np.int32)
    for i in prange(len(keys)):
        k=keys[i]
        _,_,_,out=decrypt_score_event(inp,SHELLS[k[0]],k[1:5],k[5:9],k[9:35],QTAB,0,36,1,k[35:39])
        total=0
        for j in range(len(out)-3):
            z=((int(out[j])*26+int(out[j+1]))*26+int(out[j+2]))*26+int(out[j+3])
            total+=QTAB_INT[z]
        result[i]=100*(total//(len(out)-3))
    return result

def search(text, seed, *, count=256, iterations=128, topk=8):
    if len(text)!=72 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in text): raise ValueError('72 letters required')
    if not 1<=count<=32768 or not 1<=iterations<=2000 or not 1<=topk<=32: raise ValueError('Invalid budget')
    inp=encode(text); winners=[]; kinds=np.array([0],dtype=np.int32)
    for off in range(0,count,BLOCK):
        size=min(BLOCK,count-off); rng=np.random.Generator(np.random.PCG64(seed+off))
        keys=initial_keys(rng,size,10,10,kinds)
        keys[:,1:3]=0  # Canonical Greek and left rings, random positions retained.
        values=costs(inp,keys); best=keys.copy(); best_values=values.copy()
        for it in range(iterations):
            nxt=mutate(rng,keys,10,10,kinds)
            # Conjugate by a letter transposition: rewires while preserving ten
            # cables. Removing two cables and adding one would freeze this arm.
            for row in range(size):
                if rng.integers(100)<58:
                    a,b=rng.choice(26,2,replace=False)
                    perm=np.arange(26);perm[a],perm[b]=b,a
                    nxt[row,9:35]=perm[keys[row,9:35][perm]]
            nxt[:,1:3]=0
            proposed=costs(inp,nxt)
            temp=max(2500,38000*(iterations-it)//iterations)
            accept=proposed<=values+rng.integers(0,temp+1,size)
            keys[accept]=nxt[accept];values[accept]=proposed[accept]
            improve=values<best_values
            best[improve]=keys[improve];best_values[improve]=values[improve]
        for i in np.lexsort((np.arange(size),best_values))[:topk]:
            k=best[i]
            _,_,_,out=decrypt_score_event(inp,SHELLS[k[0]],k[1:5],k[5:9],k[9:35],QTAB,0,36,1,k[35:39])
            winners.append(dict(cost=int(best_values[i]),attempt=seed+off+int(i),plaintext=decode(out)))
    return sorted(winners,key=lambda x:(x['cost'],x['attempt']))[:topk]
