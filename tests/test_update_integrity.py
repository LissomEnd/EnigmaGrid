"""Always-run negative tests with an ephemeral release key; no production secrets."""
import base64
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'worker'))
import updater
import updater_apply

def rejects(call,types=(ValueError,InvalidSignature)):
    try:call()
    except types:return
    raise AssertionError('Untrusted update accepted')

with tempfile.TemporaryDirectory(prefix='enigma-update-integrity-') as temp:
    directory=Path(temp);key=Ed25519PrivateKey.generate()
    public=directory/'public.json'
    public.write_text(json.dumps({'algorithm':'ed25519','public_key_hex':key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()}))
    asset=directory/'asset.zip';asset.write_bytes(b'isolated-payload')
    manifest=directory/'manifest.json';signature=directory/'signature'
    obj={'schema':1,'version':'0.4.1','repository':'Test/Fixture','mandatory':False,'asset_name':asset.name,
         'size':asset.stat().st_size,'sha256':hashlib.sha256(asset.read_bytes()).hexdigest()}
    def signed(value):
        raw=json.dumps(value).encode();sig=base64.b64encode(key.sign(raw)).decode()
        manifest.write_bytes(raw);signature.write_text(sig);return raw,sig
    raw,sig=signed(obj)
    with patch.object(updater,'PUB',public):
        updater.verify_manifest(raw,sig)
        rejects(lambda:updater.verify_manifest(raw+b' ',sig))
        other=Ed25519PrivateKey.generate()
        rejects(lambda:updater.verify_manifest(raw,base64.b64encode(other.sign(raw)).decode()))
        assert updater_apply.verify(manifest,signature,public,asset)['version']=='0.4.1'
        asset.write_bytes(b'tampered-payload')
        rejects(lambda:updater_apply.verify(manifest,signature,public,asset))
        asset.write_bytes(b'isolated-payload')
        signed(dict(obj,size=obj['size']+1))
        rejects(lambda:updater_apply.verify(manifest,signature,public,asset))

        manager=updater.UpdateManager('0.4.0',directory/'client.json','http://127.0.0.1:1')
        manager.cfg={'github_repo':'Test/Fixture'}
        release={'assets':[{'name':'update-manifest.json','browser_download_url':'https://github.com/fixture/manifest'},
                           {'name':'update-manifest.sig','browser_download_url':'https://github.com/fixture/signature'}]}
        def check(value):
            body,signed_text=signed(value)
            with patch.object(manager,'_release',return_value=release),patch.object(updater,'fetch_bytes',side_effect=[body,signed_text.encode()]):
                return manager.check_once()
        with patch.object(updater,'prompt_update',return_value=False) as prompt:
            rejects(lambda:check(dict(obj,repository='Other/Project')))
            prompt.assert_not_called()
            assert check(dict(obj,version='0.3.9')) is None
            prompt.assert_not_called()
            assert check(obj)['mandatory'] is False
            assert manager.local_state['dismissed_version']=='0.4.1' and not manager.stop_requested
            # A previously declined optional update must be prompted again if now required.
            assert check(dict(obj,min_supported_version='0.4.1'))['mandatory'] is True
            assert manager.stop_requested and prompt.call_count==2
print('UPDATE_SIGNATURE_TAMPER_SIZE_REPOSITORY_DOWNGRADE_AND_REQUIRED_POLICY_OK')
