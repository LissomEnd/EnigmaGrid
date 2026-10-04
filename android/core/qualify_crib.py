"""Full clean work receipts against Python, including positive and capped cases."""
import argparse, pathlib, random, subprocess, sys, tempfile, json
from dataclasses import replace
root=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'solver/runtime/src'))
from search.crib_pilot import core_at, DOMAIN
from search.c3_models import crypt
from search.bounded_crib import search
p=argparse.ArgumentParser();p.add_argument('--jdk',required=True);p.add_argument('--workers',type=int,default=1);p.add_argument('--write-fixtures',action='store_true');a=p.parse_args()
jdk=pathlib.Path(a.jdk)/'bin';rng=random.Random(39264)
lines=[];expected=[]
for i in range(60):
    index=[0,DOMAIN-1,rng.randrange(DOMAIN)][i%3]
    indices=[index] if i%2 else [index,(index+1)%DOMAIN]
    pairs=i%4
    key=replace(core_at(index),plugboard=tuple(['AZ','BY','CX'][:pairs]))
    plain='WETTERBERICHTFUERDIESTATION'
    cipher=crypt(plain,key)
    offset=i%5;crib=plain[offset:offset+([1,4,12,18][i%4])]
    if i%7==0:crib=cipher[offset:offset+len(crib)]
    nodes=[1,50,500][i%3];boards=[1,8][i%2];completions=[1,8][i%2];candidates=[1,16][i%2]
    result=search(cipher,crib,offset,[core_at(x) for x in indices],pairs=pairs,node_limit=nodes,board_limit=boards,completion_limit=completions,candidate_limit=candidates)
    expected.append(result)
    lines.append(' '.join(map(str,[cipher,crib,offset,pairs,nodes,boards,completions,candidates,len(indices),*indices])))
with tempfile.TemporaryDirectory() as tmp:
    sources=list((root/'android/core/src/main/java/org/enigmagrid/core').glob('*.java'))
    subprocess.run([str(jdk/'javac.exe'),'-d',tmp,*map(str,sources),str(root/'android/core/CribCli.java')],check=True)
    result=subprocess.run([str(jdk/'java.exe'),'-cp',tmp,'CribCli',str(a.workers)],input='\n'.join(lines),text=True,capture_output=True,check=True)
    actual=result.stdout.splitlines()
    assert len(actual)==len(expected),(len(actual),len(expected))
    for i,(raw,want) in enumerate(zip(actual,expected)):
        got=json.loads(raw)
        assert got==json.loads(json.dumps(want)),(i,got,want)
        assert raw==json.dumps(want,sort_keys=True,separators=(',',':')),(i,'Canonical mismatch')
print(f'PASS: {len(lines)} complete receipts and canonical bytes match Python')
print('Statuses:',sorted({r['status'] for r in expected}))
if a.write_fixtures:
    from hashlib import sha256
    fixtures=[{'input':line,'receipt_sha256':sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest()} for line,r in zip(lines,expected)]
    path=root/'android/app/src/main/assets/crib-fixtures.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(fixtures,indent=2)+'\n',encoding='utf-8')
