"""Local UI snapshots produced by the existing worker, without helper processes."""
import hashlib
import json
import threading
import time
from pathlib import Path
from file_state import atomic_write


def identity(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_cached_summary(state_path, version):
    try:
        record=json.loads(Path(state_path).with_name('client-summary-cache.json').read_text(encoding='utf-8'))
        age=time.time()-record['created']
        if not 0<=age<=35 or record['version']!=version or record['identity']!=identity(state_path):return None
        return record['summary'] if isinstance(record['summary'],dict) else None
    except (OSError,ValueError,KeyError,TypeError):return None


class SummaryPublisher:
    def __init__(self,state_path,version,fetch):
        self.path=Path(state_path);self.version=version;self.fetch=fetch
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,name='ui-summary',daemon=True)

    def publish(self):
        before=identity(self.path)
        summary=self.fetch(self.path)
        if self.stop.is_set() or identity(self.path)!=before:return
        record={'created':time.time(),'version':self.version,'identity':before,'summary':summary}
        atomic_write(self.path.with_name('client-summary-cache.json'),json.dumps(record).encode('utf-8'))

    def run(self):
        while not self.stop.is_set():
            try:self.publish()
            except Exception:pass  # UI refresh cannot interrupt computation or receipt persistence.
            if self.stop.wait(10):return

    def start(self):self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)
