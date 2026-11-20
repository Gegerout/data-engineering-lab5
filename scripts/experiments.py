import csv
import hashlib
import io
import json
import math
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import boto3
from botocore.config import Config

P = Path(__file__).resolve().parents[1]
K = [str(P / 'tmp/bin/kubectl'), '--kubeconfig', str(P / 'tmp/kubeconfig')]


def cmd(args, check=True):
    print('$ ' + shlex.join([str(x) for x in args]).replace(str(P) + '/', ''), flush=True)
    r = subprocess.run(args, cwd=P, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(r.stdout, end='', flush=True)
    if check and r.returncode:
        raise RuntimeError(f'command exit={r.returncode}')
    return r


def data(*args):
    return json.loads(subprocess.check_output(K + list(args) + ['-o', 'json'], cwd=P))


def apply(name):
    return cmd(K + ['apply', '-f', 'manifests/' + name])


def wait_job(name):
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        j = data('-n', 'lab5', 'get', 'job', name)
        if any(c['type'] in ['Complete', 'Failed'] and c['status'] == 'True' for c in j.get('status', {}).get('conditions', [])):
            break
        time.sleep(1)
    else:
        cmd(K + ['-n', 'lab5', 'describe', 'job', name])
        raise RuntimeError('job timeout')
    pods = data('-n', 'lab5', 'get', 'pods', '-l', 'job-name=' + name)
    (P / 'logs' / (name + '.json')).write_text(json.dumps({'job': j, 'pods': pods}, indent=2))
    print('$ kubectl -n lab5 get pods -l job-name=' + name + ' -o json', flush=True)
    for p in pods['items']:
        for c in p['status'].get('containerStatuses', []):
            print(json.dumps({'pod': p['metadata']['name'], 'phase': p['status']['phase'],
                              'state': c['state'], 'resources': p['spec']['containers'][0]['resources']}, ensure_ascii=False), flush=True)
        cmd(K + ['-n', 'lab5', 'logs', p['metadata']['name']], check=False)
    return j, pods


def s3(endpoint):
    env = dict(x.split('=', 1) for x in (P / '.env').read_text().splitlines() if '=' in x)
    return boto3.client('s3', endpoint_url=endpoint, aws_access_key_id=env['RUSTFS_ACCESS_KEY'],
                       aws_secret_access_key=env['RUSTFS_SECRET_KEY'], region_name='us-east-1',
                       config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}))


def verify(endpoint, key, name):
    body = s3(endpoint).get_object(Bucket='hh-lake', Key=key)['Body'].read()
    (P / 'results' / f'{name}_pairs.csv').write_bytes(body)
    ref = (P / 'input/lab3_pairs.csv').read_bytes()
    a = list(csv.reader(io.StringIO(body.decode())))
    b = list(csv.reader(io.StringIO(ref.decode())))
    print(f'COMPARE {name} rows={len(a)-1} all_equal={a == b} top10_equal={a[1:11] == b[1:11]}', flush=True)
    print('sha256=' + hashlib.sha256(body).hexdigest(), flush=True)
    for row in a[1:11]:
        print(' + '.join(row[:2]) + ' = ' + row[2], flush=True)
    assert a == b
    return body


def memory():
    apply('job-oom.yaml')
    j, ps = wait_job('pairs-oom')
    assert ps['items'][0]['status']['containerStatuses'][0]['state']['terminated']['reason'] == 'OOMKilled'
    apply('job-measure.yaml')
    j, ps = wait_job('pairs-measure')
    assert j['status'].get('succeeded') == 1
    s = s3('http://127.0.0.1:9010')
    metrics = json.loads(s.get_object(Bucket='hh-lake', Key='lab5/pairs-measure/pairs.csv.metrics.json')['Body'].read())
    peak = metrics['cgroup_memory_peak_bytes']
    limit = math.ceil(peak * 1.25 / (32 * 1024 ** 2)) * 32
    (P / 'results/memory.json').write_text(json.dumps({**metrics, 'margin': 1.25, 'selected_limit_mib': limit}, indent=2))
    print(f'MEASURED peak_bytes={peak} peak_mib={peak / 1024**2:.2f} margin=1.25 selected_limit={limit}Mi', flush=True)
    import yaml
    obj = yaml.safe_load((P / 'manifests/job-measure.yaml').read_text())
    obj['metadata']['name'] = 'pairs-sized'
    c = obj['spec']['template']['spec']['containers'][0]
    c['resources']['limits']['memory'] = f'{limit}Mi'
    for e in c['env']:
        if e['name'] == 'RUN':e['value'] = 'pairs-sized'
    (P / 'manifests/job-sized.yaml').write_text(yaml.safe_dump(obj, sort_keys=False))
    for file in ['job-parallel.yaml', 'job-reduce.yaml']:
        obj2 = yaml.safe_load((P / 'manifests' / file).read_text())
        obj2['spec']['template']['spec']['containers'][0]['resources']['limits']['memory'] = f'{limit}Mi'
        (P / 'manifests' / file).write_text(yaml.safe_dump(obj2, sort_keys=False))
    apply('job-sized.yaml')
    j, _ = wait_job('pairs-sized')
    assert j['status'].get('succeeded') == 1
    verify('http://127.0.0.1:9010', 'lab5/pairs-sized/pairs.csv', 'single')


def migrate():
    src, dst = s3('http://127.0.0.1:9010'), s3('http://127.0.0.1:19010')
    dst.create_bucket(Bucket='hh-lake')
    key = 'raw/it_vacancies_2024.csv'
    h = hashlib.sha256()
    with (P / 'tmp/transfer.csv').open('wb') as f:
        for chunk in src.get_object(Bucket='hh-lake', Key=key)['Body'].iter_chunks(1024 * 1024):
            f.write(chunk);h.update(chunk)
    with (P / 'tmp/transfer.csv').open('rb') as f:
        dst.put_object(Bucket='hh-lake', Key=key, Body=f)
    got = hashlib.sha256()
    size = 0
    for chunk in dst.get_object(Bucket='hh-lake', Key=key)['Body'].iter_chunks(1024 * 1024):
        got.update(chunk);size += len(chunk)
    print('source=http://127.0.0.1:9010 target=Kubernetes/rustfs:9000 via port-forward', flush=True)
    print(f'object=s3://hh-lake/{key} bytes={size}', flush=True)
    print('source_sha256=' + h.hexdigest(), flush=True)
    print('target_sha256=' + got.hexdigest(), flush=True)
    assert h.digest() == got.digest()
    print('SHA256_MATCH=True', flush=True)
    cmd(K + ['-n', 'lab5', 'get', 'deployment,pod,service,pvc', '-o', 'wide'])


def parallel():
    apply('job-parallel.yaml')
    j, _ = wait_job('pairs-parallel')
    assert j['status'].get('succeeded') == 3
    apply('job-reduce.yaml')
    j, _ = wait_job('pairs-reduce')
    assert j['status'].get('succeeded') == 1
    verify('http://127.0.0.1:19010', 'lab5/parallel/pairs.csv', 'parallel')


def events(name):
    cmd(K + ['-n', 'lab5', 'get', 'events', '--field-selector', 'involvedObject.name=' + name, '--sort-by=.metadata.creationTimestamp'])
    ev = data('-n', 'lab5', 'get', 'events', '--field-selector', 'involvedObject.name=' + name)
    (P / 'logs' / (name + '-events.json')).write_text(json.dumps(ev, indent=2))
    found = data('-n', 'lab5', 'get', 'pods', '--field-selector', 'metadata.name=' + name)
    if not found['items']:
        print('pod=' + name + ' deleted', flush=True)
        return None
    obj = found['items'][0]
    (P / 'logs' / (name + '.json')).write_text(json.dumps(obj, indent=2))
    print(json.dumps({'pod': name, 'phase': obj['status']['phase'], 'conditions': obj['status'].get('conditions')}, ensure_ascii=False), flush=True)
    return obj


def wait_event(name, reason):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        ev = data('-n', 'lab5', 'get', 'events', '--field-selector', 'involvedObject.name=' + name)
        if any(e.get('reason') == reason for e in ev['items']):return
        time.sleep(1)
    raise RuntimeError('event timeout ' + name + ' ' + reason)


def scheduling():
    cmd(K + ['get', 'node', 'lab5-worker', '-o', 'custom-columns=NAME:.metadata.name,CPU:.status.capacity.cpu,ALLOCATABLE:.status.allocatable.cpu'])
    apply('cpu-holder.yaml')
    cmd(K + ['-n', 'lab5', 'wait', '--for=condition=Ready', 'pod/cpu-holder', '--timeout=60s'])
    apply('cpu-wait.yaml')
    wait_event('cpu-wait', 'FailedScheduling')
    p = events('cpu-wait')
    assert p['status']['phase'] == 'Pending'
    cmd(K + ['-n', 'lab5', 'delete', 'pod', 'cpu-holder', '--wait=true'])
    cmd(K + ['-n', 'lab5', 'wait', '--for=condition=Ready', 'pod/cpu-wait', '--timeout=60s'])
    events('cpu-wait')
    cmd(K + ['-n', 'lab5', 'delete', 'pod', 'cpu-wait', '--wait=true'])
    apply('low.yaml')
    cmd(K + ['-n', 'lab5', 'wait', '--for=condition=Ready', 'pod/low', '--timeout=60s'])
    apply('high.yaml')
    wait_event('low', 'Preempted')
    cmd(K + ['-n', 'lab5', 'wait', '--for=condition=Ready', 'pod/high', '--timeout=90s'])
    events('low');events('high')
    cmd(K + ['-n', 'lab5', 'get', 'pods', '-o', 'wide'])
    cmd(K + ['-n', 'lab5', 'delete', 'pod', 'low', 'high', '--wait=true', '--ignore-not-found=true'])


def quota():
    apply('quota.yaml');apply('quota-first.yaml')
    cmd(K + ['-n', 'lab5-quota', 'wait', '--for=condition=Ready', 'pod/quota-first', '--timeout=60s'])
    cmd(K + ['-n', 'lab5-quota', 'describe', 'resourcequota', 'compute'])
    r = cmd(K + ['create', '-f', 'manifests/quota-second.yaml'], check=False)
    assert r.returncode != 0 and 'exceeded quota' in r.stdout
    cmd(K + ['-n', 'lab5-quota', 'get', 'pods'])
    cmd(K + ['-n', 'lab5-quota', 'delete', 'pod', 'quota-first', '--wait=true'])
    apply('quota-second.yaml')
    cmd(K + ['-n', 'lab5-quota', 'wait', '--for=condition=Ready', 'pod/quota-second', '--timeout=60s'])
    cmd(K + ['-n', 'lab5-quota', 'describe', 'resourcequota', 'compute'])
    cmd(K + ['-n', 'lab5-quota', 'delete', 'pod', 'quota-second', '--wait=true'])


if __name__ == '__main__':
    phase = sys.argv[1]
    print('$ python scripts/experiments.py ' + phase, flush=True)
    {'memory': memory, 'migrate': migrate, 'parallel': parallel, 'scheduling': scheduling, 'quota': quota}[phase]()
