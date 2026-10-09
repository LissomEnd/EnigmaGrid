"""Device-scoped OpenCL cohort selection for portable_event_v1.

Grid receipts are never submitted from qualification. Four blocks remain the
safe default until an exact-workload profile is complete and current.
"""
import hashlib
import json
import math
import os
import platform
import statistics
import time
import multiprocessing
from pathlib import Path

FORMAT = "portable-opencl-batch-v1"
DEFAULT_BLOCKS = 4
CANDIDATES = (4, 8, 16)
TRIALS = 3
ASSETS = (
    "solver/runtime/src/search/portable_search.py",
    "solver/runtime/src/search/portable_score.cl",
    "solver/runtime/src/search/cpu_numba.py",
    "solver/runtime/src/search/event_stochastic.py",
    "solver/runtime/src/search/stochastic_c2.py",
    "solver/runtime/src/search/plug_transition.py",
    "solver/runtime/data/language/german_quadgrams.txt",
    "solver/runtime/data/messages/p1030680.json",
)


def scope_for(config, ciphertext, mode):
    if mode not in ("joint", "gpu"):
        raise ValueError("Invalid portable resource mode")
    count = int(config.get("count_per_unit", 4096))
    iterations = int(config.get("iterations", 512))
    topk = int(config.get("topk", 8))
    minimum = int(config.get("min_pairs", 0))
    maximum = int(config.get("max_pairs", 13))
    kinds = tuple(int(x) for x in config.get("event_kinds", (1, 2, 3, 4, 5, 6)))
    if not 1 <= count <= 32768 or not 1 <= iterations <= 2000:
        raise ValueError("Unsupported portable search scope")
    if not 1 <= topk <= 32 or not 0 <= minimum <= maximum <= 13:
        raise ValueError("Unsupported portable search bounds")
    if not kinds or any(x not in (1, 2, 3, 4, 5, 6) for x in kinds):
        raise ValueError("Unsupported event kinds")
    return dict(mode=mode, base_attempt=int(config.get("base_attempt", 71000000000)),
                count=count, iterations=iterations, topk=topk,
                min_pairs=minimum, max_pairs=maximum, event_kinds=list(kinds),
                ciphertext_sha256=hashlib.sha256(ciphertext.encode("utf-8")).hexdigest())


def asset_fingerprint(root, worker_source, *, frozen=False, executable=None):
    digest = hashlib.sha256()
    for relative in ASSETS:
        contents = (Path(root) / relative).read_bytes()
        digest.update(relative.encode("ascii") + b"\0")
        digest.update(len(contents).to_bytes(8, "big") + contents)
    # PyInstaller bundles scoring_pool as bytecode in the executable, not as
    # worker/scoring_pool.py beside the reviewed solver data files.
    code_paths=(("worker-executable",Path(executable)),) if frozen else (
        ("worker",Path(worker_source)),("qualification",Path(__file__)),
        ("scoring-pool",Path(root)/"worker/scoring_pool.py"))
    for label,path in code_paths:
        contents=path.read_bytes()
        digest.update(label.encode("ascii")+b"\0")
        digest.update(len(contents).to_bytes(8,"big")+contents)
    return digest.hexdigest()


def device_fingerprint(scorers):
    import numpy
    import numba
    import pyopencl
    devices = []
    for scorer in scorers:
        device = scorer.device
        devices.append([str(getattr(device, name)) for name in
                        ("vendor", "name", "version", "driver_version", "global_mem_size")])
    if not devices:
        raise ValueError("No qualified OpenCL scorer")
    # Driver/code changes invalidate this private profile without recording IDs.
    environment=[platform.platform(),platform.processor(),os.cpu_count(),
                 numpy.__version__,numba.__version__,getattr(pyopencl,"VERSION_TEXT","unknown")]
    return hashlib.sha256(json.dumps([devices,environment],sort_keys=True).encode("utf-8")).hexdigest()


def choose(trials):
    if not isinstance(trials, list) or len(trials) != TRIALS:
        raise ValueError("Incomplete cohort qualification")
    timings = {candidate: [] for candidate in CANDIDATES}
    for index, row in enumerate(trials):
        if not isinstance(row, dict) or row.get("trial") != index:
            raise ValueError("Invalid trial order")
        observed = row.get("seconds")
        if row.get("receipt_equal") is not True or not isinstance(observed, dict):
            raise ValueError("Missing canonical receipt parity")
        for candidate in CANDIDATES:
            value = observed.get(str(candidate))
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid cohort timing")
            timings[candidate].append(value)
    qualified = [candidate for candidate in (8, 16)
                 if all(b <= a * .95 for a, b in zip(timings[4], timings[candidate]))
                 and statistics.median(timings[candidate]) < statistics.median(timings[4]) * .95]
    return min(qualified, key=lambda c: statistics.median(timings[c])) if qualified else DEFAULT_BLOCKS


def qualify(execute, scope, hardware, assets,
            checkpoint=lambda: None, clock=time.perf_counter):
    """One bounded, balanced comparison on the actual job scope.

    execute(blocks, checkpoint) must run the *whole* one-unit CPU+GPU pipeline
    (or GPU-only pipeline), return its canonical result and use independent
    OpenCL scorers. The parent watchdog owns cancellation, thermal gating and
    its measured, capped deadline. Any interruption leaves the default in place.
    """
    if scope["count"] < 4096:
        raise ValueError("Insufficient independent cohorts to compare 4/8/16")
    expected = None
    rows = []
    for trial in range(TRIALS):
        order = (1, 4, 8, 16) if trial != 1 else (16, 8, 4, 1)
        row = dict(trial=trial, receipt_equal=True, seconds={})
        for blocks in order:
            checkpoint()
            started = clock()
            actual = execute(blocks, checkpoint)
            elapsed = clock() - started
            checkpoint()
            if expected is None:
                expected = actual
            if actual != expected:
                raise ValueError("Portable cohort full canonical receipt parity failed")
            if blocks != 1:
                row["seconds"][str(blocks)] = elapsed
        rows.append(row)
    selected = choose(rows)
    return dict(format=FORMAT, hardware=hardware, assets=assets, scope=scope,
                parity_passed=True, trials=rows, selected_blocks=selected)


def load_profile(path, hardware, assets, scope):
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        if report.get("format") != FORMAT or report.get("hardware") != hardware:
            return None
        if report.get("assets") != assets or report.get("scope") != scope:
            return None
        if report.get("parity_passed") is not True:
            return None
        selected = choose(report.get("trials"))
        if report.get("selected_blocks") != selected:
            return None
        return selected
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return None


def save_profile(path, report):
    from file_state import atomic_write
    atomic_write(path, json.dumps(report, allow_nan=False, sort_keys=True).encode("utf-8"))


def stop_owned_process(process, grace_seconds=.5):
    """Stop only the qualification child, including a blocked driver call."""
    if process is None:
        return True
    if process.is_alive():
        process.terminate()
        process.join(grace_seconds)
    if process.is_alive():
        process.kill()
        process.join(grace_seconds)
    return not process.is_alive()


def qualification_child(send, run_portable, sample_lease, settings, scope,
                        expected_hardware, assets, deadline_seconds):
    """No server, identity, outbox, durable receipts, or production GPU context."""
    try:
        worker = run_portable.__globals__
        if os.name == "nt":
            # The one-time pilot must yield CPU time to the real grid worker.
            import ctypes
            below_normal_priority_class = 0x00004000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(),
                                      below_normal_priority_class)
        if asset_fingerprint(worker["ROOT"], worker["__file__"],
                             frozen=worker["FROZEN"], executable=os.sys.executable) != assets:
            raise ValueError("Qualification source changed")
        worker["hardware"]()  # A fresh context in this spawned process.
        scorers = worker["_GPU_SCORERS"]
        if device_fingerprint(scorers) != expected_hardware:
            raise ValueError("Qualification device fingerprint changed")
        if not scorers:
            raise ValueError("No GPU scorer in qualification child")
        from search.portable_search import OpenCLScorer, initial_keys, score_cpu
        from search.cpu_numba import encode
        from scoring_pool import OrderedScorers
        import numpy as np
        root = worker["ROOT"]
        text = json.loads((root / "solver/runtime/data/messages/p1030680.json").read_text(
            encoding="utf-8"))["ciphertext"]
        if scope_for(sample_lease["config"], text, scope["mode"]) != scope:
            raise ValueError("Qualification scope changed")
        encoded = encode(text)
        fresh = [OpenCLScorer(encoded, scorer.device) for scorer in scorers]
        probe = initial_keys(np.random.Generator(np.random.PCG64(73021)),
                             4096, scope["min_pairs"], scope["max_pairs"],
                             np.asarray(scope["event_kinds"], np.int32))
        pool = OrderedScorers(fresh)
        try:
            observed = np.concatenate(pool.score(probe))
        finally:
            pool.close()
        if not np.array_equal(observed, score_cpu(encoded, probe)):
            raise ValueError("Portable GPU score parity failed")
        deadline = time.monotonic() + deadline_seconds
        def checkpoint():
            if time.monotonic() >= deadline:
                raise InterruptedError("Qualification deadline reached")
        local_runtime = {"settings": settings, "enabled": True}
        def execute(blocks, check):
            return run_portable(sample_lease, local_runtime, None,
                gpu_scorers=fresh, gpu_blocks_override=blocks,
                qualification_check=check)[0]
        try:
            result = qualify(execute, scope, expected_hardware, assets,
                             checkpoint=checkpoint)
            checkpoint()
            send.send(result)
        finally:
            worker["release_portable_executor"](local_runtime)
    except BaseException:
        # Failure or driver crash has no effect on real work; keep default 4.
        pass
    finally:
        send.close()


def spawn_qualification(run_portable, sample_lease, settings, scope,
                        hardware, assets, seconds=30):
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=qualification_child,
        args=(send, run_portable, sample_lease, settings, scope,
              hardware, assets, seconds), daemon=True,
        name="portable-gpu-batch-qualification")
    try:
        process.start()
    except BaseException:
        receive.close(); send.close()
        raise
    send.close()
    return process, receive


def _spawn_target_probe(send, portable_function):
    try:
        send.send(portable_function.__name__ == "run_portable")
    finally:
        send.close()


def selftest_spawn(run_portable, timeout=8):
    """Validate frozen helper import and main-function pickling without GPU."""
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_spawn_target_probe,
        args=(send, run_portable), daemon=True, name="portable-spawn-selftest")
    try:
        process.start()
        send.close()
        if not receive.poll(timeout):
            return False
        return receive.recv() is True
    except (OSError, ValueError, EOFError, TypeError, AttributeError):
        return False
    finally:
        stop_owned_process(process)
        receive.close()
        send.close()


def _simulated_driver_hang():
    time.sleep(300)


def selftest_termination():
    """Verify that a spawned child stuck in a driver-like call is reaped."""
    process = multiprocessing.get_context("spawn").Process(
        target=_simulated_driver_hang, daemon=True,
        name="portable-stop-selftest")
    try:
        process.start()
        return stop_owned_process(process) and process.exitcode is not None
    except (OSError, RuntimeError):
        return False
