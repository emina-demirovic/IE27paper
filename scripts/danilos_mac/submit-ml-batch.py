#!/usr/bin/env python3
"""Submit repeated experiment specifications and persist IDs for check-ml-time.py."""
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
import urllib.request


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:5031')
    parser.add_argument('--specs', type=Path,
                        help='Optional JSON array overriding the four standard experiments')
    parser.add_argument('--trees', type=int, default=50)
    parser.add_argument('--dry-run', action='store_true', help='Print requests without submitting')
    parser.add_argument('--rounds', type=int, default=5)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    if not 1 <= args.trees <= 10000:
        parser.error('--trees must be between 1 and 10000')
    # Match IE27paper/scripts/submit-classical-ml.ps1 exactly.
    specs = [dict(name=f'Random forest - {dataset}', algorithm='random-forest',
                  environment=dataset, seed=42, maxSteps=args.trees, timeoutSeconds=300)
             for dataset in ('Iris', 'Wine', 'Breast Cancer', 'California Housing')]
    if args.specs:
        specs = json.loads(args.specs.read_text())
    required = {'name', 'algorithm', 'environment', 'seed', 'maxSteps'}
    if (not isinstance(specs, list) or len(specs) != 4
            or any(not isinstance(s, dict) or not required.issubset(s) for s in specs)):
        parser.error('--specs must contain four experiment objects with '
                     'name, algorithm, environment, seed and maxSteps')
    if args.dry_run:
        print(json.dumps({'url': args.url, 'rounds': args.rounds,
                          'taskCount': len(specs) * args.rounds, 'specifications': specs}, indent=2))
        return 0
    # Check connectivity before creating a batch or submitting anything.
    try:
        with urllib.request.urlopen(args.url.rstrip('/') + '/api/workers', timeout=10) as response:
            workers = json.load(response)
        online_workers = [worker for worker in workers if worker.get('isOnline') is True]
        print(f'Coordinator: {args.url} ({len(online_workers)} online workers, '
              f'{len(workers)} registered)', flush=True)
    except Exception as error:
        print(f'Cannot reach coordinator {args.url}: {error}. '
              'Check its listening address or pass --url. No tasks submitted.', file=sys.stderr)
        return 1
    if not online_workers:
        print('No online workers at this coordinator. Start workers using the same URL, '
              'wait for registration, then retry. No tasks submitted.', file=sys.stderr)
        return 1
    batches = root / 'ml-batches'
    batches.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    path = batches / (stamp + '.json')
    batch = {'url': args.url.rstrip('/'), 'expectedCount': len(specs) * args.rounds,
             'specifications': specs, 'ids': [], 'submissionComplete': False}

    def save():
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(batch, indent=2) + '\n')
        temp.replace(path)

    save()
    (batches / 'latest.txt').write_text(path.name + '\n')
    print('Batch file:', path, flush=True)
    try:
        for _ in range(args.rounds):
            for spec in specs:
                request = urllib.request.Request(
                    batch['url'] + '/api/experiments',
                    data=json.dumps(spec).encode(),
                    headers={'Content-Type': 'application/json'}, method='POST')
                # Do not retry POST automatically: a timed-out request may have succeeded.
                with urllib.request.urlopen(request, timeout=30) as response:
                    experiment = json.load(response)
                batch['ids'].append(experiment['id'])
                save()
                print(f"Submitted {len(batch['ids'])}/{batch['expectedCount']}: "
                      f"{experiment['id']}", flush=True)
        batch['submissionComplete'] = True
        save()
    except (Exception, KeyboardInterrupt) as error:
        print(f'Submission interrupted: {error}. Saved IDs remain in {path}. '
              'Check the coordinator before resubmitting; an unacknowledged request '
              'may have been accepted.', file=sys.stderr)
        return 1
    print(f"Submitted tasks: {len(batch['ids'])}")
    print('Check results: python3 check-ml-time.py --wait')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(f'Could not submit batch: {error}', file=sys.stderr)
        sys.exit(1)
