#!/usr/bin/env python3
"""Check a saved batch and measure earliest creation to latest completion."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', nargs='?', type=Path, help='Defaults to latest submitted batch')
    parser.add_argument('--wait', action='store_true', help='Poll every two seconds until all tasks finish')
    parser.add_argument('--timeout', type=float, default=1800, help='Maximum wait in seconds (default: 1800)')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    path = args.batch
    if path is None:
        latest = root / 'ml-batches' / 'latest.txt'
        if not latest.exists():
            parser.error('No saved batch. Run submit-ml-batch.py first.')
        path = latest.parent / latest.read_text().strip()
    batch = json.loads(path.read_text())
    deadline = time.monotonic() + args.timeout
    while True:
        results = []
        for experiment_id in batch['ids']:
            url = batch['url'] + '/api/experiments/' + urllib.parse.quote(experiment_id, safe='')
            with urllib.request.urlopen(url, timeout=10) as response:
                results.append(json.load(response))
        if (not args.wait or not batch['submissionComplete']
                or all(r['status'] in (2, 3, 4) for r in results)):
            break
        print(f"Completed: {sum(r['status'] == 2 for r in results)}/{batch['expectedCount']}", flush=True)
        if time.monotonic() >= deadline:
            print('Wait limit reached. Run this script again later.')
            break
        time.sleep(2)
    completed = [r for r in results if r['status'] == 2]
    print('Batch:', path)
    print(f"Successfully completed: {len(completed)} / {batch['expectedCount']}")
    print('Completed tasks by worker:')
    for worker, count in sorted(Counter(r.get('assignedWorkerId') or '(unknown)'
                                        for r in completed).items()):
        print(f'  {worker}: {count}')
    labels = {0: 'Pending', 1: 'Running', 2: 'Completed', 3: 'Failed', 4: 'Cancelled'}
    for result in results:
        if result['status'] != 2:
            print(f"  {result['id']}: {labels.get(result['status'], result['status'])}"
                  f" — {result.get('resultMessage') or ''}")
    snapshot = path.with_name(path.stem + '-results.json')
    snapshot.write_text(json.dumps(results, indent=2) + '\n')
    if (batch['submissionComplete'] and len(results) == batch['expectedCount']
            and len(completed) == batch['expectedCount']):
        def timestamp(value):
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        start = min(timestamp(r['createdAtUtc']) for r in results)
        end = max(timestamp(r['finishedAtUtc']) for r in results)
        print(f"Total time for {len(results)} tasks: {(end - start).total_seconds():.2f} s")
        print('Includes submission, queueing, scheduling and execution time.')
    else:
        print('Total time is available only when the entire batch completes successfully.')
        if not batch['submissionComplete']:
            print('This batch was only partially submitted.')
    print('Results saved:', snapshot)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped waiting. Tasks continue running; saved IDs are unchanged.')
        sys.exit(130)
    except Exception as error:
        print(f'Could not read results: {error}', file=sys.stderr)
        sys.exit(1)
