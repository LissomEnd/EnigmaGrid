import os, sys, time, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    with tempfile.TemporaryDirectory(prefix="enigma-quarantine-") as folder:
        TMP=Path(folder)
        os.environ["GRID_DATA_DIR"]=str(TMP)
        # Override inherited operator database paths as well as the state directory.
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
        con.execute("""insert into contributors(id,display_name,public_credit,join_key_hash,
                     dashboard_token_hash,created) values(?,?,?,?,?,?)""",
                    ("c","Test",1,"j","t",time.time()))
        con.execute("""insert into devices(id,contributor_id,label,token_hash,enabled,last_seen,
                     meta_json,created,settings_json,capabilities_json) values(?,?,?,?,1,?,?,?,?,?)""",
                    ("d","c","D","k",time.time(),"{}",time.time(),
                     '{"cpu_percent":100,"gpu_percent":0,"allow_cpu":true,"allow_gpu":false}','["cpu"]'))
        c.trust_penalty(con,"d",True,"bad_result_1")
        one=dict(con.execute("select trust_score,invalid_jobs,quarantined,enabled from devices where id='d'").fetchone())
        assert one["invalid_jobs"]==1 and one["quarantined"]==0 and one["enabled"]==1,one
        c.trust_penalty(con,"d",True,"bad_result_2")
        two=dict(con.execute("select trust_score,invalid_jobs,quarantined,enabled from devices where id='d'").fetchone())
        assert two["invalid_jobs"]==2 and two["quarantined"]==1 and two["enabled"]==0,two
        print({"after_first":one,"after_second":two})
        con.close()

if __name__ == "__main__":
    main()
