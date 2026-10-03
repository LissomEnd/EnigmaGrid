"""Compare exact clean crib constraints, without treating catalog entries as runs.

An external negative can exclude a proposed domain only after independently
checking its engine, key domain, completion and receipt. This tool never does so.
"""
import argparse,hashlib,json,re
from pathlib import Path

def classify(text,offset,prior,prior_offset):
    lo=max(offset,prior_offset);hi=min(offset+len(text),prior_offset+len(prior))
    if lo>=hi:return None
    if any(text[i-offset]!=prior[i-prior_offset] for i in range(lo,hi)):return None
    if offset==prior_offset and text==prior:return 'identical_constraints'
    if offset<=prior_offset and offset+len(text)>=prior_offset+len(prior):
        return 'proposal_implies_prior_constraints'
    if prior_offset<=offset and prior_offset+len(prior)>=offset+len(text):
        return 'prior_implies_proposal_constraints'
    return 'compatible_partial_overlap'

def audit(proposal,catalog):
    if proposal['ciphertext']!=catalog['ciphertext']:raise ValueError('Different ciphertext transcripts')
    rows=[]
    for hypothesis in proposal['hypotheses']:
        for offset in hypothesis['legal_clean_offsets']:
            matches=[]
            for prior in catalog['cribs']:
                for po in prior['offsets']:
                    kind=classify(hypothesis['text'],offset,prior['text'],po)
                    if kind and kind!='compatible_partial_overlap':
                        matches.append(dict(relation=kind,prior_text=prior['text'],prior_offset=po))
            rows.append(dict(text=hypothesis['text'],offset=offset,matches=matches,
                exclusion_allowed=False,execution_coverage='UNVERIFIED'))
    return dict(schema='crib_overlap_audit_v1',placements=rows,
        caveat='Catalog membership is not proof of execution or full-domain exclusion')

def attach_execution_log(result,raw):
    """Map reported rows, not proof of coverage, correctness or completion."""
    records={}
    for line_number,line in enumerate(raw.decode('utf-8').splitlines(),1):
        match=re.match(r'\s*\[(\d+)/(\d+)·(\d+)\]\s+([A-Z]+)@(\d+)\s+(.+)',line)
        if match:
            key=(match[4],int(match[5]))
            records.setdefault(key,[]).append(dict(line=line_number,menu=int(match[1]),reported_outcome=match[6]))
    mapped=0
    for row in result['placements']:
        found=False
        for prior in row['matches']:
            prior['reported_execution_rows']=records.get((prior['prior_text'],prior['prior_offset']),[])
            found=found or bool(prior['reported_execution_rows'])
        mapped+=int(found)
        row['execution_coverage']='REPORTED_PARTIAL_UNVERIFIED' if found else 'UNVERIFIED'
    result['execution_log']=dict(sha256=hashlib.sha256(raw).hexdigest(),
        reported_rows=sum(len(v) for v in records.values()),mapped_placements=mapped,
        exclusion_allowed=False,caveat='Rows report activity only; independently verify key domain, solver and completion before excluding work')
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--proposal',required=True);ap.add_argument('--catalog',required=True);ap.add_argument('--output',required=True)
    ap.add_argument('--execution-log')
    a=ap.parse_args();p=Path(a.proposal).read_bytes();c=Path(a.catalog).read_bytes()
    result=audit(json.loads(p),json.loads(c));result.update(proposal_sha256=hashlib.sha256(p).hexdigest(),catalog_sha256=hashlib.sha256(c).hexdigest())
    if a.execution_log:attach_execution_log(result,Path(a.execution_log).read_bytes())
    Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(placements=len(result['placements']),with_matches=sum(bool(r['matches']) for r in result['placements']),exclusions=0)))
