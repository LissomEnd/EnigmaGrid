"""Public totals and credit exclude local diagnostic campaigns without deleting them."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
import coordinator as c


def main():
    old_data,old_db,old_cfg=c.DATA,c.DB,c.CFG
    with tempfile.TemporaryDirectory() as folder:
        c.DATA=Path(folder);c.DB=c.DATA/'grid.sqlite3';c.CFG=c.DATA/'server.json'
        c.CFG.write_text(json.dumps({'online_seconds':60,'public_campaign_ids':['p1030680-real']}))
        try:
            c.init_db();con=c.db()
            try:
                stamp=time.time()
                for cid,name in [('real','Real contributor'),('test','C0')]:
                    con.execute('insert into contributors(id,display_name,join_key_hash,dashboard_token_hash,created) values(?,?,?,?,?)',
                                (cid,name,'j-'+cid,'t-'+cid,stamp))
                    con.execute('insert into devices(id,contributor_id,label,token_hash,created) values(?,?,?,?,?)',
                                ('d-'+cid,cid,name,'k-'+cid,stamp))
                for cid,name,status in [('p1030680-real','Real search','running'),('ct','Consensus Test','paused')]:
                    con.execute('insert into campaigns(id,name,version,status,created) values(?,?,?,?,?)',
                                (cid,name,'1',status,stamp))
                con.execute("insert into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size) values('real-seg','p1030680-real','Real','portable_event_v1',0,5,5,1)")
                con.execute("insert into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size) values('cts','ct','Test','demo_hash',0,1,1,1)")
                con.execute("insert into done_ranges(segment_id,start_unit,end_unit,lease_id,device_id,completed_at,result_json) values('real-seg',0,3,'lr','d-real',?,'{}')",(stamp,))
                con.execute("insert into done_ranges(segment_id,start_unit,end_unit,lease_id,device_id,completed_at,result_json) values('cts',0,1,'lt','d-test',?,'{}')",(stamp,))
                for sid,start,end in [('real-seg',3,4),('cts',0,1)]:
                    con.execute('insert into validations(segment_id,start_unit,end_unit,base_required,target_replicas,max_replicas,status,created) values(?,?,?,?,?,?,?,?)',
                                (sid,start,end,2,2,3,'pending',stamp))
                submissions=[('r','real','d-real','real-seg',0,3,3.0),
                             ('rt','real','d-real','cts',0,1,1.0),
                             ('t','test','d-test','cts',0,1,1.0)]
                for sid,cid,did,segment,start,end,seconds in submissions:
                    con.execute('''insert into submissions(id,lease_id,segment_id,start_unit,end_unit,device_id,
                        contributor_id,fingerprint,result_json,compute_seconds,candidate_count,status,credited,submitted_at)
                        values(?,?,?,?,?,?,?,?,?,?,0,'verified',1,?)''',
                        (sid,'l'+sid,segment,start,end,did,cid,'f','{}',seconds,stamp))
                con.execute("insert into contributions(contributor_id,device_id,units,jobs,compute_seconds) values('real','d-real',4,2,4)")
                con.execute("insert into contributions(contributor_id,device_id,units,jobs,compute_seconds) values('test','d-test',1,1,1)")
                all_data=c.progress_payload(con)
                public=c.progress_payload(con,['p1030680-real'])
                assert (all_data['total_units'],all_data['completed_units'],all_data['pending_validations'])==(6,4,2),all_data
                assert (public['total_units'],public['completed_units'],public['pending_validations'])==(5,3,1),public
                assert [x['id'] for x in public['campaigns']]==['p1030680-real'],public['campaigns']
                assert public['leaderboard']==[{'display_name':'Real contributor','units':3,'jobs':1,'compute_seconds':3.0}],public['leaderboard']
                assert len(all_data['leaderboard'])==2
                assert c.progress_payload(con,[])['leaderboard']==[]
                c.PUBLIC_STATUS_CACHE=(None,0.0,None)
                cached=c.public_status_payload()
                assert cached['completed_units']==3 and len(cached['leaderboard'])==1,cached
                con.execute("insert into done_ranges(segment_id,start_unit,end_unit,lease_id,device_id,completed_at,result_json) values('real-seg',4,5,'lr2','d-real',?,'{}')",(stamp,))
                assert c.public_status_payload() is cached
                c.PUBLIC_STATUS_CACHE=(None,0.0,None)
                assert c.public_status_payload()['completed_units']==4
                c.CFG.write_text(json.dumps({'online_seconds':60}),encoding='utf-8')
                c.PUBLIC_STATUS_CACHE=(None,0.0,None)
                unconfigured=c.public_status_payload()
                assert unconfigured['campaigns']==[] and unconfigured['completed_units']==0
                assert unconfigured['leaderboard']==[],unconfigured
                print('PASS public campaign allowlist excludes diagnostic totals and credit, preserving real contributor')
            finally:con.close()
        finally:c.DATA,c.DB,c.CFG=old_data,old_db,old_cfg


if __name__=='__main__':main()
