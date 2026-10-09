"""Select a stable Windows update behind an Android release, without network access."""
import base64
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'worker'))
import updater


def release(tag,names,**fields):
    prefix='https://github.com/Test/Fixture/releases/download/'+tag+'/'
    return dict(tag_name=tag,draft=False,prerelease=False,
                assets=[dict(name=name,browser_download_url=prefix+name) for name in names],**fields)


WINDOWS=('update-manifest.json','update-manifest.sig','enigma-volunteer-windows.zip')
with tempfile.TemporaryDirectory(prefix='enigma-update-release-selection-') as folder:
    root=Path(folder)
    manager=updater.UpdateManager('0.4.3',root/'client.json','')
    manager.cfg={'github_repo':'Test/Fixture'}
    android=release('android-v0.5.1',('enigmagrid-android.apk',))
    windows=release('v0.5.0',WINDOWS)
    older=release('v0.4.4',WINDOWS)
    draft=release('v9.0.0',WINDOWS);draft['draft']=True
    malformed=release('v8.0.0',WINDOWS[:2])
    urls=[]

    def listing(url,timeout):
        urls.append(url)
        if url.endswith('/latest'):return android
        if url.endswith('?per_page=100&page=1'):
            return [draft,malformed,older,windows,{'tag_name':'v10.0.0','assets':'bad'}]
        raise AssertionError('Unexpected update lookup: '+url)

    key=Ed25519PrivateKey.generate()
    public=root/'public.json'
    public.write_text(json.dumps({'algorithm':'ed25519','public_key_hex':
        key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()}))
    manifest=json.dumps({'schema':1,'version':'0.5.0','repository':'Test/Fixture',
                         'asset_name':WINDOWS[2],'mandatory':False}).encode()
    signature=base64.b64encode(key.sign(manifest))
    files={windows['assets'][0]['browser_download_url']:manifest,
           windows['assets'][1]['browser_download_url']:signature}

    def metadata(url,timeout):
        if url not in files:raise AssertionError('Only signed metadata may be read')
        return files[url]

    with patch.object(updater,'fetch_json',side_effect=listing),patch.object(updater,'fetch_bytes',side_effect=metadata),\
         patch.object(updater,'PUB',public),patch.object(updater,'prompt_update',return_value=False) as prompt:
        selected=manager._release()
        assert selected['tag_name']=='v0.5.0'
        result=manager.check_once()
        assert result=={'version':'0.5.0','accepted':False,'mandatory':False}
        assert len(urls)==4 and all('per_page=100&page=1' in url for url in urls[1::2])
        prompt.assert_called_once()

    # No matching Windows package is unavailable, rather than an Android update.
    with patch.object(updater,'fetch_json',side_effect=[android,[android,malformed,draft]]),\
         patch.object(updater,'prompt_update') as prompt:
        assert manager.check_once() is None
        assert json.loads(manager.status_path.read_text())['status']=='error'
        prompt.assert_not_called()

    broken=release('v7.0.0',WINDOWS)
    broken['assets'][0]['browser_download_url']='https://[invalid-host/path'
    with patch.object(updater,'fetch_json',side_effect=[android,[broken]*100+[windows]]):
        assert manager._release() is None  # Never scan beyond the first page.
    with patch.object(updater,'fetch_json',return_value=windows) as lookup:
        assert manager._release()['tag_name']=='v0.5.0'
        lookup.assert_called_once()  # Normal Windows latest needs no list request.

    # A signed but older Windows package cannot replace a newer installed app.
    current=updater.UpdateManager('0.5.1',root/'newer-client.json','')
    current.cfg=manager.cfg
    with patch.object(updater,'fetch_json',side_effect=[android,[older,windows]]),\
         patch.object(updater,'fetch_bytes',side_effect=metadata),patch.object(updater,'PUB',public),\
         patch.object(updater,'prompt_update') as prompt:
        assert current.check_once() is None
        assert json.loads(current.status_path.read_text())['status']=='current'
        prompt.assert_not_called()

print('PASS Android latest fallback selects signed stable Windows metadata, unavailable and no downgrade')
