"""Control snapshots save reads without hiding stop or thermal changes.

Run directly with Python, like the other Windows worker tests. This file is
portable into the public tests/ tree and contains no private workspace paths.
"""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))
import worker


class NoHardwareProbe:
    def sample(self):
        raise AssertionError('No hardware probe expected in this fixture')


def runtime():
    return {'_telemetry_device': NoHardwareProbe(), '_telemetry_at': time.monotonic(),
            'telemetry': {'cpu_temp_c': 79, 'gpu_temp_c': 55},
            '_metrics_lock': threading.RLock(), 'enabled': True}


def expire(current):
    path, _at, control, reader = current['_control_snapshot']
    current['_control_snapshot'] = (path, time.monotonic() - .051, control, reader)


def main():
    with tempfile.TemporaryDirectory(prefix='eg-control-cache-') as folder:
        state = Path(folder) / 'state.json'
        control = worker.control_path(state)
        def write(**fields):
            control.write_text(json.dumps(fields), encoding='utf-8')

        write(max_cpu_temp_c=80, max_gpu_temp_c=75)
        current = runtime()
        original = worker._read_control_with_status
        reads = [0]
        def counted(path):
            reads[0] += 1
            return original(path)

        with patch.object(worker, '_read_control_with_status', side_effect=counted):
            assert worker._thermal_probe(current, state)[0] == ''
            for _ in range(10):
                assert worker._thermal_probe(current, state)[0] == ''
            assert reads[0] == 1
            returned = worker._thermal_probe(current, state)[1]
            returned['paused'] = True
            assert not worker._thermal_probe(current, state)[1]['paused']

            # A fresh cache may defer a file change, but never beyond 50 ms.
            write(paused=True, max_cpu_temp_c=75, max_gpu_temp_c=75)
            assert not worker._thermal_probe(current, state)[1]['paused']
            expire(current)
            reason, refreshed = worker._thermal_probe(current, state)
            assert refreshed['paused'] and reason.startswith('CPU cooling')
            assert reads[0] == 2
            current['telemetry']['cpu_temp_c'] = 60
            assert worker._thermal_probe(current, state)[0] == '', 'Hysteresis remains live'

            # Separate state directories must not share a control snapshot.
            other = Path(folder) / 'other' / 'state.json'
            other.parent.mkdir()
            worker.control_path(other).write_text('{"stop_requested":true}', encoding='utf-8')
            assert worker._thermal_probe(current, other)[1]['stop_requested']
            assert reads[0] == 3

            stop = threading.Event()
            stop.set()
            current['_block_stop_event'] = stop
            before = reads[0]
            try:
                worker.cooperative_gate(current, other)
            except InterruptedError:
                pass
            else:
                raise AssertionError('Explicit stop event was ignored')
            assert reads[0] == before, 'Stop event must precede cached disk control'
            del current['_block_stop_event']

            # Failed/malformed reads never gain a new freshness period.
            control.unlink()
            before = reads[0]
            assert worker._thermal_probe(current, state)[1]['max_cpu_temp_c'] == 80
            assert worker._thermal_probe(current, state)[1]['max_cpu_temp_c'] == 80
            assert reads[0] == before + 2
            write(stop_requested=True)
            assert worker._thermal_probe(current, state)[1]['stop_requested']
            try:
                worker.cooperative_gate(current, state)
            except InterruptedError:
                pass
            else:
                raise AssertionError('Disk stop was ignored after refresh')
            control.write_text('{bad json', encoding='utf-8')
            current['_control_snapshot'] = None
            before = reads[0]
            worker._thermal_probe(current, state)
            worker._thermal_probe(current, state)
            assert reads[0] == before + 2

        # Existing one-argument mock readers must remain usable and uncached.
        calls = [0]
        def replacement(_path):
            calls[0] += 1
            return {'paused': False, 'stop_requested': True}
        write()
        current = runtime()
        worker._thermal_probe(current, state)  # prime a real snapshot
        with patch.object(worker, 'read_control', side_effect=replacement):
            assert worker._thermal_probe(current, state)[1]['stop_requested']
            assert worker._thermal_probe(current, state)[1]['stop_requested']
        assert calls[0] == 2

        # Four lanes see one parse in one fixed freshness epoch.
        write()
        current = runtime()
        reads = [0]
        with patch.object(worker, '_read_control_with_status', side_effect=counted), \
             patch.object(worker.time, 'monotonic', return_value=1000.0):
            current['_telemetry_at'] = 1000.0
            results = []
            threads = [threading.Thread(target=lambda: results.append(worker._thermal_probe(current, state)))
                       for _ in range(4)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=2)
            assert len(results) == 4 and reads[0] == 1
    print('PASS Windows control snapshot TTL, concurrency, stop and thermal guards')


if __name__ == '__main__':
    main()
