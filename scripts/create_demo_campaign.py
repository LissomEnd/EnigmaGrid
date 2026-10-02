import json, sqlite3, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/"state"/"grid.sqlite3"
con=sqlite3.connect(DB)
con.execute("pragma foreign_keys=ON")
cid="p1030680-grid-dev"
con.execute("""insert or ignore into campaigns(id,name,version,status,created,notes)
               values(?,?,?,?,?,?)""",(cid,"P1030680 Volunteer Grid DEV","0.1","running",time.time(),
               "Infrastructure validation only; not the production giant campaign."))
cfg=json.dumps({"hash_rounds":5000},separators=(",",":"))
con.execute("""insert or ignore into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json)
               values(?,?,?,?,?,?,?,?,?,?)""",
            ("dev-demo-hash",cid,"DEV interruption/requeue test","demo_hash",0,200,0,5,1,cfg))
con.commit()
print("demo campaign ready")
