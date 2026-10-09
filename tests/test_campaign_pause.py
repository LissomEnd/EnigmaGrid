"""A scientific pause preserves accounting and stops new work allocation."""
import os
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))

def main():
    # Direct script, never run during pytest collection with a cached live
    # coordinator module whose DATA path ignores this temporary environment.
    with tempfile.TemporaryDirectory() as folder:
        os.environ['GRID_DATA_DIR']=folder
        os.environ['GRID_DB']=str(Path(folder)/'grid.sqlite3')
        config=Path(folder)/'server.json'
        config.write_text((ROOT/'config/server.example.json').read_text(encoding='utf-8'),encoding='utf-8')
        os.environ['GRID_CONFIG']=str(config)
        import coordinator as c
        if (c.DATA.resolve(),c.DB.resolve(),c.CFG.resolve()) != (
                Path(folder).resolve(),(Path(folder)/'grid.sqlite3').resolve(),config.resolve()):
            raise RuntimeError('Coordinator DATA, DB or CFG is not isolated')
        c.init_db();con=c.db()
        try:
            con.execute("insert into campaigns values(?,?,?,?,?,?)",('test','Test','1','paused',time.time(),''))
            con.execute('insert into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json) values(?,?,?,?,?,?,?,?,?,?)',('s','test','Test','demo_hash',0,10,2,1,1,'{}'))
            # No device data needed: paused segments must be excluded before eligibility.
            assert c.next_primary(con,{})[0] is None
            con.execute('insert into done_ranges(segment_id,start_unit,end_unit,lease_id,device_id,completed_at,result_json) values(?,?,?,?,?,?,?)',('s',0,1,'l','d',time.time(),'{}'))
            con.execute('insert into validations(segment_id,start_unit,end_unit,base_required,target_replicas,max_replicas,status,created) values(?,?,?,?,?,?,?,?)',('s',1,2,2,2,3,'pending',time.time()))
            payload=c.progress_payload(con)
            assert payload['total_units']==10
            assert payload['completed_units']==1 and payload['pending_validations']==1
            assert payload['progress_pct']==10
            assert payload['campaigns'][0]['status']=='paused'
        finally:con.close()
    print('CAMPAIGN_PAUSE_ACCOUNTING_AND_ALLOCATION_OK')


if __name__=='__main__':main()
