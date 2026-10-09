"""Durable ACK, scientific drain and crash recovery on an isolated database."""
import json
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
import coordinator as c
from search.work_block import unit_envelope
from search.crib_work import run

with tempfile.TemporaryDirectory() as folder:
    c.DATA=Path(folder)
    c.DB=c.DATA/'grid.sqlite3'
    c.CFG=c.DATA/'config.json'
    cfg=json.loads((ROOT/'config/server.example.json').read_text(encoding='utf-8'))
    cfg.update(long_work_blocks_enabled=True,trusted_sampling_enabled=False,min_worker_version='0.1.0',
               rate_limit_per_minute=1000,compute_rate_limit_per_minute=1000)
    c.CFG.write_text(json.dumps(cfg),encoding='utf-8')
    c.init_db()
    con=c.db()
    stamp=time.time()
    con.execute("INSERT INTO contributors(id,display_name,join_key_hash,dashboard_token_hash,created) VALUES('owner','test','j','d',?)",(stamp,))
    con.execute("""INSERT INTO devices(id,contributor_id,label,token_hash,created,meta_json,
        capabilities_json,settings_json) VALUES('a','owner','test',?,? ,?,
        '[\"cpu\",\"bounded_crib_v1\"]','{\"cpu_percent\":100,\"allow_cpu\":true}')""",
        (c.sha('atoken'),stamp,json.dumps({'worker_version':'0.4.61','supported_engines':['bounded_crib_v1']})))
    con.execute("INSERT INTO campaigns(id,name,version,status,created) VALUES('c','test','1','running',?)",(stamp,))
    config=dict(requires=['cpu','bounded_crib_v1'],program=dict(ciphertext='BDZGO',
        hypotheses=[dict(text='BD',legal_clean_offsets=[0])],chunk=3,ordinal_base=0,candidate_limit=3))
    con.execute("""INSERT INTO segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,
        chunk_size,priority,config_json) VALUES('s','c','test','bounded_crib_v1',0,100000,0,1,10,?)""",
        (json.dumps(config),))
    block=c.work_blocks.reserve(con,'a','one',observed_rate=10,timestamp=time.time(),
                                eligible=lambda d,s:True)['block']
    def packet(start,count):
        rows=[dict(unit=n,compute_seconds=.05,result=run(unit_envelope(block,n)))
              for n in range(start,start+count)]
        return dict(format=c.work_result_groups.FORMAT,block_id=block['block_id'],
                    groups=[rows[i:i+8] for i in range(0,len(rows),8)])

    server=c.ThreadingHTTPServer(('127.0.0.1',0),c.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    def post(body):
        request=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+
            '/api/work-blocks/result-groups',data=json.dumps(body).encode(),
            headers={'Content-Type':'application/json','X-Device-Token':'atoken'})
        with urllib.request.urlopen(request,timeout=5) as response:
            return response.status,json.load(response)
    try:
        first=packet(0,4)
        status,ack=post(first)
        assert status==200 and len(ack['results'])==4
        assert con.execute('SELECT count(*) FROM block_receipts').fetchone()[0]==4
        assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==0
        assert con.execute("SELECT unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone()[0]==4
        diagnostics=c.work_blocks.promotion_metrics(con,timestamp=time.time())
        assert diagnostics['durable_unpromoted_units']==4
        assert diagnostics['oldest_pending_age_seconds'] is not None
        assert diagnostics['top_devices'][0]['unpromoted_units']==4
        assert post(first)==(status,ack)
        # A restarted worker reconstructs work from the durable receipt index.
        con.close();con=c.db()
        stop=threading.Event()
        promoter=threading.Thread(target=c.promotion_worker,args=(stop,),daemon=True)
        promoter.start()
        deadline=time.monotonic()+5
        while con.execute('SELECT count(*) FROM submissions').fetchone()[0]!=4 and time.monotonic()<deadline:
            time.sleep(.02)
        stop.set();c.PROMOTION_WAKE.set();promoter.join(5)
        assert not promoter.is_alive()
        assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==4
        assert con.execute('SELECT count(*) FROM validations WHERE status=\'pending\'').fetchone()[0]==4
        assert con.execute("SELECT unpromoted_units FROM device_work_exposure WHERE device_id='a'").fetchone()[0]==0
        assert c.work_blocks.promotion_metrics(con,timestamp=time.time())['oldest_pending_age_seconds'] is None
        assert c.promote_pending_once(con,object.__new__(c.Handler)) is None
        assert post(first)==(status,ack)
        assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==4

        # While candidate replay runs outside the writer, a second durable
        # packet remains independently acknowledgeable and recoverable.
        second=packet(4,2)
        assert post(second)[0]==200
        entered=threading.Event();resume=threading.Event()
        original=c.Handler._prepare_completion
        def held(self,connection,device,body):
            entered.set();assert not connection.in_transaction
            assert resume.wait(5)
            return original(self,connection,device,body)
        c.Handler._prepare_completion=held
        error=[]
        def drain():
            connection=c.db()
            try:c.promote_pending_once(connection,object.__new__(c.Handler))
            except BaseException as exc:error.append(exc)
            finally:connection.close()
        drain_thread=threading.Thread(target=drain);drain_thread.start()
        assert entered.wait(5)
        third=packet(6,1)
        assert post(third)[0]==200
        assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==4
        resume.set();drain_thread.join(10)
        c.Handler._prepare_completion=original
        assert not error,error
        assert c.promote_pending_once(con,object.__new__(c.Handler))==block['block_id']
        assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==7
        assert con.execute('SELECT count(*) FROM block_receipts WHERE promoted_at IS NULL').fetchone()[0]==0

        # A verifier rejection is retained as rejected evidence, without
        # credit or an infinite retry loop; later durable rows can progress.
        fourth=packet(7,2)
        assert post(fourth)[0]==200
        con.execute("UPDATE devices SET trust_score=0.6 WHERE id='a'")
        once={'n':0}
        def reject_first(self,connection,device,body):
            item=original(self,connection,device,body)
            once['n']+=1
            if once['n']==1:return item[0],None,None,'injected scientific rejection'
            return item
        c.Handler._prepare_completion=reject_first
        try:
            try:c.promote_pending_once(con,object.__new__(c.Handler))
            except c.PromotionFailure:pass
            else:raise AssertionError('Verifier rejection hidden')
        finally:c.Handler._prepare_completion=original
        assert con.execute("SELECT verification_status FROM block_receipts WHERE unit=7").fetchone()[0]=='rejected'
        assert con.execute('SELECT count(*) FROM submissions WHERE start_unit=7').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==7
        # Device quarantine is a genuine scientific penalty, not a failed ACK.
        assert con.execute("SELECT quarantined FROM devices WHERE id='a'").fetchone()[0]==1
        # An already durable receipt remains scientifically eligible after
        # its block reservation expires; a new late receipt would be rejected.
        con.execute("UPDATE devices SET quarantined=0,enabled=1 WHERE id='a'")
        con.execute('UPDATE work_blocks SET expires_at=? WHERE id=?',(time.time()-1,block['block_id']))
        state=c.work_blocks.status(con,'a',[block['block_id']],timestamp=time.time())
        assert state['blocks'][0]['status']=='expired'
        assert c.promote_pending_once(con,object.__new__(c.Handler))==block['block_id']
        assert con.execute('SELECT count(*) FROM submissions WHERE start_unit=8').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM submissions WHERE start_unit=7').fetchone()[0]==0
    finally:
        server.shutdown();server.server_close();thread.join(5);con.close()
print('PASS durable ACK, duplicate replay, restart drain, concurrent intake and scientific rejection isolation')
