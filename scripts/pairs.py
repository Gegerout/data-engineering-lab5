import csv
import hashlib
import io
import json
import os
import resource
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

from common import BUCKET, RAW_KEY, VARIANT_ROLE, in_variant, s3_client, skills_of

EXTRA = 256 * 1024
CHUNK = 32 * 1024 * 1024
def get_range(s3, lo, hi):
    return s3.get_object(Bucket=BUCKET, Key=RAW_KEY, Range=f'bytes={lo}-{hi}')['Body'].read()

def read_split(s3, start, end, size):
    """Сплит целиком от байта start-1 до конца последней строки, начатой до end."""
    base = start - 1 if start > 0 else 0
    hi = end - 1
    buf = bytearray(get_range(s3, base, hi))
    while hi < size - 1 and buf.find(b'\n', end - 1 - base) == -1:
        lo, hi = hi + 1, min(hi + EXTRA, size - 1)
        buf += get_range(s3, lo, hi)
    return bytes(buf), base

def owned_lines(buf, base, start, end):
    """Строки, которые начинаются внутри сплита, как в LineRecordReader из Hadoop."""
    if start == 0:
        p = 0
    else:
        nl = buf.find(b'\n')  # buf начинается с байта start-1
        if nl == -1:
            return
        p = nl + 1
    n = len(buf)
    while p < n and base + p < end:
        nl = buf.find(b'\n', p)
        if nl == -1:
            nl = n
        yield base + p, buf[p:nl]
        p = nl + 1

def csv_bytes(pairs):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['skill_1', 'skill_2', 'vacancies'])
    for (a, b), n in sorted(pairs.items(), key=lambda x: (-x[1], x[0])):
        w.writerow([a, b, n])
    return out.getvalue().encode()


def main():
    start = time.monotonic()
    mode = sys.argv[1]
    run = os.environ.get('RUN', mode)
    total = Counter()
    s3 = s3_client()
    if mode == 'reduce':
        for i in range(int(os.environ['PARTS'])):
            key = f'lab5/{run}/parts/{i}.csv'
            data = s3.get_object(Bucket=BUCKET, Key=key)['Body'].read().decode()
            for row in csv.DictReader(io.StringIO(data)):
                total[(row['skill_1'], row['skill_2'])] += int(row['vacancies'])
    else:
        index = int(os.environ.get('JOB_COMPLETION_INDEX', '0'))
        parts = int(os.environ.get('PARTS', '1'))
        size = s3.head_object(Bucket=BUCKET, Key=RAW_KEY)['ContentLength']
        print(f'mode={mode} index={index} parts={parts} input_bytes={size}', flush=True)
        records = 0
        for i, lo in enumerate(range(0, size, CHUNK)):
            if i % parts != index:
                continue
            hi = min(lo + CHUNK, size)
            buf, base = read_split(s3, lo, hi, size)
            for pos, line in owned_lines(buf, base, lo, hi):
                if VARIANT_ROLE.encode() not in line:
                    continue
                row = next(csv.reader([line.decode()]))
                if in_variant(row):
                    records += 1
                    total.update(combinations(skills_of(row), 2))
            del buf
            print(f'index={index} split={i} bytes={lo}-{hi - 1} variant_records={records}', flush=True)
    body = csv_bytes(total)
    key = f'lab5/{run}/parts/{index}.csv' if mode == 'map' else f'lab5/{run}/pairs.csv'
    s3.put_object(Bucket=BUCKET, Key=key, Body=body)
    print(f'output=s3://{BUCKET}/{key} pairs={len(total)} sum={sum(total.values())}', flush=True)
    print('sha256=' + hashlib.sha256(body).hexdigest(), flush=True)
    if mode != 'map':
        print('TOP10', flush=True)
        for (a, b), n in sorted(total.items(), key=lambda x: (-x[1], x[0]))[:10]:
            print(f'{a} + {b} = {n}', flush=True)
    peak = Path('/sys/fs/cgroup/memory.peak')
    metrics = {'elapsed_s': round(time.monotonic() - start, 3),
               'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
               'cgroup_memory_peak_bytes': int(peak.read_text()) if peak.exists() else None}
    print('METRICS ' + json.dumps(metrics), flush=True)
    s3.put_object(Bucket=BUCKET, Key=key + '.metrics.json', Body=json.dumps(metrics).encode())


if __name__ == '__main__':
    main()
