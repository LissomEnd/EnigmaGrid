"""Sacrificial Windows monitor sampler and bounded coordinator telemetry sender.

Neither thread participates in work allocation, receipt persistence or upload.
Unsupported sensors are absent from wire buckets rather than reported as zero.
"""
from collections import deque
import json
import math
import secrets
import threading
import time


class DeviceTelemetry:
    def __init__(self,runtime,sample,publish,capabilities,post,version,*,close_sample=None):
        self.runtime=runtime;self.sample=sample;self.publish=publish
        self.capabilities=capabilities;self.post=post;self.version=version
        self.close_sample=close_sample
        self.session_id=secrets.token_hex(12);self.seq=0
        self.stop_event=threading.Event();self.wake=threading.Event()
        self.lock=threading.Lock();self.ready=deque(maxlen=12)
        self.current=None;self.last_totals={};self.next_probe=0;self.supported=False
        self.clock_anchor=None
        self.sampler=threading.Thread(target=self._sample_loop,name='device-telemetry-sample')
        self.sender=threading.Thread(target=self._send_loop,name='device-telemetry-send')

    def start(self):
        self.sampler.start();self.sender.start();self.wake.set()

    def close(self):
        self.stop_event.set();self.wake.set()
        # The sender has bounded 5-second HTTP calls; the sampler may be in
        # a native sensor API. Releasing NVML/PDH before it exits is unsafe.
        for thread,seconds in ((self.sampler,8),(self.sender,12)):
            if thread.ident is not None:
                thread.join(timeout=seconds)
                if thread.is_alive():
                    raise RuntimeError(thread.name+' did not terminate')
        if self.close_sample is not None:self.close_sample()

    @staticmethod
    def _number(value,minimum=0,maximum=None):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):return None
        if value<minimum or maximum is not None and value>maximum:return None
        return float(value)

    def _epoch_ms(self):
        anchor=self.clock_anchor
        if anchor is None:return int(time.time()*1000)
        return anchor[0]+max(0,int((time.monotonic()-anchor[1])*1000))

    def _snapshot(self):
        lock=self.runtime.setdefault('_metrics_lock',threading.RLock())
        with lock:
            throughput=dict(self.runtime.get('throughput') or {})
            pipeline=self.runtime.get('_block_pipeline')
            engine=self.runtime.get('active_engine')
            backend=(self.runtime.get('bounded_backend','CPU') if engine=='bounded_crib_v1'
                     else self.runtime.get('resource','CPU'))
            block_metrics=pipeline is not None and engine=='bounded_crib_v1'
            block_counter=self.runtime.get('_bounded_ack_counter')
            block_acks=block_counter.value() if block_counter is not None else None
            data=dict(status=self.runtime.get('status','starting'),backend=backend,
                      ready_jobs=self.runtime.get('ready_units'),
                      pending_receipts=self.runtime.get('outbox_count'),
                      wait_reason=self.runtime.get('wait_reason',''),
                      completed_jobs=throughput.get('completed_jobs'),
                      completed_units=throughput.get('completed_units'),
                      compute_seconds=throughput.get('compute_seconds'),
                      persist_seconds=self.runtime.get('persistence_seconds'),
                      upload_seconds=(getattr(pipeline,'upload_seconds',None) if block_metrics
                                      else self.runtime.get('_legacy_upload_seconds')),
                      lease_seconds=(getattr(pipeline,'lease_seconds',None) if block_metrics
                                     else self.runtime.get('_legacy_lease_seconds')),
                      # A block pipeline may replace or coexist with the
                      # legacy uploader. Never compare their independent
                      # cumulative clocks as one counter.
                      network_counter_origin=('block:%d'%id(pipeline) if block_metrics
                                              else 'legacy'),
                      receipts_acked=self.runtime.get('_legacy_receipts_acked'),
                      block_receipts_acked=block_acks if block_acks else None)
        return data

    def _add_sample(self,telemetry,monitor):
        epoch_ms=self._epoch_ms();start=epoch_ms//5000*5000
        with self.lock:
            if self.current is None or self.current['start_ms']!=start:
                if self.current is not None:
                    meta={key:self.current.get(key) for key in
                          ('backend','cpu_scope','gpu_scope','cpu_provider','gpu_provider')}
                    self.ready.append((self._finish(self.current),meta))
                self.current={'start_ms':start,'duration_ms':5000,'samples':0,'values':{},'counts':{}}
                if len(self.ready)>=6:self.wake.set()
            bucket=self.current;bucket['samples']=min(5,bucket['samples']+1)
            for wire,source,maximum in (('cpu_percent','cpu_percent',100),
                                        ('gpu_percent','gpu_percent',100),
                                        ('cpu_temp_c','cpu_temp_c',150),
                                        ('gpu_temp_c','gpu_temp_c',150)):
                value=self._number(telemetry.get(source),-30 if 'temp' in wire else 0,maximum)
                if value is not None:bucket['values'].setdefault(wire,[]).append(value)
            for wire,source,multiplier in (('jobs_done','completed_jobs',1),
                                           ('units_done','completed_units',1),
                                           ('compute_ms','compute_seconds',1000),
                                           ('persist_ms','persist_seconds',1000),
                                           ('upload_ms','upload_seconds',1000),
                                           ('lease_ms','lease_seconds',1000),
                                           ('receipts_acked','receipts_acked',1),
                                           ('receipts_acked','block_receipts_acked',1)):
                value=self._number(monitor.get(source))
                if value is None:continue
                baseline_key=((source,monitor.get('network_counter_origin','legacy'))
                              if source in ('upload_seconds','lease_seconds') else source)
                prior=self.last_totals.get(baseline_key)
                self.last_totals[baseline_key]=value
                if source in ('upload_seconds','lease_seconds','receipts_acked','block_receipts_acked'):
                    # These counters begin at zero in this worker session but
                    # are absent until the first actual HTTP attempt or ACK.
                    # Preserve its first positive delta without fabricating
                    # zero-valued network activity before an event.
                    baseline=0 if prior is None or value<prior else prior
                    if value>baseline:
                        bucket['counts'][wire]=bucket['counts'].get(wire,0)+int(round((value-baseline)*multiplier))
                    continue
                if prior is not None and value>=prior:
                    bucket['counts'][wire]=bucket['counts'].get(wire,0)+int(round((value-prior)*multiplier))
            for wire,source in (('ready_jobs','ready_jobs'),('pending_receipts','pending_receipts')):
                value=self._number(monitor.get(source))
                if value is not None:bucket[wire]=int(value)
            memory=self._number(telemetry.get('memory_bytes'))
            if memory is not None:bucket['memory_bytes']=int(memory)
            reason=monitor.get('wait_reason') or ('paused' if monitor.get('status')=='paused' else '')
            if isinstance(reason,str):bucket['wait_reason']=''.join(c for c in reason if 32<=ord(c)<=126)[:48]
            bucket['cpu_scope']='process' if telemetry.get('cpu_percent') is not None else 'unknown'
            bucket['gpu_scope']=telemetry.get('gpu_metric_scope','unknown')
            bucket['cpu_provider']=telemetry.get('cpu_util_provider','')
            bucket['gpu_provider']=telemetry.get('gpu_util_provider','')
            bucket['backend']=''.join(c for c in str(monitor.get('backend') or 'CPU') if 32<=ord(c)<=126)[:64]

    @staticmethod
    def _finish(bucket):
        result={key:bucket[key] for key in ('start_ms','duration_ms','samples')}
        for key,values in bucket['values'].items():
            if values:result[key]=round(sum(values)/len(values),2)
        result.update(bucket['counts'])
        for key in ('ready_jobs','pending_receipts','memory_bytes','wait_reason'):
            if key in bucket:result[key]=bucket[key]
        return result

    def _sample_loop(self):
        next_at=time.monotonic()
        while not self.stop_event.is_set():
            try:
                sample=self.sample()
                if not isinstance(sample,dict):sample={}
                sample['time']=time.time()
                with self.runtime.setdefault('_metrics_lock',threading.RLock()):
                    self.runtime['telemetry']=sample
                    self.runtime['_telemetry_at']=time.monotonic()
                self.publish(self.runtime)
                self._add_sample(sample,self._snapshot())
            except Exception:
                # Monitoring failure must not stop work or forge zeros.
                pass
            next_at+=1
            self.stop_event.wait(max(0,min(1,next_at-time.monotonic())))
            if next_at<time.monotonic()-1:next_at=time.monotonic()

    def _send_loop(self):
        pending=None;attempts=0
        while not self.stop_event.is_set():
            self.wake.wait(30);self.wake.clear()
            if self.stop_event.is_set():break
            now=time.monotonic()
            if now>=self.next_probe:
                try:
                    capabilities=self.capabilities()
                    self.supported=capabilities.get('device_telemetry')=='device_telemetry_v1'
                    server_ms=capabilities.get('server_time_ms')
                    received=time.monotonic()
                    if type(server_ms) is int and 1_000_000_000_000<=server_ms<=4_000_000_000_000:
                        with self.lock:
                            if self.clock_anchor is None:
                                # Discard any samples made with an untrusted local wall clock.
                                self.ready.clear();self.current=None;self.last_totals.clear()
                                self.clock_anchor=(server_ms,received)
                            else:
                                prior=self.clock_anchor[0]+int((received-self.clock_anchor[1])*1000)
                                if abs(prior-server_ms)>1000:
                                    # Drop buckets stamped with the stale clock, but keep
                                    # cumulative baselines: clearing them would replay every
                                    # previously counted ACK and network duration.
                                    self.ready.clear();self.current=None
                                    self.clock_anchor=(server_ms,received)
                except Exception:self.supported=False
                self.next_probe=now+300
            if not self.supported:continue
            if self.stop_event.is_set():break
            if pending is None:
                with self.lock:
                    if not self.ready:continue
                    first,scope=self.ready.popleft();buckets=[first]
                    while self.ready and len(buckets)<6 and self.ready[0][1]==scope:
                        buckets.append(self.ready.popleft()[0])
                self.seq+=1
                pending=dict(format='device_telemetry_v1',session_id=self.session_id,seq=self.seq,
                             worker_version=self.version,backend=scope.get('backend','CPU'),
                             cpu_scope=scope.get('cpu_scope','unknown'),gpu_scope=scope.get('gpu_scope','unknown'),
                             buckets=buckets)
                for key in ('cpu_provider','gpu_provider'):
                    value=scope.get(key)
                    if value:pending[key]=''.join(c for c in str(value) if 32<=ord(c)<=126)[:64]
                while len(json.dumps(pending,separators=(',',':')).encode('utf-8'))>8192 and len(buckets)>1:
                    buckets.pop()
                if len(json.dumps(pending,separators=(',',':')).encode('utf-8'))>8192:
                    pending=None
                    continue
                attempts=0
            try:
                if self.stop_event.is_set():break
                reply=self.post(pending)
                if (not isinstance(reply,dict) or reply.get('ok') is not True or
                    type(reply.get('accepted')) is not int or reply['accepted']!=len(pending['buckets'])):
                    raise ValueError('Telemetry not acknowledged')
                pending=None;attempts=0
            except Exception:
                attempts+=1
                if attempts>=2:
                    # These samples are disposable; receipts never enter this queue.
                    pending=None;attempts=0
