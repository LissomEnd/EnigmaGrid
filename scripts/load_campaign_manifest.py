import argparse, json, os, sqlite3, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('GRID_DATA_DIR',str(ROOT/'state')))
DB=Path(os.environ.get('GRID_DB',str(DATA/'grid.sqlite3')))
ap=argparse.ArgumentParser(); ap.add_argument('manifest'); ap.add_argument('--activate',action='store_true'); ap.add_argument('--refresh-prepared',action='store_true')
a=ap.parse_args(); m=json.loads(Path(a.manifest).read_text(encoding='utf-8'))
con=sqlite3.connect(DB); con.row_factory=sqlite3.Row; con.execute('pragma foreign_keys=ON')
c=m['campaign']; requested='running' if a.activate else c.get('status','prepared')
old=con.execute('select status from campaigns where id=?',(c['id'],)).fetchone()
if old and a.refresh_prepared and old['status']!='prepared': raise SystemExit('Refusing refresh: campaign is not prepared')
con.execute('insert or ignore into campaigns(id,name,version,status,created,notes) values(?,?,?,?,?,?)',
            (c['id'],c['name'],c['version'],requested,time.time(),c.get('notes','')))
if old and a.refresh_prepared:
    con.execute('update campaigns set name=?,version=?,notes=? where id=?',(c['name'],c['version'],c.get('notes',''),c['id']))
for s in m['segments']:
    cfg=json.dumps(s.get('config',{}),separators=(',',':'))
    con.execute('''insert or ignore into segments(id,campaign_id,label,engine,start_unit,end_unit,next_unit,chunk_size,priority,config_json)
                   values(?,?,?,?,?,?,?,?,?,?)''',(s['id'],c['id'],s['label'],s['engine'],s['start_unit'],s['end_unit'],s['start_unit'],s['chunk_size'],s.get('priority',100),cfg))
    if old and a.refresh_prepared:
        con.execute('update segments set label=?,engine=?,chunk_size=?,priority=?,config_json=? where id=? and campaign_id=?',
                    (s['label'],s['engine'],s['chunk_size'],s.get('priority',100),cfg,s['id'],c['id']))
if a.activate:
    con.execute("update campaigns set status='running' where id=? and status='prepared'",(c['id'],))
con.commit(); print(c['id'],con.execute('select status from campaigns where id=?',(c['id'],)).fetchone()['status'],'segments',len(m['segments']),'db',DB)
