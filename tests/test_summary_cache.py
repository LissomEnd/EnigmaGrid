"""UI snapshots cannot cross account changes or survive expiry/worker versions."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from summary_cache import SummaryPublisher,read_cached_summary

with tempfile.TemporaryDirectory() as folder:
    state=Path(folder)/'client.json';state.write_bytes(b'encrypted-account-one')
    publisher=SummaryPublisher(state,'test',lambda _: {'registered':True,'settings':{'cpu_percent':100}})
    publisher.publish()
    assert read_cached_summary(state,'test')['settings']['cpu_percent']==100
    assert read_cached_summary(state,'other-version') is None
    cache=state.with_name('client-summary-cache.json')
    record=json.loads(cache.read_text())
    with patch('summary_cache.time.time',return_value=record['created']+36):
        assert read_cached_summary(state,'test') is None
    state.write_bytes(b'encrypted-account-two')
    assert read_cached_summary(state,'test') is None
    def changed_account(_):
        state.write_bytes(b'encrypted-account-three')
        return {'registered':True}
    publisher.fetch=changed_account
    publisher.publish()
    assert json.loads(cache.read_text())==record,'Account changed during fetch but snapshot was published'
    publisher.stop.set();publisher.fetch=lambda _: {'registered':True}
    publisher.publish()
    assert json.loads(cache.read_text())==record,'Stopped publisher wrote a snapshot'
    cache.write_text('{broken')
    assert read_cached_summary(state,'test') is None
print('PASS summary cache reuse, expiry, version/account isolation, account race, stop and malformed fallback')

# Exercise the real UI fetch path without launching Tk or the packaged worker.
from types import SimpleNamespace
from unittest.mock import Mock
import tray_app
received=[]
view=SimpleNamespace(root=SimpleNamespace(after=lambda delay,fn:fn()),apply_summary=received.append,refresh_busy=True)
with patch.object(tray_app,'read_cached_summary',return_value={'registered':True}) as cached, patch.object(tray_app,'run_worker') as launch:
    tray_app.App.fetch_summary(view)
    assert received==[{'registered':True}] and not view.refresh_busy
    launch.assert_not_called()
received.clear()
with patch.object(tray_app,'read_cached_summary',return_value=None),patch.object(tray_app,'run_worker',return_value=SimpleNamespace(returncode=0,stdout='{"registered":false}')) as launch:
    tray_app.App.fetch_summary(view)
    assert received==[{'registered':False}]
    launch.assert_called_once()
print('PASS UI uses fresh cache without spawning worker and retains legacy fallback')
