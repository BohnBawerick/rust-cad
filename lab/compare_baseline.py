#!/usr/bin/env python3
"""Fail when a suite result regresses from the recorded frozen baseline.

A regression is any case that passed in the baseline and now fails, any new
incorrect success (a failing case that now returns geometry where the baseline
did not), any new timeout, crash, panic or evaluator error, or a lower score.
New passes are allowed and listed, so an improvement prompts a baseline update
instead of a red build. Results recorded under a different evaluator revision
never compare equal: re-baseline instead.
"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def runtime_failures(rows):
    return {r['id'] for r in rows if any(s == 'timeout' or s.startswith(('crash:', 'panic:', 'evaluator_error:')) for s in r['reasons'])}


def unsafe(rows):
    return {r['id'] for r in rows if not r['pass'] and 'actual' in r}


def compare(baseline, current):
    old = {r['id']: r for r in baseline['rows']}
    new = {r['id']: r for r in current['rows']}
    problems = []
    if baseline.get('evaluator') != current.get('evaluator'):
        problems.append(f"evaluator revision differs: baseline {baseline.get('evaluator')!r}, current {current.get('evaluator')!r}")
    if set(old) != set(new):
        problems.append(f'case set differs: missing {sorted(set(old) - set(new))}, extra {sorted(set(new) - set(old))}')
    regressions = sorted(i for i in old if i in new and old[i]['pass'] and not new[i]['pass'])
    if regressions:
        problems.append(f'previously passing cases now fail: {regressions}')
    wrong = sorted(unsafe(current['rows']) - unsafe(baseline['rows']))
    if wrong:
        problems.append(f'new incorrect successes: {wrong}')
    crashes = sorted(runtime_failures(current['rows']) - runtime_failures(baseline['rows']))
    if crashes:
        problems.append(f'new timeouts, crashes, panics or evaluator errors: {crashes}')
    if current['score'] < baseline['score'] - 1e-9:
        problems.append(f"score fell from {baseline['score']:.10f} to {current['score']:.10f}")
    gains = sorted(i for i in old if i in new and not old[i]['pass'] and new[i]['pass'])
    return problems, gains


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('split', choices=['public', 'heldout'])
    p.add_argument('result', type=Path, help='output of verify.py suite')
    p.add_argument('--baseline', type=Path, help='defaults to results/frozen-baseline-<split>.json')
    a = p.parse_args()
    baseline = json.loads((a.baseline or ROOT / f'results/frozen-baseline-{a.split}.json').read_text())
    current = json.loads(a.result.read_text())
    problems, gains = compare(baseline, current)
    print(f"{a.split}: baseline {baseline['passed']}/{baseline['total']} score {baseline['score']:.10f}; "
          f"current {current['passed']}/{current['total']} score {current['score']:.10f}")
    for name, group in current['groups'].items():
        print(f"  {name:10} {group['passed']:4}/{group['total']:<4} (baseline {baseline['groups'][name]['passed']})")
    if gains:
        print(f'new passes ({len(gains)}): {gains}')
        print('If these are reviewed and real, record a new baseline.')
    for problem in problems:
        print('REGRESSION: ' + problem)
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
