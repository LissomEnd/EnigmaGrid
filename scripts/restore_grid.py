import argparse, os, shutil, sqlite3, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('GRID_DATA_DIR',str(ROOT/'state')))
DB=Path(os.environ.get('GRID_DB',str(DATA/'grid.sqlite3')))
ap=argparse.ArgumentParser(); ap.add_argument('backup'); ap.add_argument('--yes',action='store_true'); a=ap.parse_args()
src=Path(a.backup)
if not src.exists(): raise SystemExit('Backup not found')
if not a.yes: raise SystemExit('Refusing restore without --yes; stop coordinator first')
test=sqlite3.connect(src); ok=test.execute('pragma integrity_check').fetchone()[0]; test.close()
if ok!='ok': raise SystemExit('Backup integrity check failed: '+str(ok))
DATA.mkdir(parents=True,exist_ok=True)
if DB.exists(): shutil.copy2(DB,DB.with_suffix('.pre-restore-'+time.strftime('%Y%m%d-%H%M%S')+'.sqlite3'))
shutil.copy2(src,DB)
print(DB)
