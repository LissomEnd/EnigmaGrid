"""Durable local subdivision: no network call is needed to select a unit.

The caller supplies the existing encrypted atomic state store. Cursor advancement
and receipt persistence share one write, so restart cannot skip an unsaved result.
"""
import copy
import json
import threading
import time
import uuid
from pathlib import Path
from search.work_block import validate_block, unit_envelope, validate_partial_results, FORMAT, MAX_BODY_BYTES

MAX_PENDING=8
MAX_BYTES=8*1024*1024
# Default JSON spacing can expand the compact protocol receipt. Leave room for
# that expansion, the queue wrapper and cursor growth before starting compute.
RESULT_RESERVE=2*MAX_BODY_BYTES+4096

class QueueCapacityError(ValueError):
    """Retry after upload frees space; retain the allocation request for replay."""

class BlockQueue:
    def __init__(self,path,owner,load,save,*,grouped=False):
        self.max_pending=64 if grouped else MAX_PENDING
        self.path=Path(path);self.owner={k:owner[k] for k in ('server','device_id')}
        self.load=load;self.save=save;self.lock=threading.RLock()
        self.reserved_bytes=0
        self.computing_block=None
        self.claims=set()
        self.confirmed={}
        self.persistence_seconds=0.0
        self.cached_value=None;self.cached_stamp=None

    def _stamp(self):
        try:
            s=self.path.stat()
            return (s.st_mtime_ns,s.st_size,s.st_ino)
        except FileNotFoundError:return None

    def _read(self,*,copy_value=True):
        value=self._read_stored(copy_value=copy_value)
        if self.confirmed:
            # Never mutate the durable-state cache before a successful save.
            value=copy.deepcopy(value)
            value['pending']=[r for r in value['pending']
                if r!=self.confirmed.get((r['block_id'],r['unit']))]
        return value

    def _read_stored(self,*,copy_value=True):
        stamp=self._stamp()
        if self.cached_value is not None and stamp==self.cached_stamp:
            return copy.deepcopy(self.cached_value) if copy_value else self.cached_value
        value=self.load(self.path)
        if value is None:return dict(owner=self.owner,blocks=[],pending=[],version=1)
        if value.get('owner')!=self.owner or value.get('version') not in (1,2):
            raise ValueError('Block queue belongs to another account or format')
        if self._stamp()==stamp:
            self.cached_stamp=stamp;self.cached_value=copy.deepcopy(value)
        return copy.deepcopy(value) if copy_value else value

    def _write(self,value,*,completion=False,completions=0):
        # Old clients fail closed while a gap exists, instead of recomputing
        # already acknowledged out-of-order units. Closing gaps restores v1.
        value['version']=2 if any(x.get('completed_ahead') for x in value['blocks']) else 1
        reserve=max(0,self.reserved_bytes-RESULT_RESERVE*(completions+int(completion)))
        if len(value['pending'])>64 or len(json.dumps(value,allow_nan=False).encode())+reserve>MAX_BYTES:
            raise QueueCapacityError('Block result storage is full')
        began=time.monotonic()
        try:self.save(self.path,value)
        except BaseException:
            # A failed atomic write may still have replaced the file.
            self.cached_value=None;self.cached_stamp=None
            raise
        finally:self.persistence_seconds+=time.monotonic()-began
        # The worker mutex and queue lock give this store one writer. Cache only
        # after the atomic durable save succeeds, never before it. File identity
        # checks still detect replacement by recovery or another queue instance.
        self.cached_stamp=self._stamp();self.cached_value=copy.deepcopy(value)
        self.confirmed.clear()

    def allocation_request(self):
        with self.lock:
            value=self._read()
            if not value.get('allocation_request'):
                value['allocation_request']=uuid.uuid4().hex;self._write(value)
            return value['allocation_request']

    def allocation_received(self,request_id,block):
        with self.lock:
            if self._read().get('allocation_request')!=request_id:
                raise ValueError('Unexpected allocation response')
            self.add(block)
            value=self._read();value.pop('allocation_request',None);self._write(value)

    def allocation_retired(self,request_id,block):
        """Forget a terminal replay only after preserving any local receipts."""
        validate_block(block)
        with self.lock:
            value=self._read()
            if value.get('allocation_request')!=request_id:
                raise ValueError('Unexpected allocation response')
            for item in value['blocks']:
                if item['block']['block_id']==block['block_id']:
                    if item['block']!=block:raise ValueError('Conflicting replayed block')
                    item['retiring']=True
            value.pop('allocation_request',None)
            self._write(value)

    def add(self,block):
        validate_block(block)
        with self.lock:
            value=self._read()
            for item in value['blocks']:
                if item['block']['block_id']==block['block_id']:
                    if item['block']!=block:raise ValueError('Conflicting replayed block')
                    return
            # Keep completed descriptors while their receipts await acknowledgement.
            pending_ids={x['block_id'] for x in value['pending']}
            value['blocks']=[x for x in value['blocks'] if x['next']<x['block']['end_unit'] or x['block']['block_id'] in pending_ids]
            if sum(x['next']<x['block']['end_unit'] for x in value['blocks'])>=2:
                raise QueueCapacityError('Current and next blocks already reserved')
            value['blocks'].append(dict(block=copy.deepcopy(block),next=block['start_unit']))
            self._write(value)

    def qualification_sample(self):
        """Read-only sample; qualification never advances or claims grid work."""
        with self.lock:
            if self.computing_block is not None or self.claims:return []
            for item in self._read(copy_value=False)['blocks']:
                if item.get('retiring') or time.time()+120>=item.get('expires_local',float('inf')):continue
                if item['block']['end_unit']-item['next']>=12:
                    return [unit_envelope(item['block'],item['next']+i) for i in range(12)]
            return []

    def next_unit(self):
        with self.lock:
            if self.claims:return None
            value=self._read(copy_value=False)
            if len(value['pending'])>=self.max_pending:return None
            if len(json.dumps(value,allow_nan=False).encode())+RESULT_RESERVE>MAX_BYTES:return None
            for item in value['blocks']:
                if not item.get('retiring') and time.time()<item.get('expires_local',float('inf')) and item['next']<item['block']['end_unit']:
                    self.reserved_bytes=RESULT_RESERVE
                    self.computing_block=item['block']['block_id']
                    return item['block']['block_id'],unit_envelope(item['block'],item['next'])
            return None

    def claim_next(self,lanes):
        return self._claim(lanes,lanes)

    def claim_prefetched(self,lanes):
        # Two reservations per physical lane, not twice as many solver threads.
        return self._claim(lanes,2*lanes)

    def _claim(self,lanes,window):
        if type(lanes) is not int or lanes not in (1,2,4):raise ValueError('Compute lanes must be 1, 2 or 4')
        with self.lock:
            if self.computing_block is not None or len(self.claims)>=window:return None
            value=self._read(copy_value=False)
            if len(value['pending'])+len(self.claims)>=self.max_pending:return None
            if len(json.dumps(value,allow_nan=False).encode())+self.reserved_bytes+RESULT_RESERVE>MAX_BYTES:return None
            for item in value['blocks']:
                identity=item['block']['block_id'];cursor=item['next'];unit=cursor
                if item.get('retiring') or time.time()>=item.get('expires_local',float('inf')):continue
                completed=set(item.get('completed_ahead',[]));end=item['block']['end_unit']
                while unit<end and ((identity,unit) in self.claims or unit in completed):unit+=1
                if unit<end and unit-cursor<self.max_pending:
                    self.claims.add((identity,unit));self.reserved_bytes+=RESULT_RESERVE
                    return identity,unit_envelope(item['block'],unit)
            return None

    def complete(self,block_id,unit,result,compute_seconds):
        self.complete_batch([(block_id,unit,result,compute_seconds)])

    def complete_batch(self,completions):
        """Commit receipts and all associated cursors together or advance none."""
        if not isinstance(completions,(list,tuple)) or not 1<=len(completions)<=4:
            raise ValueError('Completion batch must contain 1 to 4 results')
        with self.lock:
            value=self._read();released=[];legacy=False
            for block_id,unit,result,compute_seconds in completions:
                item=next((x for x in value['blocks'] if x['block']['block_id']==block_id),None)
                claimed=type(unit) is int and (block_id,unit) in self.claims
                if item is None or type(unit) is not int or unit<item['next'] or unit in item.get('completed_ahead',[]) or (unit!=item['next'] and not claimed):
                    raise ValueError('Completion does not match local cursor')
                if len(value['pending'])>=self.max_pending:raise QueueCapacityError('Block result storage is full')
                payload=dict(format=FORMAT,block_id=block_id,receipts=[dict(unit=unit,result=result,compute_seconds=compute_seconds)])
                validate_partial_results(item['block'],payload)
                value['pending'].append(dict(block_id=block_id,**copy.deepcopy(payload['receipts'][0])))
                completed=set(item.get('completed_ahead',[]));completed.add(unit)
                while item['next'] in completed:completed.remove(item['next']);item['next']+=1
                if completed:item['completed_ahead']=sorted(completed)
                else:item.pop('completed_ahead',None)
                if claimed:released.append((block_id,unit))
                elif self.computing_block==block_id:legacy=True
            self._write(value,completions=len(released)+int(legacy))
            for block_id,unit in released:self.release_claim(block_id,unit)
            if legacy:self.release_claim()

    def release_claim(self,block_id=None,unit=None):
        with self.lock:
            if block_id is None:
                if self.claims:raise ValueError('Release concurrent claims by identity')
                self.computing_block=None;self.reserved_bytes=0
            elif (block_id,unit) in self.claims:
                self.claims.remove((block_id,unit));self.reserved_bytes-=RESULT_RESERVE

    def pending(self):
        with self.lock:return copy.deepcopy(self._read(copy_value=False)['pending'])

    def monitor_snapshot(self):
        """Read aggregate counts without copying complete receipt payloads."""
        with self.lock:
            value=self._read(copy_value=False)
            items=[x for x in value['blocks'] if not x.get('retiring') and x['next']<x['block']['end_unit']]
            remaining=sum(x['block']['end_unit']-x['next']-len(x.get('completed_ahead',[])) for x in items)
            running=sum(1 for identity,_ in self.claims if any(x['block']['block_id']==identity for x in items))
            return dict(outbox_count=len(value['pending']),expired_results=len(value.get('expired_receipts',[])),
                        ready_units=max(0,remaining-running),ready_blocks=len(items),
                        persistence_seconds=self.persistence_seconds)

    def archive_expired(self,block_id,units):
        """Retain explicit server expiry separately from the active outbox."""
        if not units:return
        if any(type(x) is not int for x in units):raise ValueError('Invalid expired units')
        with self.lock:
            value=self._read();expired=set(units)
            archive=value.setdefault('expired_receipts',[]);pending=[]
            descriptor=next((x['block'] for x in value['blocks'] if x['block']['block_id']==block_id),None)
            for receipt in value['pending']:
                if receipt['block_id']==block_id and receipt['unit'] in expired:
                    saved=copy.deepcopy(receipt);saved['server_status']='expired'
                    if descriptor is not None:saved['block']=copy.deepcopy(descriptor)
                    archive.append(saved)
                else:pending.append(receipt)
            value['pending']=pending
            for item in value['blocks']:
                if item['block']['block_id']==block_id:item['retiring']=True
            # Archive remains within the encrypted record's byte bound. Never prune.
            self._write(value)

    def acknowledge(self,block_id,units):
        # Only invoke for individually acknowledged units, never on batch HTTP 200.
        if not isinstance(units,list) or any(type(x) is not int for x in units):raise ValueError('Invalid acknowledgements')
        with self.lock:
            value=self._read();accepted=set(units)
            if self.computing_block is not None or self.claims:
                # Persist the removal together with the next completed result.
                # Restart before that write safely replays an accepted receipt.
                for row in value['pending']:
                    if row['block_id']==block_id and row['unit'] in accepted:
                        self.confirmed[(block_id,row['unit'])]=copy.deepcopy(row)
                return
            value['pending']=[x for x in value['pending'] if not(x['block_id']==block_id and x['unit'] in accepted)]
            self._write(value)

    def remaining(self):
        with self.lock:
            items=[x for x in self._read(copy_value=False)['blocks'] if not x.get('retiring') and x['next']<x['block']['end_unit']]
            return sum(x['block']['end_unit']-x['next']-len(x.get('completed_ahead',[])) for x in items),len(items)

    def retire(self):
        # Persist intent before asking the server: a lost release response must
        # never allow these units to be computed again after restart.
        with self.lock:
            value=self._read()
            for item in value['blocks']:item['retiring']=True
            self._write(value)

    def releasable(self):
        with self.lock:
            value=self._read(copy_value=False);pending={x['block_id'] for x in value['pending']}
            return [x['block']['block_id'] for x in value['blocks']
                    if x.get('retiring') and x['block']['block_id'] not in pending
                    and x['block']['block_id']!=self.computing_block
                    and not any(identity==x['block']['block_id'] for identity,_ in self.claims)]

    def released(self,identity):
        with self.lock:
            value=self._read()
            if identity==self.computing_block or any(key==identity for key,_ in self.claims):raise ValueError('Block computation still active')
            if any(x['block_id']==identity for x in value['pending']):raise ValueError('Unsent block results')
            value['blocks']=[x for x in value['blocks'] if x['block']['block_id']!=identity]
            self._write(value)

    def identities(self):
        with self.lock:return [x['block']['block_id'] for x in self._read(copy_value=False)['blocks']]

    def update_status(self,states):
        with self.lock:
            value=self._read()
            for item in value['blocks']:
                status=states.get(item['block']['block_id'])
                # A prefetch can add a block while the status request is in flight.
                # The transport validates completeness against its requested IDs;
                # leave newly added blocks to their own status response.
                if status is None:continue
                item['expires_local']=time.time()+status['valid_for_seconds']
                if status['status']!='reserved':item['retiring']=True
            self._write(value)
