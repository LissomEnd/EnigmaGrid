"""Read-side scheduling must permit writers and reject stale advisory candidates."""
import json
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
import coordinator as c


def scenario(change,check,legacy=False):
    with tempfile.TemporaryDirectory() as directory:
        c.DATA=Path(directory);c.DB=c.DATA/'grid.sqlite3';c.CFG=c.DATA/'server.json'
        cfg=json.loads((ROOT/'config/server.example.json').read_text())
        cfg.update(trusted_sampling_enabled=True,min_worker_version='0.1.0')
        c.CFG.write_text(json.dumps(cfg));c.init_db();con=c.db();peer=c.db()
        original=c.validation_candidates
        try:
            for identity in ('source','requester','competitor'):
                con.execute('insert into contributors(id,display_name,join_key_hash,dashboard_token_hash,created) values(?,?,?,?,?)',(identity,identity,identity,identity,time.time()))
                con.execute('insert into devices(id,contributor_id,label,token_hash,created,meta_json,capabilities_json,settings_json) values(?,?,?,?,?,?,?,?)',(identity,identity,identity,identity,time.time(),json.dumps({'worker_version':'0.4.44','supported_engines':['bounded_crib_v1']}),'["cpu","bounded_crib_v1"]','{"cpu_percent":100,"allow_cpu":true}'))
            con.execute("insert into campaigns(id,name,version,status,created) values('c','Test','1','running',?)",(time.time(),))
            con.execute("insert into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json) values('s','c','Test','bounded_crib_v1',0,40,40,1,10,'{\"requires\":[\"cpu\",\"bounded_crib_v1\"]}')")
            for n in range(40):
                con.execute("insert into submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,contributor_id,fingerprint,result_json,compute_seconds,candidate_count,submitted_at) values(?,?,'s',?,?,'source','source','f','{}',0.1,0,?)",('sub'+str(n),'old'+str(n),n,n+1,time.time()))
                con.execute("insert into validations(segment_id,start_unit,end_unit,base_required,target_replicas,max_replicas,created) values('s',?,?,2,2,2,?)",(n,n+1,n))
            fired=[]
            def selection(db,dev):
                assert not db.in_transaction,'Backlog scan holds SQLite writer'
                # Materialize the same advisory candidates, then let a different
                # connection commit before the allocator starts its transaction.
                rows=list(original(db,dev))
                if not fired:
                    change(peer,rows);fired.append(True)
                yield from rows
            c.validation_candidates=selection
            if legacy:
                from types import SimpleNamespace
                handler=SimpleNamespace(send_json=lambda code,payload:(code,payload))
                dev=con.execute("select * from devices where id='requester'").fetchone()
                code,payload=c.Handler.lease(handler,con,dev)
                assert code==200 and 'lease' in payload and 'leases' not in payload
                result={**payload,'leases':[payload['lease']] if payload['lease'] else []}
            else:result=c.allocate_batch(con,'requester',32)
            assert fired
            check(con,result)
            assert not con.in_transaction
        finally:
            c.validation_candidates=original;peer.close();con.close()


def compete(peer,rows):
    peer.execute('begin immediate')
    dev=peer.execute("select * from devices where id='competitor'").fetchone()
    for row,_,_ in rows[:32]:c.make_lease(peer,dev,row,row['v_start'],row['v_end'],'validation',900)
    peer.commit()

def check_competition(con,result):
    assert not result['leases']
    assert result['wait_reason']=='validation_selection_changed'
    following=c.allocate_batch(con,'requester',32)
    assert {x['start_unit'] for x in following['leases']}==set(range(32,40))
    assert con.execute("select max(n) from (select count(*) n from leases where status='leased' group by segment_id,start_unit,end_unit)").fetchone()[0]==1

def check_empty(con,result):
    assert not result['leases'],'Stale validation candidate assigned'

def check_disabled(con,result):
    assert result['enabled'] is False and not result['leases']

scenario(compete,check_competition)
scenario(lambda peer,rows:peer.execute("update campaigns set status='paused'"),check_empty)
scenario(lambda peer,rows:peer.execute("update devices set quarantined=1 where id='requester'"),check_disabled)
scenario(lambda peer,rows:peer.execute("update devices set contributor_id='source' where id='requester'"),check_empty)
scenario(lambda peer,rows:peer.execute("update validations set target_replicas=1,max_replicas=1"),check_empty)
scenario(lambda peer,rows:peer.execute("update validations set status='verified'"),check_empty)
scenario(lambda peer,rows:peer.execute("update devices set settings_json='{\"cpu_percent\":0,\"allow_cpu\":false}' where id='requester'"),check_empty)
scenario(lambda peer,rows:peer.execute("update segments set config_json='{\"requires\":[\"gpu\"]}'"),check_empty)
print('PASS selection outside writer; competing allocation, refill, pause, quarantine, contributor, replica, completion, settings and config changes rechecked')

scenario(compete,check_competition,legacy=True)
scenario(lambda peer,rows:peer.execute("update campaigns set status='paused'"),check_empty,legacy=True)
print('PASS legacy single-lease wire compatibility and concurrent writer revalidation')

# Exercise the diagnostic branch after a committed allocation, including replay.
from unittest.mock import patch
for legacy in (False,True):
    tick=iter(range(1000))
    with patch.object(c.time,'perf_counter',side_effect=lambda:next(tick)):
        def check_allocated(con,result):
            assert len(result['leases'])==(1 if legacy else 32)
        scenario(lambda peer,rows:None,check_allocated,legacy=legacy)
print('PASS slow allocation diagnostics return committed batch and legacy leases')

# A validation may appear after an empty preview. It must win over remaining
# primary work, even though no stale preview row exists to recheck.
with tempfile.TemporaryDirectory() as directory:
    c.DATA=Path(directory);c.DB=c.DATA/'grid.sqlite3';c.CFG=c.DATA/'server.json'
    cfg=json.loads((ROOT/'config/server.example.json').read_text())
    cfg.update(trusted_sampling_enabled=False,min_worker_version='0.1.0')
    c.CFG.write_text(json.dumps(cfg));c.init_db();con=c.db();peer=c.db()
    original=c.validation_candidates
    try:
        for identity in ('source','requester'):
            con.execute('insert into contributors(id,display_name,join_key_hash,dashboard_token_hash,created) values(?,?,?,?,?)',(identity,identity,identity,identity,time.time()))
            con.execute('insert into devices(id,contributor_id,label,token_hash,created,meta_json,capabilities_json,settings_json) values(?,?,?,?,?,?,?,?)',(identity,identity,identity,identity,time.time(),json.dumps({'worker_version':'0.4.44','supported_engines':['bounded_crib_v1']}),'["cpu","bounded_crib_v1"]','{"cpu_percent":100,"allow_cpu":true}'))
        con.execute("insert into campaigns(id,name,version,status,created) values('c','Test','1','running',?)",(time.time(),))
        con.execute("insert into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json) values('s','c','Test','bounded_crib_v1',0,40,1,1,10,'{\"requires\":[\"cpu\",\"bounded_crib_v1\"]}')")
        con.execute("insert into submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,contributor_id,fingerprint,result_json,compute_seconds,candidate_count,submitted_at) values('first','old','s',0,1,'source','source','f','{}',0.1,0,?)",(time.time(),))
        fired=[]
        def late_validation(db,dev):
            yield from original(db,dev)
            if not fired:
                peer.execute("insert into validations(segment_id,start_unit,end_unit,base_required,target_replicas,max_replicas,created) values('s',0,1,2,2,2,?)",(time.time(),))
                fired.append(True)
        c.validation_candidates=late_validation
        first=c.allocate_batch(con,'requester',1)
        assert fired and len(first['leases'])==1 and first['leases'][0]['purpose']=='validation',first
        assert first['leases'][0]['start_unit']==0
    finally:
        c.validation_candidates=original;peer.close();con.close()
print('PASS validation introduced after an empty preview retains priority over primary work')
