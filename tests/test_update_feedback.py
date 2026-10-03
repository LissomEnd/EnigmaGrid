"""Exercise visible update outcomes and manual retry independently of worker jobs."""
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))
import updater

with tempfile.TemporaryDirectory() as temp:
    manager = updater.UpdateManager('0.4.3', Path(temp) / 'client.json', '')
    manager.cfg = {'github_repo': 'Test/Fixture'}
    release = {'assets': [
        {'name': 'update-manifest.json', 'browser_download_url': 'https://github.com/test/manifest'},
        {'name': 'update-manifest.sig', 'browser_download_url': 'https://github.com/test/sig'}]}
    def check(version):
        body = json.dumps({'schema': 1, 'version': version, 'repository': 'Test/Fixture'}).encode()
        with patch.object(manager, '_release', return_value=release), patch.object(updater, 'fetch_bytes', side_effect=[body, b'sig']), patch.object(updater, 'verify_manifest'):
            return manager.check_once()
    check('0.4.3')
    assert json.loads(manager.status_path.read_text())['status'] == 'current'
    with patch.object(updater, 'prompt_update', return_value=False):
        check('0.4.4')
    assert json.loads(manager.status_path.read_text())['status'] == 'deferred'
    assert manager.local_state['dismissed_version'] == '0.4.4'
    manager.request_path.write_text('check')
    observed = []
    def failure():
        observed.append(dict(manager.local_state))
        raise OSError('offline')
    with patch.object(manager, 'check_once', side_effect=failure):
        manager.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            if manager.last_error:
                break
            time.sleep(.05)
        manager.shutdown()
        manager.thread.join(3)
    assert observed and 'dismissed_version' not in observed[0]
    assert json.loads(manager.status_path.read_text())['status'] == 'error'
    assert not manager.request_path.exists()
print('UPDATE_FEEDBACK_MANUAL_RETRY_AND_OFFLINE_OK')
