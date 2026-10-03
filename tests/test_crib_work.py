"""Work routing bounds and honest negative receipts for the constrained engine."""
import copy
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'solver/runtime/src'))
from search.crib_work import run,validate_envelope,verify_result,validate_receipt_shape

job=dict(engine='bounded_crib_v1',ciphertext='A'*72,crib='A'*24,offset=0,
         core_indices=[0],model='clean',pairs=10,
         budgets=dict(node_limit=1,board_limit=1,completion_limit=1,candidate_limit=1))
lease=dict(engine='bounded_crib_v1',start_unit=0,end_unit=1,
           config=dict(job=job,requires=['cpu','bounded_crib_v1']))
# Enigma cannot map a letter to itself: this is a true negative, not a timeout.
result=run(lease)
assert result['summary']['status']=='complete_negative'
assert result['receipt']['historical_solution'] is False
assert result['receipt']['candidates']==[]
assert verify_result(lease,result)[0]==result
for field,value in [('status','unknown_budget'),('job_hash','0'*64),('exhaustive_within_scope',False)]:
    forged=copy.deepcopy(result);forged['summary'][field]=value
    try:verify_result(lease,forged)
    except ValueError:pass
    else:raise AssertionError('Forged summary accepted: '+field)
forged=copy.deepcopy(result);forged['receipt']['visited_cores']=100
try:verify_result(lease,forged)
except ValueError:pass
else:raise AssertionError('Forged coverage accepted')
limited=copy.deepcopy(lease);limited['config']['job']['crib']='B'*24
partial=run(limited)
assert partial['summary']['status']=='unknown_budget'
assert partial['summary']['exhaustive_within_scope'] is False
assert verify_result(limited,partial)[0]==partial
assert validate_receipt_shape(limited,partial)[0]==partial
assert validate_receipt_shape(lease,result)[0]==result
for field,value in [('scope_hash','0'*64),('core_count',2),('nodes',-1),('visited_cores',True)]:
    altered=copy.deepcopy(partial);altered['receipt'][field]=value
    try:validate_receipt_shape(limited,altered)
    except ValueError:pass
    else:raise AssertionError('Invalid receipt accepted: '+field)
forged=copy.deepcopy(partial)
forged['summary'].update(status='complete_negative',exhaustive_within_scope=True)
forged['receipt'].update(status='complete_negative',complete=True)
try:verify_result(limited,forged)
except ValueError:pass
else:raise AssertionError('Budget cutoff promoted to negative')
for change in ['missing_capability','many_units','oversized_domain','unknown_field']:
    bad=copy.deepcopy(lease)
    if change=='missing_capability':bad['config']['requires']=['cpu']
    elif change=='many_units':bad['end_unit']=2
    elif change=='oversized_domain':bad['config']['job']['core_indices']=list(range(129))
    else:bad['config']['job']['command']='not executable input'
    try:validate_envelope(bad)
    except ValueError:pass
    else:raise AssertionError(change)
print('CRIB_WORK_BOUNDS_AND_NEGATIVE_RECEIPT_OK')

sys.path.insert(0,str(ROOT/'worker'))
import worker
result,count=worker.execute(lease,{'settings':{'allow_cpu':True,'cpu_percent':100}})
assert count==0 and result['summary']['status']=='complete_negative'
try:worker.execute(lease,{'settings':{'allow_cpu':False,'cpu_percent':0}})
except InterruptedError:pass
else:raise AssertionError('Disabled CPU accepted work')
original=worker.read_control
worker.read_control=lambda _: {'paused':False,'stop_requested':True}
try:
    try:worker.execute(lease,{'settings':{'allow_cpu':True,'cpu_percent':100}},Path('unused'))
    except InterruptedError:pass
    else:raise AssertionError('Stop request ignored')
finally:worker.read_control=original
print('CRIB_WORK_DISPATCH_AND_STOP_OK')

from dataclasses import asdict
from search.crib_pilot import core_at
from search.c3_models import stream
key=core_at(0);plain=('EINTESTDERMASCHINE'*5)[:72]
rows=stream(key,len(plain))
cipher=''.join(chr(65+rows[i][ord(c)-65]) for i,c in enumerate(plain))
positive=copy.deepcopy(lease)
positive['config']['job'].update(ciphertext=cipher,crib=plain,pairs=0)
positive['config']['job']['budgets'].update(node_limit=5000,board_limit=64,completion_limit=256)
found=run(positive)
assert found['receipt']['candidates'] and found['receipt']['candidates'][0]['plaintext']==plain
assert validate_receipt_shape(positive,found)[0]==found
forged=copy.deepcopy(found);forged['receipt']['candidates'][0]['plaintext']='Z'*72
try:validate_receipt_shape(positive,forged)
except ValueError:pass
else:raise AssertionError('False plaintext accepted')
forged=copy.deepcopy(found);forged['receipt']['candidates'][0]['key']['positions']='ZZZZ'
try:validate_receipt_shape(positive,forged)
except ValueError:pass
else:raise AssertionError('Out-of-domain key accepted')
print('CRIB_CANDIDATE_REPLAY_AND_DOMAIN_OK')

program=dict(ciphertext='A'*72,hypotheses=[dict(text='B'*24,legal_clean_offsets=[0])],chunk=4,ordinal_base=17,candidate_limit=8)
scheduled=dict(engine='bounded_crib_v1',start_unit=0,end_unit=1,config=dict(program=program,requires=['cpu','bounded_crib_v1']))
first=validate_envelope(scheduled)
second=validate_envelope(dict(scheduled,start_unit=1,end_unit=2))
assert not set(first['core_indices']).intersection(second['core_indices'])
assert first==validate_envelope(scheduled)
assert first['ordinal']==17 and second['ordinal']==18
assert first['budgets']['candidate_limit']==8
print('CRIB_INDEXED_PROGRAM_STABLE_NONOVERLAPPING_OK')
