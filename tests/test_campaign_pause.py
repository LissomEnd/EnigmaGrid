"""A scientific pause preserves accounting and stops new work allocation."""
import os
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))

with tempfile.TemporaryDirectory() as folder:
    os.environ['GRID_DATA_DIR']=folder
    os.environ['GRID_CONFIG']=str(ROOT/'config/server.example.json')
    import coordinator as c
    c.init_db(); con=c.db()
    con.execute("insert into campaigns values(?,?,?,?,?,?)",('test','Test','1','paused',time.time(),''))
    con.execute('insert into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json) values(?,?,?,?,?,?,?,?,?,?)',('s','test','Test','demo_hash',0,10,2,1,1,'{}'))
    # No device data needed: paused segments must be excluded before eligibility.
    assert c.next_primary(con,{})[0] is None
    con.execute('insert into done_ranges values(?,?,?,?,?,?,?)',('s',0,1,'l','d',time.time(),'{}'))
    con.execute('insert into validations(segment_id,start_unit,end_unit,base_required,target_replicas,max_replicas,status,created) values(?,?,?,?,?,?,?,?)',('s',1,2,2,2,3,'pending',time.time()))
    payload=c.progress_payload(con)
    assert payload['total_units']==10
    assert payload['completed_units']==1 and payload['pending_validations']==1
    assert payload['progress_pct']==10
    assert payload['campaigns'][0]['status']=='paused'
    con.close()
print('CAMPAIGN_PAUSE_ACCOUNTING_AND_ALLOCATION_OK')
