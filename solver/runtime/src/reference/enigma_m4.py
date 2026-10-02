from string import ascii_uppercase as A

W={
"I":"EKMFLGDQVZNTOWYHXUSPAIBRCJ","II":"AJDKSIRUXBLHWTMCQGZNPYFVOE",
"III":"BDFHJLCPRTXVZNYEIWGAKMUSQO","IV":"ESOVPZJAYQUIRHXLNFTGKDCMWB",
"V":"VZBRGITYUPSDNHLXAWMJQOFECK","VI":"JPGVOUMFYQBENHZRDKASXLICTW",
"VII":"NZJHGRCXMYSWBOUFAIVLPEKQDT","VIII":"FKQHTLXOCBJSPDZRAMEWNIUYGV",
"Beta":"LEYJVCNIXWPBQMDRTAKZGFUHOS","Gamma":"FSOKANUERHMBTIYCWLQPZXVGJD",
"Bthin":"ENKQAUYWJICOPBLMDXZVFTHRGS","Cthin":"RDOBJNTKVEHMLFCWZAXGYIPSUQ"}
N={"I":"Q","II":"E","III":"V","IV":"J","V":"Z","VI":"ZM","VII":"ZM","VIII":"ZM"}
F={k:[A.index(c) for c in v] for k,v in W.items()}
R={}
for k,v in F.items():
    z=[0]*26
    for i,x in enumerate(v): z[x]=i
    R[k]=z

def _f(x,n,p,r): return (F[n][(x+p-r)%26]-p+r)%26
def _b(x,n,p,r): return (R[n][(x+p-r)%26]-p+r)%26
def _notch(n,p): return any(p==A.index(c) for c in N[n])

def crypt(text, reflector, greek, moving, positions, rings, plugboard):
    p=[A.index(c) for c in positions]; r=[A.index(c) for c in rings]
    plug=list(range(26))
    for q in plugboard:
        a,b=A.index(q[0]),A.index(q[1]); plug[a]=b; plug[b]=a
    out=[]
    for ch in text:
        mn=_notch(moving[1],p[2]); rn=_notch(moving[2],p[3])
        if mn: p[1]=(p[1]+1)%26
        if mn or rn: p[2]=(p[2]+1)%26
        p[3]=(p[3]+1)%26
        x=plug[A.index(ch)]
        x=_f(x,moving[2],p[3],r[3])
        x=_f(x,moving[1],p[2],r[2])
        x=_f(x,moving[0],p[1],r[1])
        x=_f(x,greek,p[0],r[0])
        x=F[reflector][x]
        x=_b(x,greek,p[0],r[0])
        x=_b(x,moving[0],p[1],r[1])
        x=_b(x,moving[1],p[2],r[2])
        x=_b(x,moving[2],p[3],r[3])
        out.append(A[plug[x]])
    return "".join(out)
