"""Large batches must count reservations made earlier in the same transaction."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
import coordinator as c

with tempfile.TemporaryDirectory() as directory:
    c.DATA=Path(directory);c.DB=c.DATA/'grid.sqlite3';c.CFG=c.DATA/'server.json'
    cfg=json.loads((ROOT/'config/server.example.json').read_text())
    cfg.update(trusted_sampling_enabled=True,min_worker_version='0.1.0')
    c.CFG.write_text(json.dumps(cfg));c.init_db();con=c.db()
    try:
        con.execute("insert into contributors(id,display_name,join_key_hash,dashboard_token_hash,created) values('c','Test','j','t',?)",(time.time(),))
        con.execute("insert into devices(id,contributor_id,label,token_hash,created,meta_json,capabilities_json,settings_json) values('d','c','Test','t',?,?,'[\"cpu\",\"bounded_crib_v1\"]','{\"cpu_percent\":100,\"allow_cpu\":true}')",(time.time(),json.dumps({'worker_version':'0.4.16','supported_engines':['bounded_crib_v1']})))
        con.execute("insert into campaigns(id,name,version,status,created) values('c','Test','1','running',?)",(time.time(),))
        con.execute("insert into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json) values('s','c','Test','bounded_crib_v1',0,100,0,1,10,'{\"requires\":[\"cpu\",\"bounded_crib_v1\"]}')")
        initial=c.allocate_batch(con,'d',32,max_new=3)
        assert initial['new_lease_limit'] is True and len(initial['leases'])==3
        replay=c.allocate_batch(con,'d',32,max_new=0)['leases']
        assert {x['id'] for x in replay}=={x['id'] for x in initial['leases']}
        assert con.execute("select next_unit from segments where id='s'").fetchone()[0]==3
        topped=c.allocate_batch(con,'d',32,max_new=5)['leases']
        assert len(topped)==8
        for bad in (-1,33,True,1.5,'2'):
            try:c.allocate_batch(con,'d',32,max_new=bad)
            except ValueError:pass
            else:raise AssertionError('Invalid local budget accepted')
        assert con.execute("select next_unit from segments where id='s'").fetchone()[0]==8
        leases=c.allocate_batch(con,'d',32)['leases']
        assert len(leases)==32
        assert len({x['start_unit'] for x in leases})==32
        assert {x['id'] for x in c.allocate_batch(con,'d',1)['leases']}=={x['id'] for x in leases}
        assert con.execute("select next_unit from segments where id='s'").fetchone()[0]==32
        con.execute('begin immediate')
        diagnostics={}
        assert c.next_primary(con,con.execute("select * from devices where id='d'").fetchone(),diagnostics)[0] is None
        assert diagnostics['wait_reason']=='verification_pending'
        con.commit()
        assert c.trusted_sampling.MAX_PENDING_VERIFICATIONS==32
        # Seven submitted receipts occupy the remaining verification window.
        # Replay of the other 25 leases must retain the partial-batch diagnosis.
        for index,lease in enumerate(leases[:7]):
            con.execute("update leases set status='submitted' where id=?",(lease['id'],))
            con.execute("insert into sampling_decisions values(?,'d','bounded_crib_v1','0.4.16','verify','probation',0)",('pending-test-'+str(index),))
        partial=c.allocate_batch(con,'d',32)
        assert len(partial['leases'])==25
        assert partial['wait_reason']=='verification_pending'
        assert partial['retry_after_seconds']==5
        assert con.execute("select next_unit from segments where id='s'").fetchone()[0]==32
        con.execute("delete from sampling_decisions where submission_id like 'pending-test-%'")
        con.execute("update leases set status='submitted'")
        con.execute("update segments set next_unit=end_unit")
        for lease in leases:
            start=lease['start_unit'];end=lease['end_unit']
            con.execute("insert into submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,contributor_id,fingerprint,result_json,compute_seconds,candidate_count,submitted_at) values(?,?,'s',?,?,'d','c','f','{}',0.1,0,?)",('sub'+str(start),lease['id'],start,end,time.time()))
            con.execute("insert into validations(segment_id,start_unit,end_unit,base_required,target_replicas,max_replicas,created) values('s',?,?,2,2,2,?)",(start,end,time.time()))
        def device(device_id,contributor):
            con.execute("insert or ignore into contributors(id,display_name,join_key_hash,dashboard_token_hash,created) values(?,?,?,?,?)",(contributor,'Test',contributor+'j',contributor+'t',time.time()))
            con.execute("insert into devices(id,contributor_id,label,token_hash,created,meta_json,capabilities_json,settings_json) select ?,?,'Test',?,created,meta_json,capabilities_json,settings_json from devices where id='d'",(device_id,contributor,device_id+'token'))
        device('sibling','c');device('independent','other');device('third','third')
        assert not c.allocate_batch(con,'sibling',32)['leases'],'Same contributor may not verify own work'
        validation=c.allocate_batch(con,'independent',32)['leases']
        assert len(validation)==32 and all(x['purpose']=='validation' for x in validation)
        assert not c.allocate_batch(con,'third',32)['leases'],'Active replicas already fill target/max'
        assert {x['id'] for x in c.allocate_batch(con,'independent',32)['leases']}=={x['id'] for x in validation}
    finally:con.close()
print('PASS batch 32, replay, pending bound, contributor independence and active replica cap')
