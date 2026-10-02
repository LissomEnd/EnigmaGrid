import argparse
import base64
import ctypes
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization

class BLOB(ctypes.Structure):
    _fields_=[("cbData",ctypes.c_ulong),("pbData",ctypes.POINTER(ctypes.c_ubyte))]

def unprotect(data):
    if os.name!="nt":
        raise SystemExit("DPAPI signing is supported only on Windows")
    raw=(ctypes.c_ubyte*len(data)).from_buffer_copy(data)
    src=BLOB(len(data),ctypes.cast(raw,ctypes.POINTER(ctypes.c_ubyte)))
    dst=BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(src),None,None,None,None,0x1,ctypes.byref(dst)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(dst.pbData,dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--key-blob",default=os.environ.get("ENIGMA_SIGNING_KEY_BLOB",""))
    ap.add_argument("--out",default="update-manifest.sig")
    a=ap.parse_args()
    if not a.key_blob:
        raise SystemExit("--key-blob or ENIGMA_SIGNING_KEY_BLOB is required")
    key_bytes=bytearray(unprotect(Path(a.key_blob).read_bytes()))
    try:
        key=serialization.load_pem_private_key(bytes(key_bytes),password=None)
        sig=key.sign(Path(a.manifest).read_bytes())
    finally:
        for i in range(len(key_bytes)):
            key_bytes[i]=0
    Path(a.out).write_text(base64.b64encode(sig).decode("ascii")+"\n",encoding="ascii")
    print(Path(a.out).resolve())

if __name__=="__main__":
    main()
