"""Idempotent C3->C4 transition. Safe no-op until every gate passes."""
import argparse,hashlib,json,os,shutil,sqlite3,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'state/grid.sqlite3'
MAN=ROOT/'campaigns/p1030680-c4-long-20261009.json'
AUDIT=ROOT/'campaigns/C4_SCOPE_AUDIT_20261009.json'
REPORT=ROOT/'state/c4-transition-last.json'
C4='p1030680-c4-long-20261009'
PRE=('p1030680-portable-v1','p1030680-c3-android-continuation','p1030680-c3-android-bridge-20261009')
DONE=('p1030680-constrained-v2','p1030680-bounded-followup-20261009')
def json_atomic(path,data):
 import tempfile
 with tempfile.NamedTemporaryFile('w',dir=path.parent,prefix='.c4-',suffix='.tmp',delete=False,encoding='utf8') as f:
  json.dump(data,f,indent=2);name=f.name;f.flush();os.fsync(f.fileno())
 os.replace(name,path)
def check_db(con):
 state={a:b for a,b in con.execute('select id,status from campaigns where id in ('+','.join('?' for _ in (*PRE,*DONE,C4))+')',(*PRE,*DONE,C4))}
 if state.get(C4)=='running':return 'already-running',state
 if state.get(C4)!='prepared':return 'C4-not-prepared',state
 for k in PRE:
  if state.get(k)!='complete':return 'C3-still-running:'+k,state
 for k in DONE:
  if state.get(k)!='complete':return 'prior-campaign-unfinished:'+k,state
 segments=list(con.execute('select id,next_unit,end_unit from segments where campaign_id in ('+','.join('?' for _ in PRE)+')',PRE))
 if not segments:return 'C3-segments-missing',state
 for sid,n,end in segments:
  if n!=end:return 'C3-index-unassigned:'+sid,state
  if con.execute("select 1 from validations where segment_id=? and status not in ('verified','accepted_trusted') limit 1",(sid,)).fetchone():return 'C3-validations-outstanding:'+sid,state
  if con.execute("select 1 from submissions where segment_id=? and status='pending' limit 1",(sid,)).fetchone():return 'C3-submissions-pending:'+sid,state
  if con.execute("select 1 from work_blocks where segment_id=? and status='reserved' limit 1",(sid,)).fetchone():return 'C3-blocks-reserved:'+sid,state
  if con.execute("select 1 from leases where segment_id=? and status='leased' limit 1",(sid,)).fetchone():return 'C3-leases-active:'+sid,state
  if con.execute("select 1 from requeue where segment_id=? limit 1",(sid,)).fetchone():return 'C3-requeue-pending:'+sid,state
  if con.execute("select 1 from block_receipts r join work_blocks b on b.id=r.block_id where r.promoted_at is null and r.verification_status='pending' and b.segment_id=? limit 1",(sid,)).fetchone():return 'C3-unpromoted-receipts:'+sid,state
 return None,state
def run(arm=False):
 now=time.time()
 audit=json.loads(AUDIT.read_text(encoding='utf8'))
 if hashlib.sha256(MAN.read_bytes()).hexdigest()!=audit['manifest_sha256']:raise RuntimeError('C4 manifest digest changed; refusing')
 if any(not (ROOT/'campaigns'/p).exists() for p in ('p1030680-portable-v1.json','p1030680-c3-android-continuation.json','p1030680-c3-android-bridge-20261009.json')):raise RuntimeError('Missing C3 historical manifests')
 con=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True,timeout=2);con.execute('pragma query_only=on')
 try:reason,states=check_db(con)
 finally:con.close()
 result={'checked_at':now,'campaign_states':states,'c4_manifest_digest':audit['manifest_sha256'],'arm_requested':bool(arm),'activated':False}
 if reason:
  result['gate']=reason
  json_atomic(REPORT,result);print(json.dumps(result));return
 if (ROOT/'state/enigma-solution-verified.json').exists():
  result['gate']='confirmed-solution-present-stop-search';json_atomic(REPORT,result);print(json.dumps(result));return
 backup=ROOT/'backups/backup-verified-latest.json'
 try:b=json.loads(backup.read_text(encoding='utf8'))
 except Exception:result['gate']='backup-metadata-unreadable';json_atomic(REPORT,result);print(json.dumps(result));return
 if b.get('status') not in ('verified','success'):
  result['gate']='fresh-verified-backup-required';json_atomic(REPORT,result);print(json.dumps(result));return
 backup_file=Path(b.get('path') or '')
 if b.get('integrity_check')!='ok' or b.get('method')!='sqlite_backup_pinned_read_transaction':
  result['gate']='backup-integrity-attestation-missing';json_atomic(REPORT,result);print(json.dumps(result));return
 if not backup_file.is_file() or backup_file.stat().st_size<100_000_000 or now-backup_file.stat().st_mtime>72*3600:
  result['gate']='recent-restorable-backup-required';json_atomic(REPORT,result);print(json.dumps(result));return
 free=shutil.disk_usage(ROOT).free
 if free<10*1024**3:
  result['gate']='disk-free-below-10-GiB';result['free_bytes']=free;json_atomic(REPORT,result);print(json.dumps(result));return
 health=ROOT/'state/coordinator_supervisor.json'
 h=json.loads(health.read_text(encoding='utf8'))
 if h.get('status')!='running' or int(h.get('restarts',0))>5:
  result['gate']='coordinator-unhealthy';json_atomic(REPORT,result);print(json.dumps(result));return
 if not arm:
  result['gate']='ready-dry-run';json_atomic(REPORT,result);print(json.dumps(result));return
 con=sqlite3.connect(DB,timeout=3,isolation_level=None)
 try:
  con.execute('BEGIN IMMEDIATE')
  reason,states=check_db(con)
  if reason:
   con.rollback();result['gate']='recheck:'+reason
  else:
   count=con.execute("update campaigns set status='running' where id=? and status='prepared'",(C4,)).rowcount
   if count!=1:raise RuntimeError('Prepared state changed')
   con.commit()
   result['gate']='activated';result['activated']=True
 finally:con.close()
 json_atomic(REPORT,result);print(json.dumps(result))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--arm-if-ready',action='store_true');a=p.parse_args();run(a.arm_if_ready)
