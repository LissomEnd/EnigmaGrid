"""Public, network-isolated frozen-client qualification.

This does not replace the private-coordinator end-to-end test. It checks only
executable startup, application self-test, candidate package integrity and
path safety when the server-side private modules are unavailable.
"""
import hashlib,json,subprocess,sys,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist'
BIN=DIST/'windows-candidate'
ZIP=DIST/'enigma-volunteer-windows-candidate.zip'

def test():
    expected=['EnigmaGrid.exe','EnigmaGridWorker.exe','EnigmaGridUpdater.exe',
              'release_config.json','SHA256SUMS.txt','LICENSES.txt']
    for name in expected:
        path=BIN/name
        assert path.is_file() and path.stat().st_size>100,(name,'missing')
    cfg=json.loads((BIN/'release_config.json').read_text(encoding='utf8'))
    assert cfg.get('server_url','').startswith('https://'),'Client update endpoint must remain HTTPS'
    assert ZIP.is_file() and ZIP.stat().st_size>1_000_000
    with zipfile.ZipFile(ZIP) as z:
        assert z.testzip() is None,'Corrupt candidate ZIP'
        names=set(z.namelist())
        for name in expected:assert name in names,('ZIP missing',name)
        for name in names:
            p=Path(name.replace('\\','/'))
            assert not p.is_absolute() and '..' not in p.parts,'Unsafe member '+name
            if name in expected:
                assert hashlib.sha256(z.read(name)).digest()==hashlib.sha256((BIN/name).read_bytes()).digest(),name
    proc=subprocess.run([str(BIN/'EnigmaGrid.exe'),'--self-test'],capture_output=True,text=True,timeout=80)
    assert proc.returncode==0,'Tray selftest failed; no network or account was required'
    proc=subprocess.run([str(BIN/'EnigmaGridWorker.exe'),'--help'],capture_output=True,text=True,timeout=80)
    assert proc.returncode==0,'Frozen worker argument parser not startable'
    print('FROZEN_CLIENT_SMOKE_PASS',len(names),'archive_entries','no_private_server_dependency')

if __name__=='__main__':test()
