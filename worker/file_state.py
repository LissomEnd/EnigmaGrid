"""Atomic state writes resilient to short-lived Windows reader locks."""
import os
import secrets
import time
from pathlib import Path


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        temporary.write_bytes(data)
        if os.name != 'nt':
            temporary.chmod(0o600)
        for attempt in range(8):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(min(0.01 * (2 ** attempt), 0.1))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
