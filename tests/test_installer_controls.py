import json,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import installer

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);data=root/'data';data.mkdir();target=root/'install';target.mkdir()
    previous={'paused':True,'stop_requested':False,'check_update':True,'max_cpu_temp_c':84,'max_gpu_temp_c':78,'future_setting':'preserved'}
    control=data/'control.json';control.write_text(json.dumps(previous))
    (data/'client.json').write_bytes(b'opaque-account')
    (data/'client.json.pending-result').write_bytes(b'opaque-receipt')
    (target/'EnigmaGrid.exe').write_bytes(b'old')
    def drain(*args):
        current=installer.read_control(data)
        assert current==dict(previous,stop_requested=True)
        current['max_cpu_temp_c']=82
        control.write_text(json.dumps(current))
    args=SimpleNamespace(install_dir=str(target),data_dir=str(data),app_id='test',no_autostart=True,no_launch=True)
    with patch.object(installer,'verify_payload',return_value=(root,{})),patch.object(installer,'wait_worker_stopped',side_effect=drain),patch.object(installer.time,'sleep'),patch.object(installer,'replace_retry'),patch.object(installer,'register_install'),patch.object(sys,'frozen',True,create=True):
        installer.install(args)
    assert installer.read_control(data)==dict(previous,max_cpu_temp_c=82)
    assert not (data/'update-exit').exists()
    assert (data/'client.json').read_bytes()==b'opaque-account'
    assert (data/'client.json.pending-result').read_bytes()==b'opaque-receipt'
    control.write_text('{broken')
    try:installer.write_control(data)
    except ValueError:pass
    else:raise AssertionError('Malformed controls silently reset')
    assert control.read_text()=='{broken'
print('PASS upgrade preserves pause, thermal limits, concurrent setting changes, account and pending receipt; malformed control is not overwritten')
