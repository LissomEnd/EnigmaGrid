"""64 real receipts: three commits, crash/retry, revocation and concurrent replay."""
import concurrent.futures,json,sqlite3,sys,tempfile,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'server'))
import coordinator as c
from search.work_block import unit_envelope
from search.crib_work import run

class Connection(sqlite3.Connection):
    commits=0;fail_at=None;fail_after=None
    def commit(self):
        self.commits+=1
        if self.commits==self.fail_at:raise sqlite3.OperationalError('injected commit failure')
        value=super().commit()
        if self.commits==self.fail_after:raise sqlite3.OperationalError("injected lost commit acknowledgement")
        return value

with tempfile.TemporaryDirectory() as folder:
    c.DATA=Path(folder);c.DB=c.DATA/'db';c.CFG=c.DATA/'config.json'
    cfg=json.loads((ROOT/'config/server.example.json').read_text(encoding='utf-8'))
    cfg.update(long_work_blocks_enabled=True,trusted_sampling_enabled=False,min_worker_version='0.1.0')
    c.CFG.write_text(json.dumps(cfg));c.init_db()
    con=sqlite3.connect(c.DB,isolation_level=None,factory=Connection);con.row_factory=sqlite3.Row
    con.execute("INSERT INTO contributors(id,display_name,join_key_hash,dashboard_token_hash,created) VALUES('owner','test','j','d',?)",(time.time(),))
    con.execute("INSERT INTO devices(id,contributor_id,label,token_hash,created,meta_json,capabilities_json,settings_json) VALUES('a','owner','test','t',?,?,'[\"cpu\",\"bounded_crib_v1\"]','{\"cpu_percent\":100,\"allow_cpu\":true}')",(time.time(),json.dumps({'worker_version':'0.4.61','supported_engines':['bounded_crib_v1']})))
    con.execute("INSERT INTO campaigns(id,name,version,status,created) VALUES('c','test','1','running',?)",(time.time(),))
    config=dict(requires=['cpu','bounded_crib_v1'],program=dict(ciphertext='BDZGO',hypotheses=[dict(text='BD',legal_clean_offsets=[0])],chunk=3,ordinal_base=0,candidate_limit=3))
    con.execute("INSERT INTO segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json) VALUES('s','c','test','bounded_crib_v1',0,100000,0,1,10,?)",(json.dumps(config),))
    block=c.work_blocks.reserve(con,'a','one',observed_rate=10,timestamp=time.time(),eligible=lambda d,s:True)['block']
    handler=object.__new__(c.Handler)
    def payload(start,count=64):
        rows=[dict(unit=n,compute_seconds=.05,result=run(unit_envelope(block,n))) for n in range(start,start+count)]
        return dict(format=c.work_result_groups.FORMAT,block_id=block['block_id'],groups=[rows[i:i+8] for i in range(0,count,8)])
    def ingest(connection,packet,h=handler):
        ack=c.work_blocks.receive_groups(connection,'a',packet,timestamp=time.time())
        return c.work_blocks.promote_receipts(connection,'a',ack,None,complete_many=h.complete_many)
    # First packet has a failure at final commit: intake and internal leases
    # survive, while all application changes roll back together.
    first=payload(0);con.commits=0;con.fail_at=3
    try:ingest(con,first)
    except sqlite3.OperationalError:pass
    else:raise AssertionError('Commit failure hidden')
    assert not con.in_transaction
    assert con.execute('SELECT count(*) FROM block_receipts').fetchone()[0]==64
    assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==0
    assert con.execute("SELECT count(*) FROM leases WHERE status='leased'").fetchone()[0]==64
    con.fail_at=None;con.commits=0;ack=ingest(con,first)
    assert con.commits==3,con.commits
    assert len(ack['results'])==64 and all(x['status']=='received' for x in ack['results'])
    assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==64
    assert con.execute('SELECT sum(credited) FROM submissions').fetchone()[0]==0
    assert con.execute("SELECT count(*) FROM validations WHERE status='pending'").fetchone()[0]==64
    con.commits=0;assert ingest(con,first)==ack and con.commits==3
    assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==64
    # Unexpected application error rolls back earlier members, even though
    # candidate validation ran outside the writer for the entire packet.
    second=payload(64);original_apply=c.Handler._apply_completion;original_prepare=c.Handler._prepare_completion
    counts={'prepare':0,'apply':0}
    def checked_prepare(self,connection,device,body):
        assert not connection.in_transaction;counts['prepare']+=1
        return original_prepare(self,connection,device,body)
    def fail_apply(self,connection,*args):
        assert connection.in_transaction;counts['apply']+=1
        if counts['apply']==3:raise RuntimeError('injected application failure')
        return original_apply(self,connection,*args)
    c.Handler._prepare_completion=checked_prepare;c.Handler._apply_completion=fail_apply
    try:
        try:ingest(con,second)
        except RuntimeError:pass
        else:raise AssertionError('Application failure hidden')
    finally:c.Handler._prepare_completion=original_prepare;c.Handler._apply_completion=original_apply
    assert counts==dict(prepare=64,apply=3),counts
    assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==64
    ingest(con,second);assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==128
    # Per-member revocation is honored within the same transaction. Prior
    # receipt and the revocation commit; later durable receipts await recovery.
    third=payload(128);calls=[]
    def revoke(self,connection,*args):
        result=original_apply(self,connection,*args);calls.append(1)
        connection.execute("UPDATE devices SET quarantined=1 WHERE id='a'")
        return result
    c.Handler._apply_completion=revoke
    try:
        try:ingest(con,third)
        except ValueError:pass
        else:raise AssertionError('Revocation ignored')
    finally:c.Handler._apply_completion=original_apply
    assert len(calls)==1 and con.execute('SELECT count(*) FROM submissions').fetchone()[0]==129
    assert con.execute("SELECT quarantined FROM devices WHERE id='a'").fetchone()[0]==1
    con.execute("UPDATE devices SET quarantined=0 WHERE id='a'");ingest(con,third)
    assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==192
    # Two simultaneous copies cannot create duplicate submissions or credit.
    fourth=payload(192)
    def concurrent_copy():
        connection=sqlite3.connect(c.DB,isolation_level=None,timeout=10);connection.row_factory=sqlite3.Row
        try:return ingest(connection,fourth)
        finally:connection.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(concurrent_copy) for _ in range(2)]
        assert futures[0].result()==futures[1].result()
    assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==256
    # Descriptor change between preparation and transaction must not penalize
    # contributors or apply a result to a different scientific scope.
    fifth=payload(256);changed=False
    def change_scope(self,connection,device,body):
        global changed
        result=original_prepare(self,connection,device,body)
        if not changed:
            changed=True;connection.execute("UPDATE segments SET config_json=? WHERE id='s'",(json.dumps(dict(config,changed=True)),))
        return result
    c.Handler._prepare_completion=change_scope
    try:
        try:ingest(con,fifth)
        except ValueError:pass
        else:raise AssertionError('Changed block configuration accepted')
    finally:c.Handler._prepare_completion=original_prepare
    assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==256
    assert con.execute("SELECT invalid_jobs FROM devices WHERE id='a'").fetchone()[0]==0
    con.execute("UPDATE segments SET config_json=? WHERE id='s'",(json.dumps(config),));ingest(con,fifth)
    assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==320
    # Fail either earlier durability boundary, or lose the final commit's
    # acknowledgement. Every retry returns exactly the original unit receipts.
    for start,stage,after in ((512,1,False),(576,2,False),(640,3,True)):
        packet=payload(start);before=con.execute('SELECT count(*) FROM submissions').fetchone()[0]
        con.commits=0;con.fail_at=None if after else stage;con.fail_after=stage if after else None
        try:ingest(con,packet)
        except sqlite3.OperationalError:pass
        else:raise AssertionError('Boundary fault hidden')
        assert not con.in_transaction
        assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==before+(64 if after else 0)
        con.fail_at=None;con.fail_after=None;con.commits=0
        assert len(ingest(con,packet)['results'])==64 and con.commits==3
        assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==before+64
    # Sampling remains sequential inside the group: nine trusted results force
    # an audit, and later members observe that audit immediately. Already
    # allocated receipts stay durable; further issuance respects the 32 bound.
    cfg['trusted_sampling_enabled']=True;c.CFG.write_text(json.dumps(cfg))
    con.execute('BEGIN IMMEDIATE')
    for n in range(100):c.trusted_sampling.record_independent_verification(con,'evidence-'+str(n),'a','bounded_crib_v1','0.4.61',matched=True,independent=True)
    con.commit();original_decide=c.trusted_sampling.decide
    c.trusted_sampling.decide=lambda *args,**kwargs:original_decide(*args,**kwargs,randbelow=lambda n:99)
    try:ingest(con,payload(320))
    finally:c.trusted_sampling.decide=original_decide
    assert con.execute("SELECT count(*) FROM sampling_decisions WHERE action='accepted_trusted'").fetchone()[0]==9
    assert con.execute("SELECT count(*) FROM sampling_decisions WHERE reason='burst_limit'").fetchone()[0]==1
    assert con.execute("SELECT count(*) FROM sampling_decisions WHERE reason='audit_pending'").fetchone()[0]==54
    assert con.execute("SELECT count(*) FROM done_ranges WHERE verification_status='accepted_trusted'").fetchone()[0]==9
    con.execute('BEGIN IMMEDIATE')
    assert c.trusted_sampling.MAX_PENDING_VERIFICATIONS==32
    assert not c.trusted_sampling.issuance_allowed(con,'a','bounded_crib_v1','0.4.61')
    con.commit()
    # A scientific rejection discovered on handoff commits its penalty and
    # earlier accepted intake, but cannot promote subsequent members.
    cfg['trusted_sampling_enabled']=False;c.CFG.write_text(json.dumps(cfg))
    con.execute("UPDATE devices SET trust_score=0.6 WHERE id='a'")
    prepared_count=0
    def reject_third(self,connection,device,body):
        global prepared_count
        value=original_prepare(self,connection,device,body);prepared_count+=1
        if prepared_count==3:return value[0],None,None,'injected scientific rejection'
        return value
    before=con.execute('SELECT count(*) FROM submissions').fetchone()[0]
    c.Handler._prepare_completion=reject_third
    try:
        try:ingest(con,payload(384))
        except ValueError:pass
        else:raise AssertionError('Scientific rejection hidden')
    finally:c.Handler._prepare_completion=original_prepare
    assert con.execute('SELECT count(*) FROM submissions').fetchone()[0]==before+2
    assert tuple(con.execute("SELECT invalid_jobs,quarantined,enabled FROM devices WHERE id='a'").fetchone())==(1,1,0)
    con.close()
print('PASS sequential trusted burst/audit decisions, pending issuance bound and scientific rejection penalty within grouped transaction')
print('PASS 64 receipts / three commits, final commit crash, application rollback, replay, concurrent duplicates, revocation, changed scope and validation outside writer')
