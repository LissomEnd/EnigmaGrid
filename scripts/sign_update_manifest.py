import argparse, base64
from pathlib import Path
from cryptography.hazmat.primitives import serialization
ap=argparse.ArgumentParser(); ap.add_argument('manifest'); ap.add_argument('--key',required=True); ap.add_argument('--out',default='update-manifest.sig'); a=ap.parse_args()
key=serialization.load_pem_private_key(Path(a.key).read_bytes(),password=None)
sig=key.sign(Path(a.manifest).read_bytes())
Path(a.out).write_text(base64.b64encode(sig).decode('ascii')+'\n',encoding='ascii')
print(Path(a.out).resolve())
