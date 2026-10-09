"""Portable bounded-solver memory policy regression; no child or device starts."""
import ast
import ctypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker'))
import worker

G = 1024 ** 3
limit = worker.constrained_process_limit

# Existing higher-headroom policy is byte-for-byte equivalent.
assert limit(24, 8.89 * G, 15.85 * G, bounded_pilot=True,
             commit_headroom_bytes=4 * G) == 9
assert limit(32, 5 * G, 16 * G, bounded_pilot=False) == 2
assert limit(32, 3 * G, 16 * G, bounded_pilot=False) == 0

# A bounded-only two-child pilot needs both physical and commit budget.
for fraction in (.15, .25):
    assert limit(16, int(2.20 * G), int(15.67 * G),
                 reserve_fraction=fraction, bounded_pilot=True,
                 commit_headroom_bytes=4 * G) == 2
assert limit(16, int(2.10 * G), int(15.67 * G),
             bounded_pilot=True, commit_headroom_bytes=4 * G) == 0
assert limit(16, int(2.20 * G), int(15.67 * G),
             bounded_pilot=True, commit_headroom_bytes=int(2.10 * G)) == 0
assert limit(16, int(2.20 * G), int(15.67 * G),
             bounded_pilot=True, probe_commit=False) == 0
assert limit(16, int(.57 * G), int(7.60 * G),
             bounded_pilot=True, commit_headroom_bytes=4 * G) == 0

# An existing two-child pool is not resized during a modest memory dip.
assert limit(16, int(2.10 * G), int(15.67 * G), existing_workers=2,
             bounded_pilot=True, commit_headroom_bytes=4 * G) == 2
assert limit(16, int(1.90 * G), int(15.67 * G), existing_workers=2,
             reserve_fraction=.15, bounded_pilot=True,
             commit_headroom_bytes=4 * G) == 1

# Older lightweight tests extract only this function with AST. Its default
# arguments must compile without module-level sentinels or Windows APIs.
tree = ast.parse((ROOT / 'worker' / 'worker.py').read_text(encoding='utf-8'))
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
            and n.name == 'constrained_process_limit')
scope = {'os': os, 'ctypes': ctypes}
exec(compile(ast.Module(body=[node], type_ignores=[]), '<limit-only>', 'exec'), scope)
assert scope['constrained_process_limit'](32, 5 * G, 16 * G) == 2

print('PASS bounded memory policy: preserved baseline, bounded pilot, pressure fallback, AST defaults')
