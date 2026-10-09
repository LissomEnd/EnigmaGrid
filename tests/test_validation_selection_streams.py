"""Indexed validation streams preserve complete priority order without full sorting."""
import json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'server'))
import coordinator as c
# Reference retains the previous exact ordering query, independent of optimizer.
def reference(con,dev):
    priority=c.validation_priority_sql() if c.load_cfg().get('trusted_sampling_enabled',False) else '(0+0)'
    rows=con.execute(f'''SELECT s.*,v.start_unit v_start,v.end_unit v_end,v.target_replicas v_target,v.max_replicas v_max,v.created v_created
        FROM validations v JOIN segments s ON s.id=v.segment_id JOIN campaigns ca ON ca.id=s.campaign_id
        WHERE v.status='pending' AND ca.status='running' ORDER BY {priority},s.priority,v.created,v.segment_id,v.start_unit,v.end_unit''')
    for row in rows:
        checked=c.recheck_validation_candidate(con,dev,row)
        if checked[0] is not None:yield row
with tempfile.TemporaryDirectory() as folder:
    c.DATA=Path(folder);c.DB=c.DATA/'db';c.CFG=c.DATA/'config'
    cfg=json.loads((ROOT/'config/server.example.json').read_text());cfg.update(trusted_sampling_enabled=True,volunteer_validation_enabled=True,min_worker_version='0.1.0')
    c.CFG.write_text(json.dumps(cfg));c.init_db();con=c.db();con.execute('BEGIN')
    for owner in ('worker','other','third'):
        con.execute('INSERT INTO contributors(id,display_name,join_key_hash,dashboard_token_hash,created) VALUES(?,?,?,?,0)',(owner,owner,owner+'j',owner+'d'))
        con.execute("INSERT INTO devices(id,contributor_id,label,token_hash,created,meta_json,capabilities_json,settings_json) VALUES(?,?,? ,?,0,?,'[\"cpu\",\"bounded_crib_v1\"]','{\"cpu_percent\":100,\"allow_cpu\":true}')",(owner,owner,owner,owner,json.dumps({'worker_version':'qualified','supported_engines':['bounded_crib_v1']})))
    con.execute("INSERT INTO campaigns(id,name,version,status,created) VALUES('c','test','1','running',0)")
    for name,rank,requires in [('s1',10,['cpu']),('s2',10,['cpu']),('s3',5,['cpu']),('gpu',1,['cuda'])]:
        con.execute("INSERT INTO segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json) VALUES(?,'c',?,'bounded_crib_v1',0,10000,10000,1,?,?)",(name,name,rank,json.dumps({'requires':requires})))
    for device in ('other','worker','third'):
        con.execute("INSERT INTO sampling_state VALUES(?,'bounded_crib_v1','qualified',0,100)",(device,))
        con.execute("INSERT INTO sampling_state VALUES(?,'bounded_crib_v1','probation',0,20)",(device,))
    for i in range(240):
        seg=('s1','s2','s3','gpu')[i%4];owner='worker' if i%13==0 else 'other';version='probation' if i%7==0 else ('missing' if i%17==0 else 'qualified')
        con.execute("INSERT INTO submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,contributor_id,fingerprint,result_json,compute_seconds,candidate_count,submitted_at,worker_version) VALUES(?,?,?,?,?,?,?,'f','{}',.1,?,0,?)",('sub'+str(i),'lease'+str(i),seg,i,i+1,owner,owner,int(i%19==0),version))
        con.execute("INSERT INTO validations(segment_id,start_unit,end_unit,base_required,target_replicas,max_replicas,status,created) VALUES(?,?,?,2,2,2,?,?)",(seg,i,i+1,'verified' if i%23==0 else 'pending',i//9))
        if i%11==0:con.execute("INSERT INTO sampling_decisions VALUES(?,?,'bounded_crib_v1',?,'verify','random_audit',100)",('sub'+str(i),owner,version))
        if i%22==0:con.execute("INSERT INTO sampling_evidence VALUES(?,?,'bounded_crib_v1',?,'match')",('sub'+str(i),owner,version))
        if i%29==0:con.execute("INSERT INTO server_verifications(segment_id,start_unit,end_unit,status,updated) VALUES(?,?,?,'running',?)",(seg,i,i+1,time.time()))
        if i%31==0:con.execute("INSERT INTO leases(id,segment_id,device_id,start_unit,end_unit,work_token,status,leased_at,expires_at,purpose) VALUES(?,?,'third',?,?,'token','leased',0,9999999999,'validation')",('active'+str(i),seg,i,i+1))
    # Orphan ranges and missing sampling decisions/states must remain visible.
    con.execute("INSERT INTO validations(segment_id,start_unit,end_unit,base_required,target_replicas,max_replicas,status,created) VALUES('s1',800,801,2,2,2,'pending',0)")
    con.commit()
    # Simulate an existing installation being migrated: historical submissions
    # and selected audits must enter the maintained queues exactly once.
    expected_audits=con.execute('SELECT count(*) FROM selection_audit_queue').fetchone()[0]
    expected_identities=con.execute('SELECT count(*) FROM selection_negative_identities').fetchone()[0]
    con.execute('DELETE FROM selection_audit_queue')
    con.execute('DELETE FROM selection_negative_identities')
    con.execute("DELETE FROM selection_cache_meta WHERE key='v1_backfilled'")
    c.init_db()
    assert con.execute('SELECT count(*) FROM selection_audit_queue').fetchone()[0]==expected_audits
    assert con.execute('SELECT count(*) FROM selection_negative_identities').fetchone()[0]==expected_identities
    c.init_db()
    assert con.execute('SELECT count(*) FROM selection_audit_queue').fetchone()[0]==expected_audits
    dev=con.execute("SELECT * FROM devices WHERE id='worker'").fetchone()
    key=lambda row:(row['id'],row['v_start'],row['v_end'])
    for enabled in (True,False):
        cfg['trusted_sampling_enabled']=enabled;c.CFG.write_text(json.dumps(cfg))
        expected=[key(row) for row in reference(con,dev)]
        actual=[key(row) for row,_,_ in c.validation_candidates(con,dev)]
        assert actual==expected,(enabled,actual,expected)
        assert len(set(actual))==len(actual)
    # A long own prefix cannot hide independent work behind it.
    con.execute('BEGIN')
    for i in range(1000,3000):
        con.execute("INSERT INTO submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,contributor_id,fingerprint,result_json,compute_seconds,candidate_count,submitted_at,worker_version) VALUES(?,?,'s1',?,?,'worker','worker','f','{}',.1,0,0,'qualified')",('own'+str(i),'ownlease'+str(i),i,i+1))
        con.execute("INSERT INTO validations(segment_id,start_unit,end_unit,base_required,target_replicas,max_replicas,status,created) VALUES('s1',?,?,2,2,2,'pending',-10)",(i,i+1))
    con.commit()
    cfg['trusted_sampling_enabled']=True;c.CFG.write_text(json.dumps(cfg))
    expected=[key(row) for row in reference(con,dev)];actual=[key(row) for row,_,_ in c.validation_candidates(con,dev)]
    assert actual==expected
    selected=con.execute("SELECT device_id,engine,worker_version FROM sampling_decisions WHERE submission_id='sub11'").fetchone()
    assert con.execute("SELECT 1 FROM selection_audit_queue WHERE submission_id='sub11'").fetchone()
    con.execute("INSERT INTO sampling_evidence VALUES(?,?,?,?, 'match')",('sub11',*selected))
    assert not con.execute("SELECT 1 FROM selection_audit_queue WHERE submission_id='sub11'").fetchone()
    expected=[key(row) for row in reference(con,dev)];actual=[key(row) for row,_,_ in c.validation_candidates(con,dev)]
    assert actual==expected
    con.close()
print('PASS exact validation ordering across audit/probation/ordinary, equal-priority segments, missing evidence/state, ownership, active replicas, server verifier, capabilities and deep own prefix')
