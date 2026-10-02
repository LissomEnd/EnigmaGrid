import argparse, os, sqlite3, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('GRID_DATA_DIR',str(ROOT/'state')))
DB=Path(os.environ.get('GRID_DB',str(DATA/'grid.sqlite3')))
ap=argparse.ArgumentParser(); ap.add_argument('--out',default=str(ROOT/'backups')); a=ap.parse_args()
out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
dest=out/f"grid-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"
src=sqlite3.connect(DB); dst=sqlite3.connect(dest)
with dst: src.backup(dst)
dst.close(); src.close()
print(dest)
