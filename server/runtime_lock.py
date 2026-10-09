"""Cross-process ownership for a database, shared by service and maintenance.

The persistent lock file is not a PID file and must never be unlinked while in
use: operating-system locks are released automatically after process death.
"""
from contextlib import contextmanager
from pathlib import Path
import os


@contextmanager
def database_runtime_lock(database):
    path = Path(str(Path(database).resolve()) + '.runtime.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('Database is owned by a running coordinator or maintenance operation') from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
