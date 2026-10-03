"""C3 bounded research toolkit; no network, no target campaign, no background work.
Replay and fixed-core constraint tests are NOT an unknown-key Enigma break.
Event slots are zero-based and events act before the normal rotor step.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Iterable, Sequence
ABC='ABCDEFGHIJKLMNOPQRSTUVWXYZ'
WIRINGS={
'I':'EKMFLGDQVZNTOWYHXUSPAIBRCJ','II':'AJDKSIRUXBLHWTMCQGZNPYFVOE',
'III':'BDFHJLCPRTXVZNYEIWGAKMUSQO','IV':'ESOVPZJAYQUIRHXLNFTGKDCMWB',
'V':'VZBRGITYUPSDNHLXAWMJQOFECK','VI':'JPGVOUMFYQBENHZRDKASXLICTW',
'VII':'NZJHGRCXMYSWBOUFAIVLPEKQDT','VIII':'FKQHTLXOCBJSPDZRAMEWNIUYGV',
'Beta':'LEYJVCNIXWPBQMDRTAKZGFUHOS','Gamma':'FSOKANUERHMBTIYCWLQPZXVGJD',
'Bthin':'ENKQAUYWJICOPBLMDXZVFTHRGS','Cthin':'RDOBJNTKVEHMLFCWZAXGYIPSUQ',
'B':'YRUHQSLDPXNGOKMIEBFZCWVJAT','C':'FVPJIAOYEDRZXWGCTKUQSBNMHL'}
FW={k:tuple(ABC.index(c) for c in v) for k,v in WIRINGS.items()}
BW={k:tuple(v.index(i) for i in range(26)) for k,v in FW.items()}
NOTCH={'I':'Q','II':'E','III':'V','IV':'J','V':'Z','VI':'MZ','VII':'MZ','VIII':'MZ'}
def letters(v, length=None):
    if not isinstance(v,str) or any(c not in ABC for c in v):raise ValueError('Explicit uppercase A-Z only')
    if length is not None and len(v)!=length:raise ValueError('Invalid length')
    return tuple(ABC.index(c) for c in v)
def board(pairs):
    p=list(range(26));used=set()
    for pair in pairs:
        a,b=letters(pair,2)
        if a==b or a in used or b in used:raise ValueError('Overlapping/invalid plug pair')
        used.update((a,b));p[a]=b;p[b]=a
    return tuple(p)
def pair_strings(p):
    if len(p)!=26 or sorted(p)!=list(range(26)) or any(p[p[i]]!=i for i in range(26)):raise ValueError('Not an involution')
    return tuple(ABC[i]+ABC[p[i]] for i in range(26) if i<p[i])
@dataclass(frozen=True)
class Key:
    reflector:str
    greek:str
    moving_rotors:tuple[str,str,str]
    rings:str
    positions:str
    plugboard:tuple[str,...]=()
    def __post_init__(self):
        if self.reflector not in ('Bthin','Cthin') or self.greek not in ('Beta','Gamma'):raise ValueError('Standard M4 only')
        if len(self.moving_rotors)!=3 or len(set(self.moving_rotors))!=3 or any(x not in NOTCH for x in self.moving_rotors):raise ValueError('Invalid rotors')
        letters(self.rings,4);letters(self.positions,4);board(self.plugboard)
    @classmethod
    def from_dict(cls,d):return cls(d['reflector'],d['greek'],tuple(d['moving_rotors']),d['rings'],d['positions'],tuple(d.get('plugboard',())))
@dataclass(frozen=True)
class Event:
    at:int
    kind:str
    value:object
    def __post_init__(self):
        if self.at<0 or self.kind not in ('step_count','wheel_shift','restart','plug_remove','plug_add'):raise ValueError('Invalid event')
def step(p,moving):
    middle=ABC[p[2]] in NOTCH[moving[1]];fast=ABC[p[3]] in NOTCH[moving[2]]
    if middle:p[1]=(p[1]+1)%26
    if middle or fast:p[2]=(p[2]+1)%26
    p[3]=(p[3]+1)%26
def core(x,key,p,rings):
    names=(key.greek,)+key.moving_rotors
    for j in (3,2,1,0):
        off=p[j]-rings[j];x=(FW[names[j]][(x+off)%26]-off)%26
    x=FW[key.reflector][x]
    for j in (0,1,2,3):
        off=p[j]-rings[j];x=(BW[names[j]][(x+off)%26]-off)%26
    return x
def stream(key,length,events=(),include_plugs=True):
    if length<0:raise ValueError('Negative length')
    slots={}
    for e in events:
        if e.at>=length:raise ValueError('Event outside message')
        slots.setdefault(e.at,[]).append(e)
    p=list(letters(key.positions,4));rings=letters(key.rings,4);plugs=list(board(key.plugboard));rows=[]
    for i in range(length):
        nsteps=1
        if sum(e.kind=='step_count' for e in slots.get(i,[]))>1:raise ValueError('Duplicate step counts')
        for e in slots.get(i,[]):
            if e.kind=='step_count':
                nsteps=int(e.value)
                if nsteps not in (0,1,2):raise ValueError('Step count 0/1/2 only')
            elif e.kind=='wheel_shift':
                w,d=e.value
                if w not in (1,2,3) or d not in (-1,1):raise ValueError('Unsupported shift')
                p[w]=(p[w]+d)%26
            elif e.kind=='restart':p=list(letters(str(e.value),4))
            else:
                a,b=letters(str(e.value),2)
                if a==b:raise ValueError('Self pair')
                if e.kind=='plug_remove':
                    if plugs[a]!=b or plugs[b]!=a:raise ValueError('Absent cable')
                    plugs[a]=a;plugs[b]=b
                else:
                    if plugs[a]!=a or plugs[b]!=b:raise ValueError('Occupied endpoints')
                    plugs[a]=b;plugs[b]=a
        for _ in range(nsteps):step(p,key.moving_rotors)
        row=tuple(core(x,key,p,rings) for x in range(26))
        if include_plugs:row=tuple(plugs[row[plugs[x]]] for x in range(26))
        rows.append(row)
    return tuple(rows)
def crypt(text,key,events=()):
    nums=letters(text)
    return ''.join(ABC[row[x]] for row,x in zip(stream(key,len(nums),events),nums))
def normalize(key):
    p=list(letters(key.positions,4));r=list(letters(key.rings,4))
    for i in (0,1):p[i]=(p[i]-r[i])%26;r[i]=0
    return replace(key,positions=''.join(ABC[i] for i in p),rings=''.join(ABC[i] for i in r),plugboard=pair_strings(board(key.plugboard)))
def stream_signature(rows):return sha256(bytes(x for row in rows for x in row)).hexdigest()

def parse_transcript(raw,ellipsis_lengths=()):
    """Dots consume slots; ellipses require an explicit documented/hypothesized length."""
    out=[];lengths=iter(ellipsis_lengths);i=0
    while i<len(raw):
        if raw.startswith('[...]',i):
            try:n=next(lengths)
            except StopIteration as ex:raise ValueError('Unresolved gap length; cannot flatten') from ex
            if not isinstance(n,int) or n<1:raise ValueError('Invalid gap length')
            out.extend([None]*n);i+=5;continue
        ch=raw[i];i+=1
        if ch in ABC:out.append(ABC.index(ch))
        elif ch in '.?':out.append(None)
        elif ch.isspace():continue
        else:raise ValueError('Unsupported symbol '+repr(ch))
    if next(lengths,None) is not None:raise ValueError('Unused gap lengths')
    return tuple(out)
def observed_replay(observed,key,events=()):
    return tuple(None if c is None else row[c] for row,c in zip(stream(key,len(observed),events),observed))
def assign(p,a,b,max_pairs):
    if p[a] not in (-1,b) or p[b] not in (-1,a):return None
    q=list(p);q[a]=b;q[b]=a
    if sum(i<q[i] for i in range(26))>max_pairs:return None
    return tuple(q)
def solve_board(rows,edges,*,max_pairs=13,node_limit=100000,solution_limit=10):
    """All-components CSP at FIXED mechanical core. Edges=(slot,plain,cipher).
    Unknown mappings remain -1; limits produce UNKNOWN, not a negative certificate.
    Does not search rotor cores or decode unrestricted unknown plaintext.
    """
    if not 0<=max_pairs<=13 or node_limit<1 or solution_limit<1:raise ValueError('Invalid budget')
    for i,a,b in edges:
        if not 0<=i<len(rows) or not 0<=a<26 or not 0<=b<26:raise ValueError('Invalid edge')
    nodes=0;cutoff=False;answers=[];seen=set()
    def extend(p,used,a,b):
        # Internal states are involutions. Only a new non-self mapping adds a
        # cable; carry its count rather than scanning all 26 endpoints again.
        if p[a] not in (-1,b) or p[b] not in (-1,a):return None
        if p[a]==b:return p,used
        count=used+int(a!=b)
        if count>max_pairs:return None
        q=list(p);q[a]=b;q[b]=a
        return tuple(q),count
    def search(p,used):
        nonlocal nodes,cutoff
        if cutoff:return
        if nodes>=node_limit or len(answers)>=solution_limit:cutoff=True;return
        nodes+=1
        if p in seen:return
        seen.add(p)
        while True:
            changed=False
            for i,a,b in edges:
                if p[a]!=-1:
                    extended=extend(p,used,b,rows[i][p[a]])
                    if extended is None:return
                    q,used=extended
                    changed|=q!=p;p=q
                if p[b]!=-1:
                    extended=extend(p,used,a,rows[i][p[b]])
                    if extended is None:return
                    q,used=extended
                    changed|=q!=p;p=q
            if not changed:break
        unresolved=[e for e in edges if p[e[1]]==-1 or p[e[2]]==-1]
        if not unresolved:
            if p not in answers:answers.append(p)
            return
        options=[]
        for i,a,b in unresolved:
            values=[]
            for x in range(26):
                q=extend(p,used,a,x)
                if q is not None:q=extend(q[0],q[1],b,rows[i][x])
                if q is not None:values.append(q)
            if not values:return
            if not options or len(values)<len(options):options=values
        for q,count in options:search(q,count)
    search(tuple([-1]*26),0)
    return {'status':'unknown_budget' if cutoff else ('satisfiable' if answers else 'unsatisfiable'),'nodes':nodes,'partial_boards':[list(p) for p in answers],'full_key_search':False,'historical_solution':False}
def exclusion_allowed(prior,request):
    axes=('cipher_sha256','wiring_model','step_model','constraints_hash','scope_hash','pair_domain')
    flags=('engine_validated','complete','negative','receipt_verified','no_overflow','no_pruning')
    return all(prior.get(k) is True for k in flags) and all(k in prior and k in request and prior[k]==request[k] for k in axes)
def faulty_rewind_event(key,at,distance):
    """Counterfactual to M.Dv.32/1 para.60: type d, rewind only fast, overwrite.
    Not evidence that the event occurred on P1030680. Distance 1..4 is our budget.
    """
    if at<0 or distance not in (1,2,3,4):raise ValueError('Invalid bounded rewind')
    p=list(letters(key.positions,4))
    for _ in range(at):step(p,key.moving_rotors)
    before=tuple(p)
    for _ in range(distance):step(p,key.moving_rotors)
    p[3]=(p[3]-distance)%26
    return None if tuple(p)==before else Event(at,'restart',''.join(ABC[x] for x in p))
