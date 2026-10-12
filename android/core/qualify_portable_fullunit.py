"""Offline Java/Python exact portable unit parity; never accesses production state."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]

JAVA = r'''
import java.io.*;
import java.util.*;
import org.enigmagrid.core.*;
public class PortableFullUnitCli {
 public static void main(String[] args) throws Exception {
  Scanner in=new Scanner(System.in);
  int[] cipher=PortableEventScore.ciphertext(in.nextLine());
  long seed=in.nextLong();int min=in.nextInt(),max=in.nextInt();
  List<PortableSearchJob.SeedState> states=new ArrayList<>();
  for(int i=0;i<16;i++)states.add(new PortableSearchJob.SeedState(in.next(),in.next()));
  int[] table=new int[PortableEventScore.QUADGRAM_ITEMS];
  try(DataInputStream data=new DataInputStream(new FileInputStream(args[0]))){
   for(int i=0;i<table.length;i++)table[i]=data.readInt();
  }
  long selfStarted=System.nanoTime();PortableSelfTest.verify(cipher,table);
  System.err.println("selftest_ms="+(System.nanoTime()-selfStarted)/1e6);
  for(int workers:new int[]{1,2,4}) {
  for(PortableSearchJob.Hit h:PortableSearchJob.run(cipher,table,seed,4096,512,8,min,max,
       new int[]{1,2,3,4,5,6},states,()->false,workers)){
   System.out.print(h.attempt+"|"+h.cost+"|");
   for(int i=0;i<h.key.length;i++)System.out.print((i==0?"":",")+h.key[i]);
   System.out.println();
  }
  System.out.println("END");
  }
  java.util.concurrent.atomic.AtomicInteger checks=new java.util.concurrent.atomic.AtomicInteger();
  try {PortableSearchJob.run(cipher,table,seed,4096,512,8,min,max,new int[]{1,2,3,4,5,6},states,
        ()->checks.incrementAndGet()>20,4);throw new AssertionError("Cancellation ignored");}
  catch(java.util.concurrent.CancellationException expected){}
 }
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--jdk', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    assets = ROOT/'android/app/src/main/assets'
    fixture = json.loads((ROOT/'android/app/src/lab/assets/portable_fullunit_v1.json').read_text())
    scope = json.loads((assets/'portable_c3_scope_v1.json').read_text())
    table = assets/'portable_qint_v1.bin'
    assert hashlib.sha256(table.read_bytes()).hexdigest() == scope['quadgram_sha256']
    cfg = fixture['config']
    seed = fixture['seed']
    payload = scope['ciphertext']+'\n'+f"{seed} {cfg['min_pairs']} {cfg['max_pairs']}\n"
    payload += '\n'.join(f"{s['state']} {s['inc']}" for s in fixture['pcg_states'])+'\n'
    names = ['EnigmaM4', 'PortableEventScore', 'PortablePcg64', 'PortableKeySampler', 'PortableSearchJob', 'PortableSearchPrefix', 'PortableSelfTest']
    core = ROOT/'android/core/src/main/java/org/enigmagrid/core'
    sources = {n:(core/(n+'.java')).read_bytes() for n in names}
    began = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='enigmagrid-portable-') as tmp:
        cli = Path(tmp)/'PortableFullUnitCli.java'
        cli.write_text(JAVA)
        for n,data in sources.items(): (Path(tmp)/(n+'.java')).write_bytes(data)
        subprocess.run([str(args.jdk/'bin/javac.exe'), '-d', tmp, *[str(Path(tmp)/(n+'.java')) for n in names], str(cli)], check=True)
        run = subprocess.run([str(args.jdk/'bin/java.exe'), '-Xmx256m', '-cp', tmp, 'PortableFullUnitCli', str(table)],
                             input=payload, text=True, capture_output=True, check=True, timeout=900)
    java_seconds = time.monotonic()-began
    runs=run.stdout.strip().split('END')
    assert len(runs)==4 and not runs[-1].strip()
    assert runs[0].strip()==runs[1].strip()==runs[2].strip(), 'Parallel receipt ordering or keys differ'
    actual = []
    for line in runs[0].strip().splitlines():
        attempt, cost, key = line.split('|')
        actual.append(dict(attempt=int(attempt), cost=int(cost), key=list(map(int,key.split(',')))))
    sys.path[:0] = [str(ROOT/'server'), str(ROOT/'solver/runtime/src')]
    import search.portable_search as portable
    from validator import validate_result
    began = time.monotonic()
    exact_keys = {}
    original_candidate = portable._candidate
    def capture(inp,obj,q,bal,si,rings,pos,plug,kind,at,param,rpos,assumptions,attempt):
        exact_keys[int(attempt)] = list(map(int,[si,*rings,*pos,*plug,*rpos,kind,at,param]))
        return original_candidate(inp,obj,q,bal,si,rings,pos,plug,kind,at,param,rpos,assumptions,attempt)
    portable._candidate = capture
    expected = portable.search(scope['ciphertext'], seed, count=4096, iterations=512, topk=8,
                      min_pairs=cfg['min_pairs'], max_pairs=cfg['max_pairs'], event_kinds=tuple(range(1,7)),
                      backend='cpu', cohort_blocks=1)
    portable._candidate = original_candidate
    expected_keys = [dict(attempt=x['attempt'], cost=x['metrics']['search_cost'], key=exact_keys[x['attempt']]) for x in expected]
    assert actual == expected_keys, 'Full Java key/cost/attempt differs from canonical Python'
    historical = [dict(attempt=x['attempt'],cost=x['cost']) for x in actual]
    assert historical == fixture['expected_top8'], 'Historical winners differ'
    for x in actual: x['unit'] = fixture['unit']
    for x in expected: x['unit'] = fixture['unit']
    lease = dict(engine='portable_event_v1', start_unit=fixture['unit'], end_unit=fixture['unit']+1, config=cfg)
    summary = dict(engine='portable_event_v1',units=1)
    clean, fingerprint = validate_result('portable_event_v1',dict(summary=summary,portable_key_rows=actual),lease)
    reference, reference_fingerprint = validate_result('portable_event_v1',dict(summary=summary,candidates=expected),lease)
    assert clean == reference and fingerprint == reference_fingerprint, 'Canonical receipts differ'
    assert fingerprint == fixture['credited_source_fingerprint'], 'Historical receipt differs'
    report = dict(status='PASS',unit=fixture['unit'],segment=fixture['segment_id'],
                  java_seconds=java_seconds,python_seconds=time.monotonic()-began,fingerprint=fingerprint,
                  compared='all eight exact keys, integer costs, attempts and full canonical receipt',
                  lanes=[1,2,4],cancellation='PASS',startup_selftest=run.stderr.strip(),
                  source_sha256={n:hashlib.sha256(data).hexdigest() for n,data in sources.items()})
    if args.report: args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__': main()
