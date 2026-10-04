"""Compare complete ordered CSP receipts, including cutoff nodes, against Python."""
import argparse, pathlib, random, subprocess, sys, tempfile
root=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'solver/runtime/src'))
from search.c3_models import Key, stream, solve_board
p=argparse.ArgumentParser();p.add_argument('--jdk',required=True);a=p.parse_args()
jdk=pathlib.Path(a.jdk)/'bin';rng=random.Random(94126)
cases=[];expected=[]
for n in range(180):
    key=Key('Bthin' if n%2 else 'Cthin','Beta' if n%3 else 'Gamma',tuple(rng.sample(['I','II','III','IV','V','VI','VII','VIII'],3)),''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ',k=4)),''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ',k=4)))
    rows=stream(key,8,include_plugs=False)
    edges=[(i,rng.randrange(26),rng.randrange(26)) for i in range(n%9)]
    pairs=n%14;nodes=[1,2,25,300][n%4];solutions=[1,3,10][n%3]
    result=solve_board(rows,edges,max_pairs=pairs,node_limit=nodes,solution_limit=solutions)
    expected.append(' '.join(map(str,[result['status'],result['nodes'],*[x for b in result['partial_boards'] for x in b]])))
    cases.append(' '.join(map(str,[len(rows),len(edges),pairs,nodes,solutions,*[x for row in rows for x in row],*[x for e in edges for x in e]])))
with tempfile.TemporaryDirectory() as tmp:
    subprocess.run([str(jdk/'javac.exe'),'-d',tmp,str(root/'android/core/src/main/java/org/enigmagrid/core/BoardSolver.java'),str(root/'android/core/BoardCli.java')],check=True)
    actual=subprocess.run([str(jdk/'java.exe'),'-cp',tmp,'BoardCli'],input='\n'.join(cases),text=True,capture_output=True,check=True).stdout.splitlines()
    assert len(actual)==len(expected),(len(actual),len(expected))
    for i,(got,want) in enumerate(zip(actual,expected)):
        assert got==want,(i,got,want)
print(f'PASS: {len(cases)} ordered CSP receipts match Python (status, nodes, partial boards)')
