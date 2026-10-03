import argparse, os, sqlite3, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('GRID_DATA_DIR',str(ROOT/'state')))
DB=Path(os.environ.get('GRID_DB',str(DATA/'grid.sqlite3')))
ap=argparse.ArgumentParser(); ap.add_argument('--out',default=str(ROOT/'backups'))
ap.add_argument('--keep-days',type=int,default=7)
a=ap.parse_args()
if a.keep_days < 1: raise SystemExit('--keep-days must be positive')
out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
dest=out/f"grid-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"
src=sqlite3.connect(DB); dst=sqlite3.connect(dest)
with dst: src.backup(dst)
dst.close(); src.close()
cutoff=time.time()-a.keep_days*86400
for old in out.glob('grid-????????-??????.sqlite3'):
    if old != dest and old.is_file() and not old.is_symlink() and old.stat().st_mtime < cutoff:
        old.unlink()
print(dest)
