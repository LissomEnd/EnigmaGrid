"""Isolated HTTP test for bounded assignment admission and intake independence."""
import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
import coordinator as c

def main():
    with tempfile.TemporaryDirectory(prefix='grid-allocation-gate-') as directory:
        c.DATA=Path(directory);c.DB=c.DATA/'grid.sqlite3';c.CFG=c.DATA/'server.json'
        cfg=json.loads((ROOT/'config/server.example.json').read_text(encoding='utf-8'))
        cfg.update(registration_open=False,batch_leases_enabled=True,long_work_blocks_enabled=True,
                   rate_limit_per_minute=1000,
                   compute_rate_limit_per_minute=1000,global_rate_per_minute=10000)
        c.CFG.write_text(json.dumps(cfg),encoding='utf-8')
        c.init_db()
        db=c.db()
        db.execute("INSERT INTO contributors(id,display_name,join_key_hash,dashboard_token_hash,created) VALUES('owner','test','j','d',?)",(time.time(),))
        devices=[f'dev-{i}' for i in range(5)]
        for device in devices:
            db.execute("""INSERT INTO devices(id,contributor_id,label,token_hash,created,meta_json,
                       capabilities_json,settings_json) VALUES(?,'owner','test',?,?,?,?,'{}')""",
                       (device,c.sha(device+'-token'),time.time(),json.dumps({'worker_version':'0.5.0'}),'["cpu"]'))
        db.close()
        server=c.ThreadingHTTPServer(('127.0.0.1',0),c.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def request(path,device,body=None):
            payload=json.dumps(body or {}).encode()
            req=urllib.request.Request(base+path,data=payload,headers={
                'Content-Type':'application/json','X-Device-Token':device+'-token'})
            try:
                with urllib.request.urlopen(req,timeout=8) as response:
                    return response.status,json.loads(response.read()),response.headers.get('Retry-After')
            except urllib.error.HTTPError as error:
                return error.code,json.loads(error.read()),error.headers.get('Retry-After')
        original_batch=c.allocate_batch
        original_receive=c.work_blocks.receive_groups
        release=threading.Event();four_entered=threading.Event();gate_lock=threading.Lock();started=[];out=[]
        def slow_batch(con,device_id,count,max_new=None):
            with gate_lock:
                started.append(device_id)
                if len(started)==4:four_entered.set()
            if not release.wait(7):raise TimeoutError('fixture wait expired')
            return {'enabled':True,'leases':[]}
        c.allocate_batch=slow_batch
        try:
            workers=[]
            for device in devices[:4]:
                worker=threading.Thread(target=lambda d=device:out.append(request('/api/leases',d,{'count':1,'max_new':1})))
                worker.start();workers.append(worker)
            assert four_entered.wait(5),(started,out)
            assert len(c.ALLOCATION_ACTIVE)==4
            same=request('/api/leases',devices[0],{'count':1,'max_new':1})
            assert same==(429,{'error':'allocation_busy','retry_after_seconds':1},'1'),same
            assert request('/api/lease',devices[0])[0]==429
            assert request('/api/work-blocks',devices[0],{'format':c.work_blocks.FORMAT,'request_id':'retry'})[0]==429
            fifth=request('/api/leases',devices[4],{'count':1,'max_new':1})
            assert fifth[0]==429 and fifth[2]=='1',fifth
            # Intake and control use no assignment slot, even while all four
            # allocator threads are blocked outside SQLite writer transactions.
            c.work_blocks.receive_groups=lambda *args,**kwargs:{'results':[{'status':'duplicate'}]}
            assert request('/api/work-blocks/result-groups',devices[4],
                           {'groups':[[{'unit':0}]]})[0]==200
            assert request('/api/heartbeat',devices[4])[0]==200
            assert request('/api/device/settings',devices[4],{'settings':{'cpu_percent':50}})[0]==200
            assert request('/api/leases','invalid',{'count':1,'max_new':1})[0]==403
            release.set()
            for worker in workers:worker.join(5);assert not worker.is_alive()
            assert len(out)==4 and all(code==200 for code,_,_ in out),out
            assert c.ALLOCATION_ACTIVE==set(),c.ALLOCATION_ACTIVE
            def fail_batch(*args,**kwargs):raise ValueError('isolated fixture failure')
            c.allocate_batch=fail_batch
            assert request('/api/leases',devices[0],{'count':1,'max_new':1})[0]==400
            assert c.ALLOCATION_ACTIVE==set(),c.ALLOCATION_ACTIVE
            c.allocate_batch=lambda *args,**kwargs:{'enabled':True,'leases':[]}
            assert request('/api/leases',devices[0],{'count':1,'max_new':1})[0]==200
            assert c.ALLOCATION_ACTIVE==set(),c.ALLOCATION_ACTIVE
            print('PASS assignment 4-global/1-device, retry header, independent intake/control, auth and exception cleanup')
        finally:
            release.set();c.allocate_batch=original_batch;c.work_blocks.receive_groups=original_receive
            server.shutdown();server.server_close();thread.join(5)

if __name__=='__main__':main()
