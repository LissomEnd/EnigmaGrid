import hashlib
import json
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

def wait_no_cleanup_helpers(timeout=20):
    end=time.time()+timeout;temp=Path(tempfile.gettempdir())
    while time.time()<end:
        if not list(temp.glob("EnigmaGridCleanup-*.exe")) and not list(temp.glob("EnigmaGridCleanup-*.cmd")):return True
        time.sleep(.3)
    return False

def main():
    assert SETUP.exists()
    pre=subprocess.run([str(SETUP),"--self-test"],timeout=120)
    assert pre.returncode==0,pre.returncode
    for pattern in ("EnigmaGridCleanup-*.exe","EnigmaGridCleanup-*.cmd"):
        for p in Path(tempfile.gettempdir()).glob(pattern):
            try:p.unlink()
            except Exception:pass
    # Windows runners may expose TEMP through an 8.3 alias; the installer
    # registers the resolved long path, so compare against that same path.
    tmp=Path(tempfile.mkdtemp(prefix="enigma-installer-test-")).resolve()
    install=tmp/"install";data=tmp/"data"
    app_id="EnigmaVolunteerGridTest_"+str(os.getpid())
    cmd=[str(SETUP),"--quiet","--no-launch",
         "--install-dir",str(install),"--data-dir",str(data),"--app-id",app_id]
    r=subprocess.run(cmd,timeout=180)
    assert r.returncode==0,r.returncode
    required=["EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe","release_config.json","EnigmaGridSetup.exe","LICENSES.txt"]
    assert all((install/x).exists() for x in required)

    for name in ("EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe","release_config.json","LICENSES.txt"):
        a=hashlib.sha256((install/name).read_bytes()).hexdigest()
        b=hashlib.sha256((CAND/name).read_bytes()).hexdigest()
        assert a==b,name
    release=json.loads((install/"release_config.json").read_text(encoding="utf-8"))
    assert str(release["server_url"]).startswith("https://")
    actual=reg_value(RUN_KEY,app_id)
    expected=f'"{install/"EnigmaGrid.exe"}" --background'
    assert actual==expected,(actual,expected)
    u=UNINSTALL_BASE+"\\"+app_id
    assert exists_key(u)
    assert reg_value(u,"DisplayVersion")=="0.4.2"
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
    assert wait_no_cleanup_helpers(),"temporary cleanup helper remained"
    shutil.rmtree(tmp,ignore_errors=True)
    print("INSTALLER_E2E_OK",{"install":True,"registry":True,"uninstall":True,"temp_cleanup":True})

if __name__=="__main__":main()
