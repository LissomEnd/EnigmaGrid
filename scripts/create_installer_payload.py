import hashlib, json, sys
from pathlib import Path

out=Path(sys.argv[1])
version=sys.argv[2]
files={}
for name in ("EnigmaGrid.exe","EnigmaGridWorker.exe","EnigmaGridUpdater.exe","release_config.json"):
    p=out/name
    if not p.exists():raise SystemExit("missing "+name)
    files[name]={"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"size":p.stat().st_size}
manifest={"schema":1,"version":version,"files":files}
target=out/"installer_payload.json"
target.write_text(json.dumps(manifest,sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")
print(target)
