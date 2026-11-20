import csv
import hashlib
from pathlib import Path

P = Path(__file__).resolve().parents[1]


def read(path):
    with path.open(newline='') as f:
        return list(csv.reader(f))


reference = read(P / 'input/lab3_pairs.csv')
for name in ['single', 'parallel']:
    path = P / 'results' / f'{name}_pairs.csv'
    rows = read(path)
    print(f'{name} pairs={len(rows)-1} all_equal={rows == reference} top10_equal={rows[1:11] == reference[1:11]}')
    print('sha256=' + hashlib.sha256(path.read_bytes()).hexdigest())
    assert rows == reference
print('TOP10')
for row in reference[1:11]:
    print(' + '.join(row[:2]) + ' = ' + row[2])
