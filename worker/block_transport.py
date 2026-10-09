"""Long-block HTTP transport; execution is independent of these calls."""
import json
import math
import time
from search.work_block import FORMAT, MAX_BODY_BYTES
from search.work_result_groups import FORMAT as GROUP_FORMAT

class ReceiptRejected(RuntimeError):
    """Terminal server refusal; the local receipt must be retained."""


class BlockTransport:
    def __init__(self,queue,request,*,grouped=False):
        self.queue=queue;self.request=request;self.grouped=grouped

    def allocate(self):
        self.release_ready()
        identity=self.queue.allocation_request()
        observed_at=time.monotonic()
        response=self.request('/api/work-blocks',dict(format=FORMAT,request_id=identity))
        if not isinstance(response,dict):raise ValueError('Invalid block response')
        block=response.get('block')
        if block is not None:
            if response.get('status') in ('expired','released','submitted'):
                self.queue.allocation_retired(identity,block)
                return dict(block=None,wait_reason='previous_block_finished')
            if response.get('status')!='reserved':raise ValueError('Invalid block reservation state')
            lifetime=response.get('valid_for_seconds')
            if lifetime is not None:
                if type(lifetime) not in (int,float) or not math.isfinite(lifetime) or not 0<=lifetime<=7200:
                    raise ValueError('Invalid block lifetime')
            self.queue.allocation_received(identity,block,lifetime,observed_at=observed_at)
            # A modern coordinator returns authoritative remaining lifetime on
            # both new and replayed reservations. Older coordinators require the
            # status round trip before the first unit can safely be claimed.
            if lifetime is None:self.refresh_status()
        return response

    def upload(self):
        pending=self.queue.pending()
        if not pending:
            self.release_ready();return 0
        identity=pending[0]['block_id'];receipts=[]
        def body():
            if self.grouped:
                return dict(format=GROUP_FORMAT,block_id=identity,groups=[receipts[i:i+8] for i in range(0,len(receipts),8)])
            return dict(format=FORMAT,block_id=identity,receipts=receipts)
        for item in pending:
            if item['block_id']!=identity:continue
            entry={k:v for k,v in item.items() if k!='block_id'}
            receipts.append(entry)
            if len(json.dumps(body(),separators=(',',':'),ensure_ascii=True,allow_nan=False).encode())>MAX_BODY_BYTES:
                receipts.pop();break
            if len(receipts)==(64 if self.grouped else 8):break
        if not receipts:raise ValueError('Receipt exceeds HTTP limit; retained locally')
        response=self.request('/api/work-blocks/result-groups' if self.grouped else '/api/work-blocks/results',body())
        if not isinstance(response,dict) or response.get('block_id')!=identity or not isinstance(response.get('results'),list):
            raise ValueError('Invalid receipt acknowledgement')
        expected={x['unit'] for x in receipts};seen=set();accepted=[];rejected=[];expired=[]
        for item in response['results']:
            if not isinstance(item,dict) or type(item.get('unit')) is not int or item['unit'] not in expected or item['unit'] in seen:
                raise ValueError('Invalid acknowledged unit')
            seen.add(item['unit'])
            if item.get('status')=='received':accepted.append(item['unit'])
            elif item.get('status')=='expired':expired.append(item['unit'])
            elif item.get('status')=='conflict':rejected.append(item['status'])
            else:raise ValueError('Unknown receipt acknowledgement status')
        if expired:self.queue.archive_expired(identity,expired)
        self.queue.acknowledge(identity,accepted)
        if rejected:raise ReceiptRejected(','.join(sorted(set(rejected))))
        self.release_ready()
        return len(accepted)

    def release_ready(self):
        for identity in self.queue.releasable():
            response=self.request('/api/work-blocks/release',dict(format=FORMAT,block_id=identity))
            if not isinstance(response,dict) or response.get('block_id')!=identity or response.get('released') is not True:
                raise ValueError('Invalid release acknowledgement')
            self.queue.released(identity)

    def refresh_status(self):
        identities=self.queue.identities()
        if not identities:return
        observed_at=time.monotonic()
        response=self.request('/api/work-blocks/status',dict(format=FORMAT,blocks=identities))
        rows=response.get('blocks') if isinstance(response,dict) else None
        if not isinstance(rows,list) or len(rows)!=len(identities):raise ValueError('Invalid block status')
        states={}
        for row in rows:
            if not isinstance(row,dict) or row.get('block_id') not in identities or row['block_id'] in states:raise ValueError('Invalid block status identity')
            seconds=row.get('valid_for_seconds')
            if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<=seconds<=7200:raise ValueError('Invalid block lifetime')
            if row.get('status') not in ('reserved','submitted','released','expired'):raise ValueError('Invalid block state')
            states[row['block_id']]=row
        self.queue.update_status(states,observed_at=observed_at)
