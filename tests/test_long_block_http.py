"""Real HTTP boundary for long blocks; isolated DB and loopback server only."""
import json,sys,tempfile,threading,time,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'server'))
import coordinator as c
from search.work_block import FORMAT,unit_envelope
from search.crib_work import run
with tempfile.TemporaryDirectory() as folder:
    c.DATA=Path(folder);c.DB=c.DATA/'db';c.CFG=c.DATA/'config.json'
    cfg=json.loads((ROOT/'config/server.example.json').read_text(encoding='utf-8'))
    cfg.update(long_work_blocks_enabled=True,min_worker_version='0.1.0',rate_limit_per_minute=1000)
    c.CFG.write_text(json.dumps(cfg),encoding='utf-8');c.init_db();con=c.db()
    con.execute("INSERT INTO contributors(id,display_name,join_key_hash,dashboard_token_hash,created) VALUES('owner','test','j','d',?)",(time.time(),))
    for name in ('a','b'):
        con.execute("INSERT INTO devices(id,contributor_id,label,token_hash,created,meta_json,capabilities_json,settings_json) VALUES(?,'owner','test',?,?,?,'[\"cpu\",\"bounded_crib_v1\"]','{\"cpu_percent\":100,\"allow_cpu\":true}')",(name,c.sha(name+'token'),time.time(),json.dumps({'worker_version':'0.4.37','supported_engines':['bounded_crib_v1']})))
    con.execute("INSERT INTO campaigns(id,name,version,status,created) VALUES('c','test','1','running',?)",(time.time(),))
    config=dict(requires=['cpu','bounded_crib_v1'],program=dict(ciphertext='BDZGO',hypotheses=[dict(text='BD',legal_clean_offsets=[0])],chunk=3,ordinal_base=0,candidate_limit=3))
    con.execute("INSERT INTO segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json) VALUES('s','c','test','bounded_crib_v1',0,100000,8,1,10,?)",(json.dumps(config),))
    for n in range(8):
        con.execute("INSERT INTO submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,contributor_id,fingerprint,result_json,compute_seconds,candidate_count,submitted_at) VALUES(?,?,'s',?,?,'a','owner','f','{}',0.05,0,?)",('sub'+str(n),'lease'+str(n),n,n+1,time.time()))
        con.execute("INSERT INTO sampling_evidence VALUES(?,'a','bounded_crib_v1','0.4.37','match')",('sub'+str(n),))
    server=c.ThreadingHTTPServer(('127.0.0.1',0),c.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    def request(path,body=None,token='atoken'):
        data=None if body is None else json.dumps(body).encode()
        req=urllib.request.Request(base+path,data=data,headers={'Content-Type':'application/json','X-Device-Token':token})
        try:
            with urllib.request.urlopen(req,timeout=5) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def drain_durable_receipts():
        # Grouped HTTP responses acknowledge durable intake. Scientific
        # verification now runs separately and is recovered from the DB.
        for _ in range(32):
            if c.promote_pending_once(con,object.__new__(c.Handler)) is None:return
        raise AssertionError('Scientific promotion did not drain')
    try:
        assert request('/api/capabilities')[1]['long_work_blocks']==FORMAT
        body=dict(format=FORMAT,request_id='one')
        code,assigned=request('/api/work-blocks',body);assert code==200,(code,assigned)
        block=assigned['block'];assert block['end_unit']-block['start_unit']==36000
        assert request('/api/work-blocks',body)[1]['block']==block
        assert request('/api/work-blocks',body,token='bad')[0]==403
        assert request('/api/work-blocks',body,token='btoken')[1]['wait_reason']=='block_calibration_required'
        unit=block['start_unit'];payload=dict(format=FORMAT,block_id=block['block_id'],receipts=[dict(unit=unit,compute_seconds=.05,result=run(unit_envelope(block,unit)))])
        # Simulate process death after durable intake, before verification handoff.
        c.work_blocks.receive_partial(con,'a',payload,timestamp=time.time())
        assert not con.execute('SELECT 1 FROM submissions WHERE segment_id=? AND start_unit=?',('s',unit)).fetchone()
        # The receipt is durable, but the reservation can expire before its
        # handoff to the existing verifier. Internal receipt leases must never
        # be recycled as uncomputed work by the legacy lease sweeper.
        original_complete=c.Handler.complete
        original_prepare=c.Handler._prepare_completion
        def expire_during_promotion(self,connection,device,body):
            connection.execute("UPDATE leases SET expires_at=0 WHERE id=?",(body['lease_id'],))
            c.expire_leases(connection)
            row=connection.execute('SELECT status,purpose FROM leases WHERE id=?',(body['lease_id'],)).fetchone()
            assert tuple(row)==('leased','block_receipt'),tuple(row)
            return original_prepare(self,connection,device,body)
        c.Handler._prepare_completion=expire_during_promotion
        try:
            first=request('/api/work-blocks/results',payload);assert first[0]==200,first
            # Durable acknowledgement is independent of the later verifier.
            drain_durable_receipts()
        finally:c.Handler._prepare_completion=original_prepare
        assert first[1]['results']==[dict(unit=unit,status='received')]
        assert request('/api/work-blocks/results',payload)==first
        assert request('/api/work-blocks/results',payload,token='btoken')[0]==400
        assert con.execute('SELECT count(*) FROM block_receipts').fetchone()[0]==1
        promoted=con.execute('SELECT * FROM submissions WHERE segment_id=? AND start_unit=?',('s',unit)).fetchall()
        assert len(promoted)==1 and promoted[0]['worker_version']=='0.4.37'
        assert promoted[0]['credited']==0
        assert con.execute('SELECT status FROM validations WHERE segment_id=? AND start_unit=?',('s',unit)).fetchone()[0]=='pending'

        # Batch preparation shares one commit; each receipt still enters the
        # original complete/verification path with no writer held during replay.
        batch=dict(format=FORMAT,block_id=block['block_id'],receipts=[
            dict(unit=n,compute_seconds=.05,result=run(unit_envelope(block,n)))
            for n in range(unit+1,unit+9)])
        ack=c.work_blocks.receive_partial(con,'a',batch,timestamp=time.time())
        statements=[];con.set_trace_callback(statements.append)
        handler=object.__new__(c.Handler);checked=[]
        def complete_one(connection,device,result):
            assert not connection.in_transaction,'Replay held SQLite writer'
            checked.append(result['lease_id'])
            return original_complete(handler,connection,device,result,respond=lambda code,value:(code,value))
        try:c.work_blocks.promote_receipts(con,'a',ack,complete_one)
        finally:con.set_trace_callback(None)
        assert len(checked)==8 and len(set(checked))==8
        # The legacy single-receipt fallback needs one final atomic transition
        # from durable intake to promoted scientific submissions.
        assert sum(statement.strip().upper()=='COMMIT' for statement in statements)==10
        c.work_blocks.promote_receipts(con,'a',ack,complete_one)
        assert con.execute("SELECT count(*) FROM submissions WHERE segment_id='s' AND start_unit>? AND start_unit<?",(unit,unit+9)).fetchone()[0]==8
        batch['receipts']=[dict(unit=n,compute_seconds=.05,result=run(unit_envelope(block,n))) for n in range(unit+9,unit+17)]
        ack=c.work_blocks.receive_partial(con,'a',batch,timestamp=time.time());revoked=[]
        def quarantine_after_first(connection,device,result):
            value=complete_one(connection,device,result);revoked.append(result['lease_id'])
            connection.execute("UPDATE devices SET quarantined=1 WHERE id='a'")
            return value
        try:c.work_blocks.promote_receipts(con,'a',ack,quarantine_after_first)
        except ValueError:pass
        else:raise AssertionError('Quarantined contributor promoted subsequent receipts')
        assert len(revoked)==1
        con.execute("UPDATE devices SET quarantined=0 WHERE id='a'")
        c.work_blocks.promote_receipts(con,'a',ack,complete_one)
        assert con.execute("SELECT count(*) FROM submissions WHERE segment_id='s' AND start_unit>=? AND start_unit<?",(unit+9,unit+17)).fetchone()[0]==8

        grouped=dict(format=c.work_result_groups.FORMAT,block_id=block['block_id'],groups=[payload['receipts']])
        assert request('/api/capabilities')[1]['work_result_groups']==c.work_result_groups.FORMAT
        assert request('/api/work-blocks/result-groups',grouped)==first
        assert request('/api/work-blocks/result-groups',grouped,token='btoken')[0]==400
        assert len(con.execute('SELECT * FROM submissions WHERE segment_id=? AND start_unit=?',('s',unit)).fetchall())==1
        assert con.execute('SELECT verification_status FROM block_receipts').fetchone()[0]=='pending'
        sys.path.insert(0,str(ROOT/'worker'))
        from block_queue import BlockQueue
        from block_transport import BlockTransport
        import worker
        queue=BlockQueue(Path(folder)/'client',dict(server=base,device_id='a'),worker.load_state,worker.save_state)
        def send(path,body):
            code,value=request(path,body)
            if code!=200:raise RuntimeError((code,value))
            return value
        transport=BlockTransport(queue,send)
        assigned2=transport.allocate();assert assigned2['block'] is not None
        key,envelope=queue.next_unit();queue.complete(key,envelope['start_unit'],run(envelope),.05)
        def lose_response(path,body):
            send(path,body);raise TimeoutError('response lost')
        try:BlockTransport(queue,lose_response).upload()
        except TimeoutError:pass
        else:raise AssertionError('Expected response loss')
        assert len(queue.pending())==1
        assert transport.upload()==1 and not queue.pending()
        # Calibration can be removed after allocation without losing retry identity.
        assert con.execute('SELECT worker_version FROM work_blocks WHERE id=?',(block['block_id'],)).fetchone()[0]=='0.4.37'
        con.execute("UPDATE devices SET meta_json=? WHERE id='a'",(json.dumps({'worker_version':'0.4.99','supported_engines':['bounded_crib_v1']}),))
        con.execute('DELETE FROM sampling_evidence')
        assert request('/api/work-blocks',body)[1]['block']==block
        assert con.execute('SELECT worker_version FROM work_blocks WHERE id=?',(block['block_id'],)).fetchone()[0]=='0.4.37'
        assert request('/api/work-blocks',dict(format=FORMAT,request_id='uncalibrated'))[1]['wait_reason']=='block_calibration_required'
        queue.retire()
        retiring=queue.releasable()
        assert retiring and queue.next_unit() is None
        try:BlockTransport(queue,lose_response).release_ready()
        except TimeoutError:pass
        else:raise AssertionError('Expected lost release acknowledgement')
        restarted=BlockQueue(Path(folder)/'client',dict(server=base,device_id='a'),worker.load_state,worker.save_state)
        assert restarted.next_unit() is None and restarted.releasable()==retiring
        BlockTransport(restarted,send).release_ready()
        assert not restarted.releasable()
        assert con.execute('SELECT status FROM work_blocks WHERE id=?',(retiring[0],)).fetchone()[0]=='released'
        assert con.execute('SELECT count(*) FROM block_receipts WHERE block_id=?',(retiring[0],)).fetchone()[0]==1
        # Exercise the actual Windows adapter against this HTTP coordinator.
        from unittest.mock import patch
        for n in range(8):
            con.execute("INSERT INTO sampling_evidence VALUES(?,'a','bounded_crib_v1','0.4.37','match')",('sub'+str(n),))
        state=dict(server=base,device_id='a',device_token='atoken')
        runtime=dict(settings=worker.normalize_settings(dict(cpu_percent=100,gpu_percent=0)),enabled=True)
        state_path=Path(folder)/'windows-client.json'
        cfg['long_work_blocks_enabled']=False;c.CFG.write_text(json.dumps(cfg),encoding='utf-8')
        assert worker.long_block_tick(state_path,state,runtime) is False
        assert runtime['_block_capabilities']['long_work_blocks'] is None
        cfg['long_work_blocks_enabled']=True;c.CFG.write_text(json.dumps(cfg),encoding='utf-8')
        assert worker.long_block_tick(state_path,state,runtime) is False  # Cached for 60 seconds.
        runtime['_block_capabilities_at']=0  # Advance only this probe deadline.
        completed=[]
        actual_execute=worker.execute
        def compute(envelope,*args,**kwargs):
            completed.append(envelope['start_unit'])
            result,count=actual_execute(envelope,*args,**kwargs)
            assert result==run(envelope)
            return result,count
        # This HTTP/receipt fixture must not depend on the signing host's heat.
        # Thermal limits and hysteresis have their own controlled tests.
        with patch.object(worker.windows_telemetry.SystemTelemetry,'sample',return_value={'cpu_temp_c':40.0,'gpu_temp_c':40.0}),patch.object(worker,'execute',side_effect=compute),patch.object(worker,'apply_cpu_limit',return_value=1),patch.object(worker,'publish_health'),patch.object(worker,'meta',return_value={'worker_version':'0.4.37','supported_engines':['bounded_crib_v1'],'capabilities':['cpu','bounded_crib_v1']}):
            try:
                deadline=time.monotonic()+10
                while len(completed)<12 and time.monotonic()<deadline:
                    assert worker.long_block_tick(state_path,state,runtime)
                assert len(completed)>=12,(completed,runtime['settings'],runtime['_block_pipeline'].wait_reason,runtime['_block_pipeline'].last_error)
                assert len(set(completed))==len(completed)
                worker.suspend_long_blocks(runtime)
                assert '_block_pipeline' not in runtime
                assert not runtime.get('block_release_error'),runtime
                persisted=BlockQueue(state_path.with_name('work-block-queue.dat'),dict(server=base,device_id='a'),worker.load_state,worker.save_state)
                assert not persisted.pending() and persisted.next_unit() is None
                drain_durable_receipts()
                for ordinal in completed:
                    assert con.execute('SELECT count(*) FROM submissions WHERE device_id=? AND segment_id=? AND start_unit=?',('a','s',ordinal)).fetchone()[0]==1
            finally:worker.suspend_long_blocks(runtime)
        expired_queue=BlockQueue(Path(folder)/'expired-client',dict(server=base,device_id='a'),worker.load_state,worker.save_state)
        expired_queue.add(block,valid_for_seconds=7200)
        con.execute('UPDATE work_blocks SET expires_at=? WHERE id=?',(time.time()-1,block['block_id']))
        expired_transport=BlockTransport(expired_queue,send)
        expired_transport.refresh_status()
        assert expired_queue.next_unit() is None
        assert con.execute('SELECT status FROM work_blocks WHERE id=?',(block['block_id'],)).fetchone()[0]=='expired'
        assert con.execute('SELECT count(*) FROM block_receipts WHERE block_id=?',(block['block_id'],)).fetchone()[0]==17
        assert request('/api/work-blocks/status',dict(format=FORMAT,blocks=[block['block_id']]),token='btoken')[0]==400
        # Lost allocation response followed by downtime beyond reservation TTL.
        # Retry must retire the old request ID, then acquire usable work.
        lost_queue=BlockQueue(Path(folder)/'lost-allocation',dict(server=base,device_id='a'),worker.load_state,worker.save_state)
        old_request=lost_queue.allocation_request()
        lost_reply=send('/api/work-blocks',dict(format=FORMAT,request_id=old_request))
        assert lost_reply['block'] is not None
        con.execute('UPDATE work_blocks SET expires_at=0 WHERE id=?',(lost_reply['block']['block_id'],))
        resumed=BlockTransport(lost_queue,send)
        assert resumed.allocate()['wait_reason']=='previous_block_finished'
        assert lost_queue.next_unit() is None
        # A completed receipt left on disk over server downtime is retained,
        # but explicit expiry must not permanently block future allocations.
        late_queue=BlockQueue(Path(folder)/'late-receipt',dict(server=base,device_id='a'),worker.load_state,worker.save_state)
        late_block=lost_reply['block'];late_queue.add(late_block,valid_for_seconds=7200)
        late_unit=late_block['start_unit']
        late_result=run(unit_envelope(late_block,late_unit))
        late_queue.complete(late_block['block_id'],late_unit,late_result,.1)
        assert BlockTransport(late_queue,send).upload()==0
        assert not late_queue.pending() and not late_queue.identities()
        archived=worker.load_state(late_queue.path)['expired_receipts']
        assert len(archived)==1 and archived[0]['result']==late_result
        assert con.execute('SELECT count(*) FROM block_receipts WHERE block_id=?',(late_block['block_id'],)).fetchone()[0]==0
        assert lost_queue.allocation_request()!=old_request
        assert resumed.allocate()['block'] is not None
        assert lost_queue.next_unit() is not None
        # Real grouped HTTP upload with response loss: durable replay must not
        # duplicate any of the sixteen independently recorded submissions.
        grouped_queue=BlockQueue(lost_queue.path,dict(server=base,device_id='a'),worker.load_state,worker.save_state,grouped=True)
        BlockTransport(grouped_queue,send,grouped=True).refresh_status()
        grouped_units=[]
        for _ in range(16):
            key,envelope=grouped_queue.next_unit();grouped_units.append(envelope['start_unit'])
            grouped_queue.complete(key,envelope['start_unit'],run(envelope),.05)
        try:BlockTransport(grouped_queue,lose_response,grouped=True).upload()
        except TimeoutError:pass
        else:raise AssertionError('Expected grouped response loss')
        assert len(grouped_queue.pending())==16
        assert BlockTransport(grouped_queue,send,grouped=True).upload()==16
        assert not grouped_queue.pending()
        drain_durable_receipts()
        for ordinal in grouped_units:
            assert con.execute('SELECT count(*) FROM submissions WHERE device_id=? AND segment_id=? AND start_unit=?',('a','s',ordinal)).fetchone()[0]==1
        lost_queue.retire();resumed.release_ready()
        # A separate contributor must service available validation before a new
        # primary block. The same owner's second device cannot self-validate.
        assert request('/api/work-blocks',dict(format=FORMAT,request_id='same-owner'),token='btoken')[1]['wait_reason']=='block_calibration_required'
        con.execute("INSERT INTO contributors(id,display_name,join_key_hash,dashboard_token_hash,created) VALUES('independent','test','j2','d2',?)",(time.time(),))
        con.execute("UPDATE devices SET contributor_id='independent' WHERE id='b'")
        reply=request('/api/work-blocks',dict(format=FORMAT,request_id='validation-first'),token='btoken')
        assert reply[0]==200 and reply[1]['block'] is not None,reply
        validation_block=reply[1]['block']
        assert con.execute('SELECT purpose FROM work_blocks WHERE id=?',
                           (validation_block['block_id'],)).fetchone()[0]=='validation'
        released=request('/api/work-blocks/release',
                         dict(format=FORMAT,block_id=validation_block['block_id']),token='btoken')
        assert released[0]==200,released
        cfg['batch_leases_enabled']=True;c.CFG.write_text(json.dumps(cfg),encoding='utf-8')
        assigned=request('/api/leases',dict(count=1),token='btoken')
        assert assigned[0]==200 and len(assigned[1]['leases'])==1,assigned
        leased=con.execute("SELECT purpose FROM leases WHERE device_id='b' AND status='leased'").fetchall()
        assert len(leased)==1 and leased[0]['purpose']=='validation'
        cfg['long_work_blocks_enabled']=False;c.CFG.write_text(json.dumps(cfg),encoding='utf-8')
        assert request('/api/work-blocks',body)[0]==404
        assert request('/api/capabilities')[1]['long_work_blocks'] is None
    finally:server.shutdown();server.server_close();thread.join();con.close()
print('PASS HTTP block allocation, server sizing, authenticated retry, receipt replay, ownership, pending verification and disabled fallback')
