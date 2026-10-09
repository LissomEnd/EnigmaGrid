"""No-GPU regression: a hung spawned qualification child cannot survive stop."""
import multiprocessing
import os
import sys
import time
from pathlib import Path

ROOT=Path(os.environ.get("ENIGMAGRID_SOURCE_ROOT",Path(__file__).resolve().parent.parent)).resolve()
sys.path.insert(0,str(ROOT/"worker"))

from portable_batch_qualification import (selftest_spawn, selftest_termination,
                                           stop_owned_process)


def simulated_driver_hang():
    time.sleep(300)


def run_portable():
    pass


if __name__ == "__main__":
    assert selftest_spawn(run_portable)
    assert selftest_termination()
    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=simulated_driver_hang,
                        name="simulated-opencl-driver-hang", daemon=True)
    child.start()
    assert child.is_alive()
    start = time.monotonic()
    assert stop_owned_process(child, .5)
    assert not child.is_alive() and child.exitcode is not None
    assert time.monotonic() - start < 3
    print("PASS owned spawned child terminates during simulated GPU hang")
