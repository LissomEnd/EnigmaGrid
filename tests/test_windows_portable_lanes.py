"""Exclusive CPU/GPU cohorts cover the lease once and merge deterministically."""
import sys
import threading
from pathlib import Path
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'worker'))
sys.path.insert(0,str(root/'solver/runtime/src'))
import worker
from search import portable_search

seen=[];lock=threading.Lock()
def fake_search(_text,start_seed,*,count,backend,cohort_blocks,topk,**_kwargs):
    with lock:seen.append((start_seed,start_seed+count,backend,cohort_blocks))
    return [{'attempt':start_seed+offset,'score':-(start_seed+offset),
             'metrics':{'search_cost':start_seed+offset}}
            for offset in range(0,count,256)][:topk]

lease={'start_unit':0,'end_unit':1,'config':{'count_per_unit':4096,'iterations':1,'topk':8,
       'base_attempt':71000000000}}
runtime={'settings':{'allow_cpu':True,'allow_gpu':True,'cpu_percent':100,'gpu_percent':100}}
with patch.object(worker,'_GPU_SCORERS',[lambda keys:keys]),patch.object(portable_search,'search',fake_search):
    result,_=worker.run_portable(lease,runtime,None)
worker.release_portable_executor(runtime)
start=lease['config']['base_attempt'];cursor=start
for left,right,backend,blocks in sorted(seen):
    assert left==cursor,(cursor,left,right)
    assert blocks==(right-left+255)//256 if backend=='opencl' else blocks==1
    cursor=right
assert cursor==start+4096
assert {'cpu','opencl'}=={item[2] for item in seen}
assert [item['attempt'] for item in result['candidates']]==[start+256*i for i in range(8)]

# Use the real integer scorer as a GPU stand-in to verify receipt parity for
# disjoint paths without requiring any particular GPU on the test host.
from search.cpu_numba import encode
import json
text=json.loads((root/'solver/runtime/data/messages/p1030680.json').read_text())['ciphertext']
encoded=encode(text)
small={'start_unit':0,'end_unit':1,'config':{'count_per_unit':512,'iterations':1,
       'topk':8,'base_attempt':71000000000}}
cpu_runtime={'settings':{'allow_cpu':True,'allow_gpu':False,'cpu_percent':100,'gpu_percent':0}}
reference,_=worker.run_portable(small,cpu_runtime,None)
with patch.object(worker,'_GPU_SCORERS',[lambda keys:portable_search.score_cpu(encoded,keys)]):
    actual,_=worker.run_portable(small,runtime,None)
worker.release_portable_executor(runtime)
assert actual==reference,'CPU/GPU cohort merge changed the portable receipt'
print('PASS exclusive CPU/GPU portable cohorts, full lease coverage and receipt parity')
