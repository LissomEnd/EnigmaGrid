"""Source-only ownership checks; no OpenCL device, network, or grid state."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract(path, name):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(item for item in tree.body if isinstance(item, (ast.ClassDef, ast.FunctionDef)) and item.name == name)
    return ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))


events = []


class Queue:
    def __init__(self):self.fail = False
    def finish(self):
        events.append('finish')
        if self.fail:raise RuntimeError('driver still busy')


class Buffer:
    def __init__(self, name):self.name = name
    def release(self):events.append('release:' + self.name)


scorer_ns = {}
exec(compile(extract(ROOT/'solver/runtime/src/search/portable_search.py', 'OpenCLScorer'), '<staged-scorer>', 'exec'), scorer_ns)
OpenCLScorer = scorer_ns['OpenCLScorer']


def make_scorer():
    scorer = OpenCLScorer.__new__(OpenCLScorer)
    scorer.queue = Queue();scorer.kernel = object();scorer.program = object()
    scorer.context = object();scorer.key_buffer = Buffer('keys')
    scorer.score_buffer = Buffer('scores');scorer.constants = [Buffer('constant')]
    scorer._closed = False
    return scorer


def check_scorer():
    scorer = make_scorer();scorer.queue.fail = True
    try:scorer.close()
    except RuntimeError:pass
    else:raise AssertionError('failed queue finish was ignored')
    assert events == ['finish'] and not scorer._closed
    scorer.queue.fail = False;scorer.close();scorer.close()
    assert events == ['finish','finish','release:keys','release:scores','release:constant']
    assert scorer._closed and scorer.queue is None and scorer.context is None
    try:scorer([])
    except RuntimeError as error:assert 'closed' in str(error)
    else:raise AssertionError('closed scorer accepted work')


def check_global_ownership():
    fake = make_scorer();other = make_scorer();other.queue.fail = True
    namespace = {'_GPU_SCORERS':[fake,other]}
    exec(compile(extract(ROOT/'worker'/'worker.py', 'close_global_opencl_scorers'), '<staged-worker>', 'exec'), namespace)
    try:namespace['close_global_opencl_scorers']()
    except RuntimeError:pass
    else:raise AssertionError('failed scorer was discarded')
    assert namespace['_GPU_SCORERS'] == [other]
    other.queue.fail = False;namespace['close_global_opencl_scorers']()
    assert namespace['_GPU_SCORERS'] == []

def check_final_cleanup_gate():
    namespace = {}
    exec(compile(extract(ROOT/'worker'/'worker.py', 'work'), '<staged-worker>', 'exec'), namespace)
    for failing in ('', 'blocks', 'portable', 'durable_after_join'):
        actions = []
        def step(name):
            actions.append(name)
            if name == failing:raise RuntimeError('synthetic incomplete owner')
        def start(_args,_state,runtime):
            runtime['_block_pipeline']=object()
            return 0
        def stop_blocks(runtime):
            step('blocks')
            runtime.pop('_block_pipeline')
            if failing=='durable_after_join':
                raise OSError('durable write failed after all owners joined')
        namespace.update(
            normalize_settings=lambda value:value,
            _work=start,
            suspend_long_blocks=stop_blocks,
            release_portable_executor=lambda _runtime:step('portable'),
            release_unused_work=lambda _state,_runtime:step('leases'),
            release_constrained_pool=lambda _runtime:step('constrained'),
            close_global_opencl_scorers=lambda:step('opencl'),
            close_global_native_solvers=lambda:step('native'),
            disable_global_native_auto_close=lambda:step('native_disabled'))
        try:namespace['work'](None, {'settings':{}})
        except RuntimeError:
            assert failing
        else:assert not failing
        assert ('opencl' in actions) == (failing in ('', 'durable_after_join'))


if __name__ == '__main__':
    check_scorer();events.clear();check_global_ownership();check_final_cleanup_gate()
    print('PASS OpenCL queue drain, idempotent release, failed-owner retention and final cleanup gate')
