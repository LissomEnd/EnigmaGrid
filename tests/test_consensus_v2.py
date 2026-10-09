import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path


def main():
    ROOT=Path(__file__).resolve().parents[1]
    TMP=Path(tempfile.mkdtemp(prefix="enigma-consensus-"))
    os.environ["GRID_DATA_DIR"]=str(TMP)
    os.environ["GRID_DB"]=str(TMP/"grid.sqlite3")
    config=TMP/"server.json"
    config.write_text((ROOT/"config"/"server.example.json").read_text(encoding="utf-8"),encoding="utf-8")
    os.environ["GRID_CONFIG"]=str(config)
    sys.path.insert(0,str(ROOT/"server"))
    import coordinator as c
    if (c.DATA.resolve(),c.DB.resolve(),c.CFG.resolve()) != (
            TMP.resolve(),(TMP/"grid.sqlite3").resolve(),config.resolve()):
        raise RuntimeError("Coordinator DATA, DB or CFG is not isolated")

    c.init_db()
    con=c.db()
    con.execute("insert into campaigns(id,name,version,status,created,notes) values(?,?,?,?,?,?)",
                ("ct","Consensus Test","t","running",time.time(),"test"))
    con.execute("""insert into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,
                 chunk_size,priority,config_json) values(?,?,?,?,?,?,?,?,?,?)""",
                ("cts","ct","Consensus","demo_hash",0,1,1,1,1,"{}"))
    devices=[]
    for i in range(3):
        cid=f"c{i}"; did=f"d{i}"
        con.execute("""insert into contributors(id,display_name,public_credit,join_key_hash,
                     dashboard_token_hash,created) values(?,?,?,?,?,?)""",
                    (cid,f"C{i}",1,f"j{i}",f"t{i}",time.time()))
        con.execute("""insert into devices(id,contributor_id,label,token_hash,enabled,last_seen,
                     meta_json,created,settings_json,capabilities_json) values(?,?,?,?,1,?,?,?,?,?)""",
                    (did,cid,f"D{i}",f"k{i}",time.time(),"{}",time.time(),
                     '{"cpu_percent":100,"gpu_percent":0,"allow_cpu":true,"allow_gpu":false}',
                     '["cpu"]'))
        devices.append((cid,did))
    con.execute("""insert into validations(segment_id,start_unit,end_unit,base_required,target_replicas,
                 max_replicas,status,created) values(?,?,?,?,?,?,?,?)""",
                ("cts",0,1,2,3,3,"pending",time.time()))
    fps=["SAME","SAME","DIFFERENT"]
    for i,(cid,did) in enumerate(devices):
        con.execute("""insert into submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,
                     contributor_id,fingerprint,result_json,compute_seconds,candidate_count,status,
                     credited,submitted_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (f"s{i}",f"l{i}","cts",0,1,did,cid,fps[i],"{}",1.0,0,
                     "pending",0,time.time()+i))
    status=c.reconcile(con,"cts",0,1)
    rows=[dict(r) for r in con.execute(
        "select id,fingerprint,status,credited from submissions where segment_id='cts' order by id")]
    dev=[dict(r) for r in con.execute(
        "select id,trust_score,valid_jobs,invalid_jobs,quarantined from devices order by id")]
    assert status=="verified",status
    assert [r["credited"] for r in rows]==[1,1,0],rows
    assert rows[2]["status"]=="rejected",rows
    assert dev[2]["invalid_jobs"]==1,dev
    progress=c.progress_payload(con)
    assert progress['total_units']==1 and progress['completed_units']==1,progress
    assert progress['progress_pct']==100,progress
    assert progress['campaigns'][0]['status']=='complete',progress
    print(json.dumps({"status":status,"submissions":rows,"devices":dev},indent=2))
    con.close()
    shutil.rmtree(TMP)

if __name__ == "__main__":
    main()
