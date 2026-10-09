"""Bounded atomic outbox; encryption is provided by the caller's state store."""
import copy
import json
import threading
from collections import deque
from pathlib import Path

MAX_RESULTS=8
MAX_BYTES=8*1024*1024
RESERVED_BYTES=512*1024
_LOCKS={}
_RESERVATIONS={}
_LOCKS_GUARD=threading.Lock()

class ReceiptOutbox:
    def __init__(self,path,state,load,save):
        self.path=Path(path)
        self.owner={k:state[k] for k in ('server','device_id')}
        self.load,self.save=load,save
        self.confirmed=set()
        # A prefetched lease response can arrive after its receipt was accepted
        # and removed from disk. Retain a bounded in-process tombstone so that
        # the stale replay cannot be computed a second time.
        self.recent_confirmed=deque(maxlen=128)
        with _LOCKS_GUARD:
            key=str(self.path.resolve())
            self.lock=_LOCKS.setdefault(key,threading.RLock())
            self.reserved=_RESERVATIONS.setdefault(key,set())

    def _entries(self):
        saved=self.load(self.path)
        if saved is None:return []
        if not isinstance(saved,dict) or any(saved.get(k)!=v for k,v in self.owner.items()):
            raise RuntimeError('Saved results belong to another coordinator or device; retained locally')
        entries=saved.get('payloads')
        if entries is None and 'payload' in saved:entries=[saved['payload']]
        if not isinstance(entries,list) or len(entries)>MAX_RESULTS:raise RuntimeError('Invalid saved result queue')
        ids=[]
        for entry in entries:
            if not isinstance(entry,dict) or 'lease_id' not in entry or 'work_token' not in entry:raise RuntimeError('Invalid saved result')
            if entry['lease_id'] in ids:raise RuntimeError('Duplicate saved result')
            ids.append(entry['lease_id'])
        return copy.deepcopy(entries)

    def pending(self):
        with self.lock:return [x for x in self._entries() if x['lease_id'] not in self.confirmed]

    def held_count(self):
        """Unacknowledged results and executing jobs still consume local slots."""
        with self.lock:
            return len({x['lease_id'] for x in self.pending()} | self.reserved)

    def computed_ids(self):
        """Snapshot before allocation; an upload may finish during that request."""
        with self.lock:return {x['lease_id'] for x in self._entries()} | self.confirmed | self.reserved | set(self.recent_confirmed)

    def has_capacity(self):
        with self.lock:
            entries=self.pending()
            return len(entries)+len(self.reserved)<MAX_RESULTS and self._size(entries)+(len(self.reserved)+1)*RESERVED_BYTES<=MAX_BYTES

    def reserve(self,lease_id):
        """Reserve bounded output storage before starting a computation."""
        with self.lock:
            if not isinstance(lease_id,str) or not lease_id:raise RuntimeError('Invalid reservation')
            if lease_id in self.reserved or lease_id in self.recent_confirmed or any(x['lease_id']==lease_id for x in self._entries()):return False
            if not self.has_capacity():return False
            self.reserved.add(lease_id)
            return True

    def release_reservation(self,lease_id):
        with self.lock:self.reserved.discard(lease_id)

    def _size(self,entries):
        return len(json.dumps({**self.owner,'outbox_version':2,'payloads':entries},separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8'))

    def _persist(self,entries):
        value={**self.owner,'outbox_version':2,'payloads':entries}
        outstanding=self.reserved-{x['lease_id'] for x in entries}
        if len(entries)+len(outstanding)>MAX_RESULTS:raise RuntimeError('Result queue is full')
        if self._size(entries)+len(outstanding)*RESERVED_BYTES>MAX_BYTES:
            raise RuntimeError('Result queue byte limit reached')
        self.save(self.path,value)
        self.reserved.intersection_update(outstanding)
        self.confirmed.intersection_update(x['lease_id'] for x in entries)

    def append(self,payload):
        with self.lock:
            if not isinstance(payload,dict) or 'lease_id' not in payload or 'work_token' not in payload:raise RuntimeError('Invalid result')
            if payload['lease_id'] in self.reserved and len(json.dumps(payload,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8'))>RESERVED_BYTES:
                raise RuntimeError('Receipt exceeds reserved capacity')
            entries=self.pending()
            for old in entries:
                if old['lease_id']==payload['lease_id']:
                    if old!=payload:raise RuntimeError('Conflicting result for lease')
                    self.reserved.discard(payload['lease_id'])
                    return
            if len(entries)>=MAX_RESULTS:raise RuntimeError('Result queue is full')
            self._persist(entries+[copy.deepcopy(payload)])

    def acknowledge(self,lease_id):
        with self.lock:
            entries=self._entries()
            remaining=[x for x in entries if x['lease_id']!=lease_id]
            if len(entries)==len(remaining):return False
            self.recent_confirmed.append(lease_id)
            if remaining:self._persist(remaining)
            else:self.path.unlink()
            return True

    def confirm(self,lease_id):
        with self.lock:
            if lease_id not in self.confirmed and any(x['lease_id']==lease_id for x in self._entries()):
                self.confirmed.add(lease_id)
                self.recent_confirmed.append(lease_id)
                return True
            return False

    def flush_confirmed(self):
        with self.lock:
            if not self.confirmed:return
            remaining=self.pending()
            if remaining:self._persist(remaining)
            else:
                self.path.unlink()
                self.confirmed.clear()


class OutboxUploader:
    """One independent sender; shutdown leaves every unacknowledged item on disk."""
    def __init__(self,queue,send,send_batch=None,on_ack=None):
        self.queue,self.send=queue,send
        self.send_batch=send_batch
        self.on_ack=on_ack
        self.stop=threading.Event();self.wake=threading.Event()
        self.last_error=None;self.terminal=False
        self.thread=threading.Thread(target=self._run,name='enigmagrid-uploader',daemon=True)
        self.thread.start()

    def notify(self):self.wake.set()

    def _run(self):
        while not self.stop.is_set():
            try:
                items=self.queue.pending()
                if not items:
                    self.queue.flush_confirmed()
                    self.wake.wait(1);self.wake.clear();continue
                if self.send_batch is not None:
                    acknowledgements=self.send_batch(items)
                    failed=False;confirmed=[]
                    for lease_id,ack in acknowledgements:
                        if isinstance(ack,dict) and ack.get('ok') is True:
                            if self.queue.confirm(lease_id):confirmed.append((lease_id,ack))
                        else:
                            failed=True
                            if isinstance(ack,dict) and ack.get('status') in (401,403,422):self.terminal=True
                    if confirmed:
                        self.queue.flush_confirmed()
                        if self.on_ack is not None:
                            for lease_id,ack in confirmed:
                                try:self.on_ack(lease_id,ack)
                                except Exception:pass  # Monitoring cannot block receipts.
                    if self.terminal:return
                    if failed:raise RuntimeError('Some results not acknowledged; retained locally')
                    self.last_error=None
                    continue
                for payload in items:
                    if self.stop.is_set():return
                    ack=self.send(payload)
                    if not isinstance(ack,dict) or ack.get('ok') is not True:raise RuntimeError('Result not acknowledged')
                    confirmed=self.queue.acknowledge(payload['lease_id'])
                    if confirmed and self.on_ack is not None:
                        try:self.on_ack(payload['lease_id'],ack)
                        except Exception:pass
                    self.last_error=None
            except Exception as error:
                self.last_error=type(error).__name__
                status=getattr(error,'code',None)
                if status in (401,403,422):self.terminal=True;return
                delay=1 if status==429 else 5
                try:delay=max(delay,float(error.headers.get('Retry-After',delay)))
                except (AttributeError,TypeError,ValueError):pass
                self.stop.wait(max(1,min(delay,3600)))

    def close(self):
        self.stop.set();self.wake.set();self.thread.join(35)
        if self.thread.is_alive():raise RuntimeError('Uploader did not terminate; durable receipts retained')
        self.queue.flush_confirmed()
