"""A portable successor survives one asynchronously acknowledged receipt."""
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
    cfg.update(trusted_sampling_enabled=False,min_worker_version='0.1.0')
    c.CFG.write_text(json.dumps(cfg));c.init_db();con=c.db()
    try:
        con.execute("insert into contributors(id,display_name,join_key_hash,dashboard_token_hash,created) values('c','Test','j','t',?)",(time.time(),))
        con.execute("insert into devices(id,contributor_id,label,token_hash,created,meta_json,capabilities_json,settings_json) values('d','c','Test','t',?,?,'[\"cpu\"]','{\"cpu_percent\":100,\"allow_cpu\":true}')",(time.time(),json.dumps({'worker_version':'0.4.16','supported_engines':['portable_event_v1']})))
        con.execute("insert into campaigns(id,name,version,status,created) values('c','Test','1','running',?)",(time.time(),))
        con.execute("insert into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json) values('s','c','Test','portable_event_v1',0,100,0,1,10,'{\"requires\":[\"cpu\"]}')")
        first=c.allocate_batch(con,'d',32)['leases']
        assert len(first)==3 and all(x['engine']=='portable_event_v1' for x in first)
        assert {x['start_unit'] for x in first}=={0,1,2}
        # The first computed receipt can remain leased until upload/ack. The
        # active job still has a ready successor instead of draining the queue.
        assert {x['start_unit'] for x in c.allocate_batch(con,'d',32)['leases']}=={0,1,2}
        assert con.execute("select next_unit from segments where id='s'").fetchone()[0]==3
        con.execute("update leases set status='submitted' where id=?",(first[0]['id'],))
        refilled=c.allocate_batch(con,'d',32)['leases']
        assert len(refilled)==3 and {x['start_unit'] for x in refilled}=={1,2,3}
        assert con.execute("select next_unit from segments where id='s'").fetchone()[0]==4
    finally:con.close()
print('PASS portable active-receipt-successor lease window and replay')
