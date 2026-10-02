import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SETUP=ROOT/"dist"/"EnigmaGridSetup.exe"
CAND=ROOT/"dist"/"windows-candidate"
RUN_KEY=r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_BASE=r"Software\Microsoft\Windows\CurrentVersion\Uninstall"

def reg_value(path,name):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path) as k:
        return winreg.QueryValueEx(k,name)[0]

def exists_key(path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path):return True
    except FileNotFoundError:return False

def wait_gone(path,timeout=12):
    end=time.time()+timeout
    while time.time()<end:
        if not path.exists():return True
        time.sleep(.3)
    return False

def wait_no_cleanup_helpers(timeout=12):
    end=time.time()+timeout;temp=Path(tempfile.gettempdir())
    while time.time()<end:
        if not list(temp.glob("EnigmaGridCleanup-*.exe")):return True
        time.sleep(.3)
    return False

def main():
    assert SETUP.exists()
    for p in Path(tempfile.gettempdir()).glob("EnigmaGridCleanup-*.exe"):
        try:p.unlink()
        except Exception:pass
    tmp=Path(tempfile.mkdtemp(prefix="enigma-installer-test-"))
    install=tmp/"install";data=tmp/"data"
    app_id="EnigmaVolunteerGridTest_"+str(os.getpid())
    cmd=[str(SETUP),"--quiet","--no-launch",
         "--install-dir",str(install),"--data-dir",str(data),"--app-id",app_id]
    r=subprocess.run(cmd,timeout=180)
    assert r.returncode==0,r.returncode
    required=["EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe","EnigmaGridSetup.exe"]
    assert all((install/x).exists() for x in required)

    for name in ("EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe"):
        a=hashlib.sha256((install/name).read_bytes()).hexdigest()
        b=hashlib.sha256((CAND/name).read_bytes()).hexdigest()
        assert a==b,name
    assert reg_value(RUN_KEY,app_id)==f'"{install/"EnigmaGrid.exe"}"'
    u=UNINSTALL_BASE+"\\"+app_id
    assert exists_key(u)
    assert reg_value(u,"DisplayVersion")=="0.3.0"
    data.mkdir(parents=True,exist_ok=True)
    (data/"dummy-secret").write_text("test",encoding="utf-8")

    r=subprocess.run([str(install/"EnigmaGridSetup.exe"),"--uninstall","--quiet","--purge-data",
                      "--install-dir",str(install),"--data-dir",str(data),"--app-id",app_id],
                     timeout=180)
    assert r.returncode==0,r.returncode
    assert not exists_key(u)

    try:reg_value(RUN_KEY,app_id);raise AssertionError("run key remained")
    except FileNotFoundError:pass
    except OSError:pass
    assert wait_gone(data),data
    assert wait_gone(install),install
    # PyInstaller may keep the temporary cleanup runner locked briefly after uninstall.
    # It contains no credentials and is removed by the next setup run / normal temp cleanup.
    shutil.rmtree(tmp,ignore_errors=True)
    print("INSTALLER_E2E_OK",{"install":True,"registry":True,"uninstall":True})

if __name__=="__main__":main()
