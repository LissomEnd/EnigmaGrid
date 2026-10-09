"""Own-only bounded validation queues skip scans without hiding foreign/orphan work."""
import json
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
import coordinator as c

with tempfile.TemporaryDirectory() as folder:
    c.DATA=Path(folder);c.DB=c.DATA/'grid.sqlite3';c.CFG=c.DATA/'server.json'
    cfg=json.loads((ROOT/'config/server.example.json').read_text())
    cfg.update(trusted_sampling_enabled=True,min_worker_version='0.1.0')
    c.CFG.write_text(json.dumps(cfg));c.init_db();con=c.db()
    try:
        for identity in ('owner','foreign'):
            con.execute("INSERT INTO contributors(id,display_name,join_key_hash,dashboard_token_hash,created) VALUES(?,?,?,?,0)",(identity,identity,identity,identity))
            con.execute("""INSERT INTO devices(id,contributor_id,label,token_hash,created,meta_json,
                capabilities_json,settings_json) VALUES(?,?,?,?,0,?,'["cpu","bounded_crib_v1"]',
                '{"cpu_percent":100,"allow_cpu":true}')""",
                (identity,identity,identity,identity,json.dumps({'worker_version':'0.4.66','supported_engines':['bounded_crib_v1']})))
        con.execute("INSERT INTO campaigns(id,name,version,status,created) VALUES('c','Test','1','running',0)")
        con.execute("""INSERT INTO segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,
            chunk_size,priority,config_json) VALUES('s','c','Test','bounded_crib_v1',0,10,10,1,10,
            '{"requires":["cpu","bounded_crib_v1"]}')""")
        assert con.execute("SELECT value FROM selection_cache_meta WHERE key='pending_sources_bounded_v1'").fetchone()[0]=='1'
        con.execute("""INSERT INTO submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,
            contributor_id,fingerprint,result_json,compute_seconds,candidate_count,submitted_at,worker_version)
            VALUES('own0','old0','s',0,1,'owner','owner','f','{}',.1,0,0,'0.4.66')""")
        con.execute("INSERT INTO validations(segment_id,start_unit,end_unit,base_required,target_replicas,max_replicas,created) VALUES('s',0,1,2,2,2,0)")
        dev=con.execute("SELECT * FROM devices WHERE id='owner'").fetchone()
        assert list(c.validation_candidates(con,dev))==[]
        assert con.execute("SELECT value FROM selection_cache_meta WHERE key='pending_sources_bounded_v1'").fetchone()[0]=='1'
        # Trusted acceptance updates the validation before its source; the
        # source-integrity flag must stay usable after this normal transition.
        con.execute("UPDATE validations SET status='accepted_trusted' WHERE segment_id='s' AND start_unit=0")
        con.execute("UPDATE submissions SET status='accepted_trusted' WHERE id='own0'")
        assert con.execute("SELECT value FROM selection_cache_meta WHERE key='pending_sources_bounded_v1'").fetchone()[0]=='1'
        con.execute("""INSERT INTO submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,
            contributor_id,fingerprint,result_json,compute_seconds,candidate_count,submitted_at,worker_version)
            VALUES('foreign1','old1','s',1,2,'foreign','foreign','f','{}',.1,0,0,'0.4.66')""")
        con.execute("INSERT INTO validations(segment_id,start_unit,end_unit,base_required,target_replicas,max_replicas,created) VALUES('s',1,2,2,2,2,1)")
        rows=list(c.validation_candidates(con,dev))
        assert len(rows)==1 and rows[0][0]['v_start']==1
        con.execute("DELETE FROM submissions WHERE id='foreign1'")
        assert con.execute("SELECT value FROM selection_cache_meta WHERE key='pending_sources_bounded_v1'").fetchone()[0]=='0'
        # With integrity dirty, the existing full selector remains authoritative.
        rows=list(c.validation_candidates(con,dev))
        assert len(rows)==1 and rows[0][0]['v_start']==1
        con.execute("UPDATE submissions SET status='verified' WHERE id='own0'")
        assert con.execute("SELECT value FROM selection_cache_meta WHERE key='pending_sources_bounded_v1'").fetchone()[0]=='0'
    finally:
        con.close()
print('PASS own-only fast skip, foreign contributor selection and fail-closed source integrity')
