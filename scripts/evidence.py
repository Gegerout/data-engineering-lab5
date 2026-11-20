import contextlib
import html
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from experiments import K, P, cmd

E = P / 'logs/evidence'
E.mkdir(exist_ok=True)
S = P / 'screenshots'
S.mkdir(exist_ok=True)


def record(name, commands):
    with (E / f'{name}.txt').open('w') as f, contextlib.redirect_stdout(f):
        for args in commands:
            cmd(args)


record('01_cluster', [K + ['get', 'nodes'], K + ['get', 'node', 'lab5-worker', '-o',
       'custom-columns=NAME:.metadata.name,CPU:.status.capacity.cpu,ALLOCATABLE:.status.allocatable.cpu'],
       ['docker', 'image', 'inspect', 'lab5-pairs:1', '--format', '{{.Id}} {{.Architecture}}']])
record('02_memory', [K + ['-n', 'lab5', 'get', 'pods', '-l', '!app', '-o',
       'custom-columns=POD:.metadata.name,PHASE:.status.phase,REASON:.status.containerStatuses[0].state.terminated.reason,EXIT:.status.containerStatuses[0].state.terminated.exitCode,LIMIT:.spec.containers[0].resources.limits.memory'],
       ['cat', 'results/memory.json']])
record('03_storage', [['head', '-n', '6', 'logs/04_migrate.txt'],
       K + ['-n', 'lab5', 'get', 'deployment', 'rustfs'], K + ['-n', 'lab5', 'get', 'pvc']])
record('04_parallel', [K + ['-n', 'lab5', 'get', 'jobs'], K + ['-n', 'lab5', 'get', 'pods', '-l', 'job-name=pairs-parallel',
       '-o', 'custom-columns=POD:.metadata.name,START:.status.containerStatuses[0].state.terminated.startedAt,FINISH:.status.containerStatuses[0].state.terminated.finishedAt'],
       ['rg', '^mode=|^METRICS', 'logs/05_parallel.txt']])
record('05_verify', [[sys.executable, 'scripts/verify.py']])
text = (P / 'logs/06_scheduling.txt').read_text()
cut = text.index("apply -f manifests/low.yaml")
cut = text.rfind('$ ', 0, cut)
for name, body in [('06_pending', text[:cut]), ('07_preemption', text[cut:])]:
    body = '\n'.join(line for line in body.splitlines() if not line.startswith('{'))
    (E / f'{name}.txt').write_text(body + '\n')
(E / '08_quota.txt').write_text((P / 'logs/07_quota.txt').read_text())

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/opt/homebrew/bin/chromium', headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 900}, device_scale_factor=2)
    for file in sorted(E.glob('*.txt')):
        lines = file.read_text().rstrip().splitlines()
        chunks = [lines[i:i+24] for i in range(0, len(lines), 24)]
        for i, chunk in enumerate(chunks, 1):
            text = '\n'.join(chunk)
            page.set_content('<!doctype html><meta charset="utf-8"><style>body{margin:0;background:white}'
                             'pre{margin:0;padding:12px;width:820px;box-sizing:border-box;color:#111;'
                             'font:14px/1.45 Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere}</style>'
                             '<pre>'+html.escape(text)+'</pre>')
            assert page.inner_text('pre') == text
            suffix = f'_{i}' if len(chunks)>1 else ''
            page.locator('pre').screenshot(path=str(S / f'{file.stem}{suffix}.png'))
            print(file.stem + suffix)
    browser.close()
