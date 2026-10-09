"""Isolated, source-only teardown checks; no production device or network I/O."""
from pathlib import Path
import multiprocessing
import sys
import tempfile
import threading
import time

SOURCE = Path(__file__).resolve().parents[1] / 'worker'
sys.path[:0] = [str(SOURCE), str(SOURCE.parent / 'solver/runtime/src')]

from summary_cache import SummaryPublisher
from performance_telemetry import DeviceTelemetry
from updater import UpdateManager, _await_owned_prompt
from block_pipeline import BlockPipeline
import worker

def _blocking_prompt(send):
    try:time.sleep(30)
    finally:send.close()

def _answered_prompt(send):
    try:send.send(("ok", True))
    finally:send.close()


def test_summary_join():
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "client.json"
        state.write_text("{}", encoding="utf-8")
        entered, release = threading.Event(), threading.Event()

        def fetch(_path, _cancel):
            entered.set()
            assert release.wait(5)
            return {"ok": True}

        publisher = SummaryPublisher(state, "0.5.0", fetch, cancel_aware=True)
        publisher.start()
        assert entered.wait(2)
        timer = threading.Timer(1.2, release.set)
        timer.start()
        try:
            before = time.monotonic()
            publisher.close()
            assert time.monotonic() - before >= 1.0
            assert not publisher.thread.is_alive()
        finally:
            release.set(); timer.join(3)


def test_summary_cancels_second_http():
    stop = threading.Event()
    original = worker.load_state, worker.get_json, worker.post
    calls = []
    try:
        worker.load_state = lambda _path: {"server": "http://127.0.0.1:1",
                                           "dashboard_token": "opaque", "settings": {}}
        def first(_server, _path, _timeout):
            calls.append("first")
            stop.set()
            return {"ok": True}
        worker.get_json = first
        worker.post = lambda *_args, **_kwargs: calls.append("second")
        summary = worker.client_summary("unused", stop)
        assert summary["global"] == {"ok": True}
        assert calls == ["first"]
    finally:
        worker.load_state, worker.get_json, worker.post = original


def test_sensor_close_after_sampler_join():
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    def sample():
        entered.set()
        assert release.wait(5)
        return {}
    telemetry = DeviceTelemetry({}, sample, lambda *_: None,
                                lambda: {}, lambda _payload: {}, "0.5.0",
                                close_sample=closed.set)
    telemetry.start()
    assert entered.wait(2)
    timer = threading.Timer(1.2, release.set)
    timer.start()
    try:
        before = time.monotonic()
        telemetry.close()
        assert time.monotonic() - before >= 1.0
        assert closed.is_set()
        assert not telemetry.sampler.is_alive()
        assert not telemetry.sender.is_alive()
    finally:
        release.set(); timer.join(3)


def test_updater_join():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = UpdateManager("0.5.0", Path(tmp) / "state.json", "http://127.0.0.1:1")
        entered, release = threading.Event(), threading.Event()
        def slow_check():
            entered.set()
            assert release.wait(5)
        mgr.check_once = slow_check
        mgr.start()
        assert entered.wait(2)
        timer = threading.Timer(1.2, release.set)
        timer.start()
        try:
            before = time.monotonic()
            mgr.shutdown()
            assert time.monotonic() - before >= 1.0
            assert not mgr.thread.is_alive()
        finally:
            release.set(); timer.join(3)


def test_failed_join_is_reported_and_sensor_stays_owned():
    class Stuck:
        ident = 1
        name = "stuck-sampler"
        def join(self, timeout):
            assert 0 < timeout < 40
        def is_alive(self):
            return True
    closed = threading.Event()
    telemetry = DeviceTelemetry({}, lambda: {}, lambda *_: None,
                                lambda: {}, lambda _payload: {}, "0.5.0",
                                close_sample=closed.set)
    telemetry.sampler = Stuck()
    try:
        telemetry.close()
        raise AssertionError("stuck sampler was silently ignored")
    except RuntimeError as error:
        assert "stuck-sampler" in str(error)
    assert not closed.is_set()


def test_worker_cleanup_continues_after_monitor_failure():
    actions = []
    class BrokenTelemetry:
        def close(self):
            actions.append("telemetry")
            raise RuntimeError("test fault")
    class FakeSummary:
        def close(self):actions.append("summary")
    original = (worker._work, worker.suspend_long_blocks,
                worker.release_portable_executor, worker.release_unused_work,
                worker.release_constrained_pool)
    try:
        def fake_work(_args, _state, runtime):
            runtime["_device_telemetry"] = BrokenTelemetry()
            runtime["_summary_publisher"] = FakeSummary()
            return 0
        worker._work = fake_work
        worker.suspend_long_blocks = lambda _runtime: actions.append("blocks")
        worker.release_portable_executor = lambda _runtime: actions.append("portable")
        worker.release_unused_work = lambda _state, _runtime: actions.append("leases")
        worker.release_constrained_pool = lambda _runtime: actions.append("constrained")
        try:
            worker.work(None, {"settings": {}})
            raise AssertionError("monitor close failure was silently ignored")
        except RuntimeError as error:
            assert "telemetry:RuntimeError" in str(error)
        assert actions == ["blocks", "portable", "telemetry", "summary", "leases", "constrained"]
    finally:
        (worker._work, worker.suspend_long_blocks,
         worker.release_portable_executor, worker.release_unused_work,
         worker.release_constrained_pool) = original


def test_qualification_thread_must_join_before_sensor_release():
    class Stuck:
        def join(self, timeout):
            assert timeout >= 2
        def is_alive(self):
            return True
    active = {"thread": Stuck()}
    runtime = {"_portable_batch_qualification": active}
    original = worker.cancel_portable_batch_qualification
    try:
        worker.cancel_portable_batch_qualification = lambda _runtime: None
        try:
            worker.release_portable_executor(runtime)
            raise AssertionError("live qualification thread was dropped")
        except RuntimeError as error:
            assert "did not terminate" in str(error)
        assert runtime["_portable_batch_qualification"] is active
    finally:
        worker.cancel_portable_batch_qualification = original


def test_owned_prompt_cancel_and_answer():
    context = multiprocessing.get_context("spawn")
    for target, cancel in ((_blocking_prompt,True),(_answered_prompt,False)):
        receive,send = context.Pipe(duplex=False)
        child = context.Process(target=target,args=(send,),daemon=True)
        child.start();send.close()
        stop = threading.Event()
        timer = threading.Timer(.4, stop.set) if cancel else None
        if timer:timer.start()
        try:
            if cancel:
                try:_await_owned_prompt(child,receive,stop)
                except InterruptedError:pass
                else:raise AssertionError("owned prompt was not cancelled")
            else:
                assert _await_owned_prompt(child,receive,stop) is True
            assert not child.is_alive() and child.exitcode is not None
        finally:
            if timer:timer.join(3)


def test_block_qualification_owner_is_retained_if_stuck():
    class Stuck:
        def join(self, timeout):assert 0 < timeout <= 8
        def is_alive(self):return True
    class Pipeline:
        def close(self):raise AssertionError("unsafe close while qualifier alive")
    active = {"thread": Stuck(), "cancel": threading.Event()}
    pipeline = Pipeline()
    runtime = {"_block_qualification": active, "_block_pipeline": pipeline,
               "_shared_constrained_pool": object()}
    try:worker.suspend_long_blocks(runtime)
    except RuntimeError as error:assert "did not terminate" in str(error)
    else:raise AssertionError("stuck qualification was silently dropped")
    assert active["cancel"].is_set()
    assert runtime["_block_qualification"] is active
    assert runtime["_block_pipeline"] is pipeline
    assert "_shared_constrained_pool" in runtime


def test_durable_failure_does_not_retire_blocks():
    class Queue:
        def __init__(self):self.retired=False
        def retire(self):self.retired=True
    class Pipeline:
        def __init__(self,queue,complete):
            self.queue=queue;self.shutdown_complete=complete
        def close(self):raise OSError("disposable disk fault")
    original = worker.release_shared_constrained
    try:
        released=[]
        worker.release_shared_constrained=lambda _runtime:released.append(True)
        for complete in (False,True):
            queue=Queue();pipeline=Pipeline(queue,complete)
            runtime={"_block_pipeline":pipeline}
            try:worker.suspend_long_blocks(runtime)
            except (OSError,RuntimeError):pass
            else:raise AssertionError("durable writer failure was suppressed")
            assert not queue.retired
            assert ("_block_pipeline" in runtime) is (not complete)
        assert released==[True]
    finally:
        worker.release_shared_constrained=original


def test_reconfiguration_retains_unjoined_block_owner():
    class UnjoinedPipeline:
        shutdown_complete=False
        def close(self):raise RuntimeError('compute thread still running')
    pipeline=UnjoinedPipeline()
    owner=object()
    runtime={'_block_pipeline':pipeline,'_shared_constrained_pool':owner}
    try:worker.close_long_block_pipeline(runtime,pipeline)
    except RuntimeError as error:assert 'still running' in str(error)
    else:raise AssertionError('reconfiguration lost an unjoined block owner')
    assert runtime['_block_pipeline'] is pipeline
    assert runtime['_shared_constrained_pool'] is owner


def test_pipeline_records_all_joins_before_writer_failure():
    from concurrent.futures import Future
    class Queue:pass
    class Transport:pass
    pipeline=BlockPipeline(Queue(),Transport(),lambda _item:None)
    failed=Future();failed.set_exception(OSError("disposable disk fault"))
    pipeline.writes.append(failed)
    try:pipeline.close()
    except OSError:pass
    else:raise AssertionError("durable write error was suppressed")
    assert pipeline.shutdown_complete and pipeline.closed
    try:pipeline.close()
    except OSError:pass
    else:raise AssertionError("repeat close hid durable error")


if __name__ == "__main__":
    test_summary_join()
    test_summary_cancels_second_http()
    test_sensor_close_after_sampler_join()
    test_updater_join()
    test_failed_join_is_reported_and_sensor_stays_owned()
    test_worker_cleanup_continues_after_monitor_failure()
    test_qualification_thread_must_join_before_sensor_release()
    test_owned_prompt_cancel_and_answer()
    test_block_qualification_owner_is_retained_if_stuck()
    test_durable_failure_does_not_retire_blocks()
    test_reconfiguration_retains_unjoined_block_owner()
    test_pipeline_records_all_joins_before_writer_failure()
    print("PASS owned background shutdown and sensor release ordering")
