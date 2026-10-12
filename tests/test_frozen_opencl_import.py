"""Verify GPU dependencies inside the actual frozen worker, without enrollment."""
import argparse,json,subprocess
from pathlib import Path
CODE = """from multiprocessing.resource_tracker import main
import sqlite3,pyopencl,json
print(json.dumps({'sqlite':sqlite3.sqlite_version,'opencl':pyopencl.VERSION_TEXT}))
"""
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--exe',required=True);ap.add_argument('--expect-broken',action='store_true');a=ap.parse_args()
    # Use the bundled multiprocessing diagnostic entry, with its exact isolated
    # interpreter flags. No rebuilt probe can accidentally use host dependencies.
    r=subprocess.run([str(Path(a.exe).resolve()),'-B','-I','-S','-c',CODE],capture_output=True,text=True,timeout=45)
    if a.expect_broken:
        assert r.returncode != 0 and '_sqlite3' in r.stderr and 'DLL load failed' in r.stderr,r.stderr
        print('PASS reproduced missing frozen SQLite DLL')
    else:
        assert r.returncode == 0,r.stderr
        data=json.loads(r.stdout.strip().splitlines()[-1]);assert data['sqlite'] and data['opencl'];print('PASS frozen SQLite and OpenCL import',data)
if __name__=='__main__':main()
