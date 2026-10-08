"""Real frozen update dialogs and downloads between configurable versions.

Only child processes use the loopback HTTPS proxy and temporary certificate.
No system trust, DNS, public release or production contributor is changed.
Requires both official release packages and the local protected signing key.
"""
import ctypes
import datetime
import hashlib
import json
import os
import shutil
import socket
import socketserver
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_frozen_update_local import force_stop_tmp,stop_runtime,wait_health
OLD=Path(os.environ.get('ENIGMA_TEST_OLD_CANDIDATE', ROOT/'dist/verified-0.4.1-backup'))
NEW=Path(os.environ.get('ENIGMA_TEST_CANDIDATE', ROOT/'dist/windows-candidate'))
ASSET=Path(os.environ.get('ENIGMA_TEST_ASSET', ROOT/'dist/public-0.4.2/enigma-volunteer-windows.zip'))
VERSION=os.environ.get('ENIGMA_TEST_TARGET_VERSION', '0.4.2')

def wait_for(check,timeout=90):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        value=check()
        if value:return value
        time.sleep(.2)
    raise TimeoutError('Update test timed out')

def dialog_for(install):
    u=ctypes.windll.user32;k=ctypes.windll.kernel32
    k.OpenProcess.restype=ctypes.c_void_p
    k.QueryFullProcessImageNameW.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)]
    k.CloseHandle.argtypes=[ctypes.c_void_p]
    u.GetWindowTextW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    found=[];callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
    @callback
    def visit(hwnd,extra):
        title=ctypes.create_unicode_buffer(256);u.GetWindowTextW(hwnd,title,256)
        if title.value!='Enigma Volunteer Grid update':return True
        pid=ctypes.c_ulong();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        handle=k.OpenProcess(0x1000,False,pid.value)
        if not handle:return True
        try:
            path=ctypes.create_unicode_buffer(32768);size=ctypes.c_ulong(32768)
            if not k.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size)):return True
            if Path(path.value).parent.resolve()!=install.resolve():return True
            texts=[]
            @callback
            def child(ch,arg):
                text=ctypes.create_unicode_buffer(2048);u.GetWindowTextW(ch,text,2048)
                texts.append(text.value);return True
            u.EnumChildWindows(ctypes.c_void_p(hwnd),child,0)
            message=' '.join(texts)
            if 'ISOLATED LOCAL UPDATE TEST' not in message:return True
            found.append((hwnd,message));return False
        finally:k.CloseHandle(handle)
    u.EnumWindows(visit,0)
    return found[0] if found else None

def main():
    key_blob=os.environ.get('ENIGMA_TEST_SIGNING_KEY_BLOB')
    if os.name!='nt' or not key_blob:
        print('FROZEN_PROMPT_E2E_SKIPPED: Windows and protected test signing key required');return
    assert ASSET.exists() and (OLD/'EnigmaGridWorker.exe').exists()
    tmp=Path(tempfile.mkdtemp(prefix='enigma-prompts-e2e-'))
    server=None;proxy=None
    try:
        # Certificate is scoped through SSL_CERT_FILE in test client environments.
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'EnigmaGrid isolated update fixture')])
        now=datetime.datetime.now(datetime.timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1))
              .not_valid_after(now+datetime.timedelta(days=1))
              .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
              .add_extension(x509.SubjectAlternativeName([x509.DNSName('github.com'),x509.DNSName('api.github.com')]),critical=False)
              .sign(key,hashes.SHA256()))
        certfile=tmp/'fixture.pem';keyfile=tmp/'fixture-key.pem'
        certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(certfile,keyfile)
        routes={};requests=[]
        # A busy scenario must acquire work before its update can be announced.
        # Otherwise a foreground Yes/No dialog is exposed while the fixture waits.
        release_ready=threading.Event()
        class Proxy(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(30)
                line=self.rfile.readline(4096).decode().strip()
                if line not in ('CONNECT github.com:443 HTTP/1.0','CONNECT api.github.com:443 HTTP/1.0',
                                'CONNECT github.com:443 HTTP/1.1','CONNECT api.github.com:443 HTTP/1.1'):return
                for _ in range(100):
                    if self.rfile.readline(4096) in (b'\r\n',b'\n',b''):break
                self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n');self.wfile.flush()
                try:
                    with context.wrap_socket(self.connection,server_side=True) as tls:
                        stream=tls.makefile('rb');request=stream.readline(4096).decode().split()
                        if len(request)!=3 or request[0]!='GET':return
                        for _ in range(100):
                            if stream.readline(4096) in (b'\r\n',b'\n',b''):break
                        path=request[1];requests.append(path)
                        if path.endswith('/releases/latest') and not release_ready.wait(60):
                            tls.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length:0\r\n\r\n');return
                        value=routes.get(path)
                        if value is None:tls.sendall(b'HTTP/1.1 404 Not Found\r\nContent-Length:0\r\n\r\n');return
                        size=value.stat().st_size if isinstance(value,Path) else len(value)
                        tls.sendall(f'HTTP/1.1 200 OK\r\nContent-Length: {size}\r\nConnection: close\r\n\r\n'.encode())
                        if isinstance(value,Path):
                            with value.open('rb') as f:
                                while block:=f.read(1024*1024):tls.sendall(block)
                        else:tls.sendall(value)
                except (ssl.SSLError,ConnectionError,OSError):pass
        class ProxyServer(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
        proxy=ProxyServer(('127.0.0.1',0),Proxy);threading.Thread(target=proxy.serve_forever,daemon=True).start()
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        cfg=json.loads((ROOT/'config/server.example.json').read_text());cfg.update(port=port,registration_open=True,
             registration_code='',registration_pow_bits=12,min_worker_version='0.4.0')
        cfgfile=tmp/'server.json';cfgfile.write_text(json.dumps(cfg))
        env=os.environ.copy();env.update(GRID_CONFIG=str(cfgfile),GRID_DATA_DIR=str(tmp/'db'),GRID_PORT=str(port),GRID_HOST='127.0.0.1')
        server=subprocess.Popen([sys.executable,str(ROOT/'server/coordinator.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        base=f'http://127.0.0.1:{port}'
        def ready():
            try:return json.load(urllib.request.urlopen(base+'/health',timeout=1)).get('ok')
            except Exception:return False
        wait_for(ready,20)
        clientenv=env.copy();clientenv.update(HTTPS_PROXY=f'http://127.0.0.1:{proxy.server_address[1]}',
           HTTP_PROXY='',NO_PROXY='127.0.0.1,localhost',SSL_CERT_FILE=str(certfile))
        busy_case=os.environ.get('ENIGMA_TEST_UPDATE_BUSY')=='1'
        scenarios=[(True,False),(False,True)] if busy_case else [(False,False),(False,True),(True,False),(True,True)]
        for mandatory,accepted in scenarios:
            release_ready.clear()
            if not busy_case:release_ready.set()
            label=('mandatory' if mandatory else 'optional')+('-accept' if accepted else '-decline')
            case=tmp/label;install=case/'install';shutil.copytree(OLD,install)
            state=case/'user/client.json';state.parent.mkdir(parents=True)
            manifest=case/'manifest.json';sig=case/'manifest.sig'
            cmd=[sys.executable,str(ROOT/'scripts/create_update_manifest.py'),str(ASSET),'--version',VERSION,
                 '--repository','LissomEnd/EnigmaGrid','--out',str(manifest),'--notes','ISOLATED LOCAL UPDATE TEST']
            if mandatory:cmd+=['--mandatory','--min-supported',VERSION]
            subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)
            subprocess.run([sys.executable,str(ROOT/'scripts/sign_update_manifest_dpapi.py'),str(manifest),
                            '--key-blob',key_blob,'--out',str(sig)],check=True,stdout=subprocess.DEVNULL)
            prefix='/LissomEnd/EnigmaGrid/releases/download/isolated-test/'
            files={'update-manifest.json':manifest,'update-manifest.sig':sig,'enigma-volunteer-windows.zip':ASSET}
            routes.clear();routes.update({prefix+n:p for n,p in files.items()})
            routes['/repos/LissomEnd/EnigmaGrid/releases/latest']=json.dumps({'tag_name':'v'+VERSION,'draft':False,'prerelease':False,
                'assets':[{'name':n,'browser_download_url':'https://github.com'+prefix+n} for n in files]}).encode()
            args=[str(install/'EnigmaGridWorker.exe'),'--state',str(state),'--server',base,'--cpu-percent','1','--gpu-percent','0']
            subprocess.run(args+['--name','Isolated update test','--register-only'],env=clientenv,check=True,timeout=120,stdout=subprocess.DEVNULL)
            if busy_case:
                with sqlite3.connect(tmp/'db/grid.sqlite3') as db:
                    db.execute("update campaigns set status='paused'")
                    db.execute("insert into campaigns values(?,?,?,'running',?,'isolated safe-boundary test')",(label,label,'1',time.time()))
                    db.execute("insert into segments values(?,?,?,'demo_hash',0,1,0,1,1,?)",(label,label,label,json.dumps({'hash_rounds':12000000,'requires':['cpu']})))
            identity=hashlib.sha256(state.read_bytes()).hexdigest()
            log=(case/'worker.log').open('wb')
            worker=subprocess.Popen(args,env=clientenv,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            if busy_case:
                def computing():
                    if worker.poll() is not None:raise RuntimeError('Fixture worker exited before acquiring work')
                    try:return json.loads(state.with_name('worker-health.json').read_text()).get('status')=='computing'
                    except (OSError,ValueError):return False
                try:wait_for(computing,30)
                except TimeoutError:
                    # Preserve actionable fixture diagnostics before finally removes
                    # its private temporary directory; never read production state.
                    health=state.with_name('worker-health.json')
                    print('BUSY_FIXTURE_HEALTH',health.read_text() if health.exists() else 'missing',flush=True)
                    print('BUSY_FIXTURE_LOG',(case/'worker.log').read_text(errors='replace')[-2000:],flush=True)
                    raise
                release_ready.set()
            print('WAITING_FOR_REAL_DIALOG',label,flush=True)
            hwnd,text=wait_for(lambda:dialog_for(install),90)
            assert ('REQUIRED' in text)==mandatory,text
            assert VERSION in text and 'ISOLATED LOCAL UPDATE TEST' in text
            if busy_case:
                # A stale health file is insufficient: the lease must still be active.
                with sqlite3.connect(tmp/'db/grid.sqlite3') as db:
                    assert db.execute("select count(*) from leases where segment_id=? and status='leased'",(label,)).fetchone()[0]==1
            respond_to_dialog(install,hwnd,accepted)
            if accepted:
                assert wait_health(state.with_name('worker-health.json'),VERSION,180)
                for name in ('EnigmaGridWorker.exe','EnigmaGrid.exe','EnigmaGridUpdater.exe'):
                    assert hashlib.sha256((install/name).read_bytes()).digest()==hashlib.sha256((NEW/name).read_bytes()).digest()
            elif mandatory:
                assert worker.wait(timeout=35)==0
                assert json.loads(state.with_name('control.json').read_text())['stop_requested']
            else:
                wait_for(lambda:state.with_name('update_state.json').exists(),10)
                assert json.loads(state.with_name('update_state.json').read_text())['dismissed_version']==VERSION
                assert worker.poll() is None
            assert hashlib.sha256(state.read_bytes()).hexdigest()==identity
            if busy_case:
                with sqlite3.connect(tmp/'db/grid.sqlite3') as db:
                    assert db.execute("select count(*) from leases where segment_id=? and status='submitted'",(label,)).fetchone()[0]==1
            stop_runtime(state);force_stop_tmp(case);worker.wait(timeout=15);log.close()
            print('REAL_FROZEN_UPDATE_PROMPT_OK',label,flush=True)
        assert any(p.endswith('enigma-volunteer-windows.zip') for p in requests)
        print('FROZEN_UPDATE_SAFE_BOUNDARIES_PASSED' if busy_case else 'ALL_FOUR_FROZEN_UPDATE_SCENARIOS_PASSED',flush=True)
    finally:
        force_stop_tmp(tmp)
        if server:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill()
        if proxy:proxy.shutdown();proxy.server_close()
        shutil.rmtree(tmp,ignore_errors=True)

def respond_to_dialog(install,expected_hwnd,accepted,*,lookup=None,post=None):
    """Never answer another/replaced dialog; injectable for headless regression."""
    current=(lookup or dialog_for)(install)
    if not current or current[0]!=expected_hwnd:
        raise RuntimeError('Isolated dialog dismissed or replaced before response; scenario is inconclusive')
    if post is None:
        post=ctypes.windll.user32.PostMessageW
        post.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
    if not post(expected_hwnd,0x111,6 if accepted else 7,0):
        raise RuntimeError('Could not deliver response to isolated update dialog')

if __name__=='__main__':main()
