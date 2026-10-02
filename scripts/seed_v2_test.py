import json, os, sqlite3, time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
data=Path(os.environ.get('GRID_DATA_DIR',str(root/'state_v2test')))
db=data/'grid.sqlite3'
con=sqlite3.connect(db)
con.execute('pragma foreign_keys=ON')
def campaign(cid,name):
    con.execute("insert or replace into campaigns(id,name,version,status,created,notes) values(?,?,?,?,?,?)",
                (cid,name,'test','running',time.time(),'isolated v0.2 validation test'))
campaign('v2-demo','V2 Demo Redundancy')
cfg=json.dumps({'hash_rounds':2000,'requires':['cpu'],'replicas_required':2,'max_replicas':3},separators=(',',':'))
con.execute("""insert or replace into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json)
             values(?,?,?,?,?,?,?,?,?,?)""",('v2-demo-seg','v2-demo','V2 demo CPU','demo_hash',0,20,0,5,1,cfg))
campaign('v2-gpu','V2 GPU Scheduler')
gcfg=json.dumps({'hash_rounds':10,'requires':['cuda'],'replicas_required':2,'max_replicas':3},separators=(',',':'))
con.execute("""insert or replace into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json)
             values(?,?,?,?,?,?,?,?,?,?)""",('v2-gpu-seg','v2-gpu','V2 CUDA routing','demo_hash',0,10,0,1,50,gcfg))
con.commit();print(db)