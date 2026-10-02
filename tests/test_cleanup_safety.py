"""Uninstall helpers must preserve unrelated files and reject arbitrary targets."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
import updater_apply

with tempfile.TemporaryDirectory(prefix='enigma-cleanup-safety-') as temp:
    root=Path(temp).resolve()
    unrelated=root/'personal.txt';unrelated.write_text('keep')
    try:updater_apply.cleanup_install(root)
    except FileNotFoundError:pass
    else:raise AssertionError('arbitrary directory accepted')
    assert unrelated.read_text()=='keep'
    (root/'enigmagrid-install.json').write_text(json.dumps({'product':'EnigmaVolunteerGrid','directory':str(root)}))
    (root/'EnigmaGrid.exe').write_bytes(b'test')
    assert updater_apply.cleanup_install(root)==0
    assert unrelated.read_text()=='keep'
    assert not (root/'EnigmaGrid.exe').exists()
print('CLEANUP_SAFETY_OK')
