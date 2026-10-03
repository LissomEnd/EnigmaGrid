"""Offline diagnostic, not a solution detector or a production score change.

Known naval plaintext is compared with deterministic letter shuffles. Optional
candidate exports must contain only public research text, not a live database.
Optimized candidates and random shuffles are different null distributions.
"""
import argparse,hashlib,json,math,random
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
QFILE=ROOT/'solver/runtime/data/language/german_quadgrams.txt'

def run(candidate_texts=()):
    counts={}
    for line in QFILE.read_text().splitlines():
        parts=line.split()
        if len(parts)==2 and len(parts[0])==4:counts[parts[0]]=int(parts[1])
    total=sum(counts.values());floor=math.log10(.01/total)
    table={k:math.log10(v/total) for k,v in counts.items()}
    def score(text):
        if len(text)<4 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in text):
            raise ValueError('At least four uppercase letters required')
        return sum(table.get(text[i:i+4],floor) for i in range(len(text)-3))/(len(text)-3)
    candidates=[score(t) for t in candidate_texts]
    fixtures=json.loads((ROOT/'tests/fixtures/historical_m4.json').read_text())
    fixtures+=json.loads((ROOT/'tests/fixtures/historical_m4_independent.json').read_text())
    rng=random.Random(20261003);rows=[]
    for fixture in fixtures:
        text=fixture['plaintext'][:72];truth=score(text);shuffles=[]
        for _ in range(1000):
            chars=list(text);rng.shuffle(chars);shuffles.append(score(''.join(chars)))
        rows.append(dict(id=fixture['id'],historical_score=truth,
            shuffles=1000,shuffles_scoring_at_least_truth=sum(x>=truth for x in shuffles),
            optimized_candidates_scoring_at_least_truth=sum(x>=truth for x in candidates)))
    return dict(table_sha256=hashlib.sha256(QFILE.read_bytes()).hexdigest(),
        controls=rows,candidate_count=len(candidates),
        caveats=['Three controls span two daily keys; they are not a representative naval corpus.',
            'Shuffle counts are not p-values for search-optimized candidates.',
            'A high score or exact replay does not establish a historical solution.',
            'Do not train a replacement scorer on these held-out controls.'])

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--candidate-texts');ap.add_argument('--output',required=True)
    args=ap.parse_args();texts=json.loads(Path(args.candidate_texts).read_text()) if args.candidate_texts else []
    result=run(texts);Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
