"""Bounded package retention using synthetic files only; no production paths."""
import json,sys,tempfile,stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from updater_apply import prune_update_packages

def package(root,version):
 p=root/'updates'/version;p.mkdir(parents=True)
 (p/'app.zip').write_bytes(b'synthetic package')
 (p/'update-manifest.json').write_text(json.dumps({'schema':1,'version':version,'asset_name':'app.zip'}))
 (p/'update-manifest.sig').write_text('synthetic signature')
 return p

with tempfile.TemporaryDirectory(prefix='enigma-package-retention-') as temp:
 root=Path(temp);state=root/'client.json';state.write_text('identity sentinel')
 for v in ('0.1.0','0.2.0','0.3.0','0.4.0','0.5.0'):package(root,v)
 # Preserve actual previous version even when another cached version is newer.
 assert prune_update_packages(state,'0.4.0','0.2.0')==['0.1.0']
 assert (root/'updates/0.2.0/app.zip').exists() and (root/'updates/0.3.0/app.zip').exists()
 assert (root/'updates/0.4.0/app.zip').exists() and (root/'updates/0.5.0/app.zip').exists()
 assert state.read_text()=='identity sentinel'
 old=package(root,'0.1.0');(root/'update-stage-0.1.0').mkdir()
 assert not prune_update_packages(state,'0.4.0','0.2.0');(root/'update-stage-0.1.0').rmdir()
 (root/'update_state.json').write_text(json.dumps({'downloaded_version':'0.1.0'}))
 assert not prune_update_packages(state,'0.4.0','0.2.0');(root/'update_state.json').unlink()
 (root/'update-backup').mkdir();assert not prune_update_packages(state,'0.4.0');(root/'update-backup').rmdir()
 (old/'app.zip.part').write_bytes(b'incomplete');assert not prune_update_packages(state,'0.4.0','0.2.0');(old/'app.zip.part').unlink()
 (old/'unrelated.txt').write_text('preserve');assert not prune_update_packages(state,'0.4.0','0.2.0');(old/'unrelated.txt').unlink()
 (root/'update-pending.json').write_text('malformed');assert not prune_update_packages(state,'0.4.0');(root/'update-pending.json').unlink()
 original=Path.lstat
 def reparse(path,*args,**kwargs):
  result=original(path,*args,**kwargs)
  if path==old:return SimpleNamespace(st_mode=result.st_mode,st_file_attributes=0x400)
  return result
 with patch.object(Path,'lstat',reparse):assert not prune_update_packages(state,'0.4.0','0.2.0')
 assert (old/'app.zip').exists()
 (old/'update-manifest.json').write_text(json.dumps({'schema':1,'version':'0.1.0','asset_name':'../outside.zip'}))
 assert not prune_update_packages(state,'0.4.0','0.2.0')
 print('UPDATE_PACKAGE_RETENTION_CURRENT_PREVIOUS_PENDING_STAGE_BACKUP_UNKNOWN_REPARSE_AND_ESCAPE_OK')
