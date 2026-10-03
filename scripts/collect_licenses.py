"""Bundle installed distribution notices alongside the Windows application."""
import importlib.metadata as metadata
import sys
from pathlib import Path
from packaging.requirements import Requirement

root = Path(__file__).resolve().parents[1]
parts = [(root / 'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8'),
         (root / 'LICENSE').read_text(encoding='utf-8')]
pending = ['numpy', 'numba', 'cryptography', 'pyopencl', 'Pillow', 'pystray', 'pyinstaller']
seen = set()
while pending:
    name = pending.pop().lower().replace('_', '-')
    if name in seen:
        continue
    seen.add(name)
    dist = metadata.distribution(name)
    parts.append('\n\n=== ' + dist.metadata['Name'] + ' ' + dist.version + ' ===\n')
    parts.append(dist.read_text('METADATA') or '')
    for entry in dist.files or []:
        if any(word in entry.name.lower() for word in ('license', 'copying', 'notice')):
            path = Path(dist.locate_file(entry))
            if path.is_file():
                parts.append(str(entry) + '\n' + path.read_text(encoding='utf-8', errors='replace'))
    for spec in dist.requires or []:
        dep = Requirement(spec)
        if dep.marker is None or dep.marker.evaluate({'extra': ''}):
            pending.append(dep.name)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if not python_license.exists():
    raise SystemExit('Python runtime license missing')
parts.append('\n=== Python runtime ===\n' + python_license.read_text(encoding='utf-8'))
parts.append((root / 'solver/runtime/data/language/COPYING.GPL-3.0.txt').read_text(encoding='utf-8'))
Path(sys.argv[1]).write_text('\n'.join(parts), encoding='utf-8')
