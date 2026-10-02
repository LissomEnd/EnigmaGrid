// EnigmaGrid portable fixed-point scorer, OpenCL 1.2. No downloaded kernels.
inline int mod26(int x) { return (x + 52) % 26; }
inline int rotor(int x, int r, int p, int ring, __global const uchar *table) {
    return mod26((int)table[r*26+mod26(x+p-ring)]-p+ring);
}
inline void enigma_step(int *p, int m1, int m2, __global const uchar *notches) {
    int mn=notches[m1*26+p[2]], rn=notches[m2*26+p[3]];
    if(mn) p[1]=(p[1]+1)%26;
    if(mn || rn) p[2]=(p[2]+1)%26;
    p[3]=(p[3]+1)%26;
}
inline int avg(int sum, int n) {
    // All quadgram costs are nonnegative: identical integer division everywhere.
    return n>0 ? sum/n : 20000;
}
__kernel void score_keys(__global const uchar *input,
    __global const short *shells, __global const uchar *fw,
    __global const uchar *rv, __global const uchar *notches,
    __global const int *qtab, __global const int *keys,
    __global int *scores) {
    int t=get_global_id(0);
    __global const int *k=keys+t*42;
    int si=k[0], kind=k[39], at=k[40], param=k[41];
    int p[4], out[72];
    for(int j=0;j<4;j++) p[j]=k[5+j];
    int refl=shells[si*5], greek=shells[si*5+1], m0=shells[si*5+2];
    int m1=shells[si*5+3], m2=shells[si*5+4];
    for(int i=0;i<72;i++) {
        int steps=1;
        if(i==at) {
            if(kind==1) steps=0;
            else if(kind==2) steps=2;
            else if(kind==3) {
                for(int j=0;j<param;j++) enigma_step(p,m1,m2,notches);
                p[3]=mod26(p[3]-param);
            } else if(kind==4) p[2]=(p[2]+1)%26;
            else if(kind==5) p[2]=mod26(p[2]-1);
            else if(kind==6) for(int j=0;j<4;j++) p[j]=k[35+j];
        }
        for(int j=0;j<steps;j++) enigma_step(p,m1,m2,notches);
        int x=k[9+input[i]];
        x=rotor(x,m2,p[3],k[4],fw); x=rotor(x,m1,p[2],k[3],fw);
        x=rotor(x,m0,p[1],k[2],fw); x=rotor(x,greek,p[0],k[1],fw);
        x=fw[refl*26+x];
        x=rotor(x,greek,p[0],k[1],rv); x=rotor(x,m0,p[1],k[2],rv);
        x=rotor(x,m1,p[2],k[3],rv); x=rotor(x,m2,p[3],k[4],rv);
        out[i]=k[9+x];
    }
    int full=0,left=0,right=0;
    for(int i=0;i<69;i++) {
        int z=((out[i]*26+out[i+1])*26+out[i+2])*26+out[i+3];
        int q=qtab[z]; full+=q;
        if(i+3<at) left+=q;
        if(i>=at) right+=q;
    }
    scores[t]=72*avg(full,69)+28*max(avg(left,at-3),avg(right,69-at));
}

