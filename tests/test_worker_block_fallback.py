"""A bounded pipeline may fall back to legacy work only when fully idle.

Compile the real worker function, while replacing its imports and IO with tiny
fixtures. This keeps the regression independent of enrollment and live state.
"""
import ast
import sys
import time
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "worker" / "worker.py"


def load_tick():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "long_block_tick")
    fake_search = types.ModuleType("search")
    fake_search.__path__ = []
    fake_work_block = types.ModuleType("search.work_block")
    fake_work_block.FORMAT = "work_block_v1"
    fake_queue = types.ModuleType("block_queue")
    fake_queue.BlockQueue = object
    fake_queue.AckCounter = object
    fake_transport = types.ModuleType("block_transport")
    fake_transport.BlockTransport = object
    fake_pipeline = types.ModuleType("block_pipeline")
    fake_pipeline.BlockPipeline = object
    modules = {
        "search": fake_search,
        "search.work_block": fake_work_block,
        "block_queue": fake_queue,
        "block_transport": fake_transport,
        "block_pipeline": fake_pipeline,
    }
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    namespace = {
        "sys": sys,
        "ROOT": ROOT,
        "Path": Path,
        "time": time,
        "read_control": lambda _: {"paused": False, "stop_requested": False},
        "poll_block_qualification": lambda *args: False,
        "publish_health": lambda *args: None,
    }
    try:
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
        return namespace["long_block_tick"], previous
    except BaseException:
        restore(previous)
        raise


def restore(previous):
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class Task:
    def done(self):
        return False


class Queue:
    max_pending = 8

    def monitor_snapshot(self):
        # The last unit has already been claimed; ready excludes active claims.
        return {"ready_units": 0, "outbox_count": 0}


class Pipeline:
    def __init__(self, *, running=False, fetching=False, writing=False):
        self.queue = Queue()
        self.running = {Task(): ["claimed unit"]} if running else {}
        self.fetch = object() if fetching else None
        self.writes = [object()] if writing else []
        self.computing = running
        self.wait_reason = "legacy_priority_work"
        self.terminal_error = None

    def poll_control(self, refresh):
        return None

    def poll_status(self):
        return None

    def tick(self, *, allow_compute):
        assert allow_compute
        return False


def check(tick, *, qualification=False, **pipeline_flags):
    settings = {"allow_cpu": True, "cpu_percent": 100, "allow_gpu": True, "gpu_percent": 100}
    runtime = {
        "_block_pipeline": Pipeline(**pipeline_flags),
        "_block_settings": tuple(settings.get(key) for key in ("allow_cpu", "cpu_percent", "allow_gpu", "gpu_percent")),
        "settings": settings,
        "enabled": True,
    }
    if qualification:
        runtime["_block_qualification"] = {"thread": "still running"}
    return tick(Path("fixture-state.json"), {}, runtime)


if __name__ == "__main__":
    tick, previous = load_tick()
    try:
        assert check(tick, running=True) is True
        assert check(tick, fetching=True) is True
        assert check(tick, writing=True) is True
        assert check(tick, qualification=True) is True
        assert check(tick) is False  # Only fully idle state may use legacy work.
    finally:
        restore(previous)
    print("PASS bounded fallback waits for running, fetch, writer and qualification; idle fallback remains")
