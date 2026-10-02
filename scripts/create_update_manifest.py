import argparse, hashlib, json, re, time
from pathlib import Path

ap=argparse.ArgumentParser()
ap.add_argument("asset")
ap.add_argument("--version",required=True)
ap.add_argument("--repository",required=True)
ap.add_argument("--min-supported",default="")
ap.add_argument("--mandatory",action="store_true")
ap.add_argument("--notes",default="")
ap.add_argument("--out",default="update-manifest.json")
a=ap.parse_args()

semver=re.compile(r"^\d+\.\d+\.\d+$")
if not semver.fullmatch(a.version):
    raise SystemExit("--version must be MAJOR.MINOR.PATCH")
if a.min_supported and not semver.fullmatch(a.min_supported):
    raise SystemExit("--min-supported must be MAJOR.MINOR.PATCH")
if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",a.repository):
    raise SystemExit("--repository must be OWNER/REPO")

asset=Path(a.asset)
h=hashlib.sha256(asset.read_bytes()).hexdigest()
obj={"schema":1,"version":a.version,"repository":a.repository,
     "asset_name":"enigma-volunteer-windows.zip","sha256":h,
     "size":asset.stat().st_size,"mandatory":bool(a.mandatory),
     "min_supported_version":a.min_supported,
     "published_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
     "notes":a.notes}
data=(json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode("utf-8")
Path(a.out).write_bytes(data)
print(Path(a.out).resolve())
print(h)
