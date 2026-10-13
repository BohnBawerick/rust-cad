#!/usr/bin/env python3
"""Re-validate the round 1 kept patches under the round 2 evaluator and gates.

The 12 kept patches apply in order to one file, so the candidates are the 12 cumulative
prefixes. For each prefix this script applies the patches to a clean checkout of the file,
builds the probe, runs both suites under the current evaluator, compares them with the
frozen baseline the way the loop does (regressions, new incorrect successes, new runtime
failures), and runs the gates for the crates the file affects. The longest prefix that passes
every check is the candidate starting point for round 2. The decision itself is written up in
`research/2026-10-13-round2-prep/README.md`.

    . lab/env.sh && python3 lab/revalidate_round1.py [--prefixes 3 4 6] [--out research/2026-10-13-round2-prep/revalidation.json]

Leaves the kernel file as it found it.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

import gates
from compile_command import ENV as COMPILE_ENV, command as compile_command
from verify import score, suite

ROOT = Path(__file__).resolve().parent
KERNEL = ROOT / 'kernel/source'
FILE = 'monstertruck-solid/src/transversal/classic/mod.rs'
ROUND1 = ROOT.parent / 'research/2026-10-13-overnight/overnight'
KEPT = [3, 4, 6, 9, 10, 20, 27, 30, 43, 46, 58, 59]


def unsafe(rows):
    return {r['id'] for r in rows if not r['pass'] and 'actual' in r}


def runtime(rows):
    return {r['id'] for r in rows if any(s == 'timeout' or s.startswith(('crash:', 'panic:', 'evaluator_error:')) for s in r['reasons'])}


def compare(base, new):
    return dict(regressions=sorted({r['id'] for r in base['rows'] if r['pass']} - {r['id'] for r in new['rows'] if r['pass']}),
                new_incorrect_successes=sorted(unsafe(new['rows']) - unsafe(base['rows'])),
                new_runtime_failures=sorted(runtime(new['rows']) - runtime(base['rows'])))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--prefixes', nargs='*', type=int, default=KEPT, help='last kept attempt of each prefix to try')
    p.add_argument('--out', type=Path, default=ROOT.parent / 'research/2026-10-13-round2-prep/revalidation.json')
    p.add_argument('--gate-budget', type=int, default=1800)
    a = p.parse_args()
    target = KERNEL / FILE
    original = target.read_bytes()
    pristine = subprocess.check_output(['git', '-C', str(KERNEL), 'show', 'HEAD:./' + FILE])
    baseline = {s: json.loads((ROOT / f'results/frozen-baseline-{s}.json').read_text()) for s in ['public', 'heldout']}
    packages = gates.affected_packages([FILE])
    (ROOT / 'gate-target').mkdir(exist_ok=True)
    (ROOT / 'tmp').mkdir(exist_ok=True)
    results = []
    try:
        for last in a.prefixes:
            prefix = [k for k in KEPT if k <= last]
            target.write_bytes(pristine)
            t = time.monotonic()
            for k in prefix:
                subprocess.run(['patch', '-p1', '--directory', str(KERNEL), '--input', str(ROUND1 / f'attempt-{k:03d}/kept.patch'), '--silent'],
                               check=True, timeout=30)
            row = dict(prefix=prefix, patched_lines=len(target.read_text().splitlines()))
            log = ROOT / f'tmp/revalidate-{last}-build.log'
            with log.open('w') as out:
                build = subprocess.run(compile_command(), stdout=out, stderr=subprocess.STDOUT, env=COMPILE_ENV, timeout=600)
            row['build_exit'] = build.returncode
            if build.returncode == 0:
                verdicts = {s: suite(s, ROOT / f'tmp/revalidate-{last}-{s}.json', workers=3) for s in ['public', 'heldout']}
                combined = score(verdicts['public']['rows'] + verdicts['heldout']['rows'])
                row.update(public_passed=verdicts['public']['passed'], heldout_passed=verdicts['heldout']['passed'],
                           combined_passed=combined['passed'], combined_score=combined['score'],
                           groups={g: v['passed'] for g, v in combined['groups'].items()},
                           public=compare(baseline['public'], verdicts['public']), heldout=compare(baseline['heldout'], verdicts['heldout']))
                for name, cmd in [('kernel_tests', gates.test_command(packages)), ('release_check', gates.release_command(packages))]:
                    rc, seconds = gates.run(cmd, ROOT / f'tmp/revalidate-{last}-{name}.log', a.gate_budget)
                    row[name] = dict(exit=rc, seconds=seconds)
                    if rc:
                        text = (ROOT / f'tmp/revalidate-{last}-{name}.log').read_text(errors='replace').splitlines()
                        row[name]['failures'] = [l.strip() for l in text if 'FAILED' in l or l.startswith('error')][:12]
                clean = (not row['public']['regressions'] and not row['heldout']['regressions']
                         and not row['public']['new_incorrect_successes'] and not row['heldout']['new_incorrect_successes']
                         and not row['public']['new_runtime_failures'] and not row['heldout']['new_runtime_failures'])
                row['passes_all_gates'] = clean and row['kernel_tests']['exit'] == 0 and row['release_check']['exit'] == 0
            row['seconds'] = round(time.monotonic() - t, 1)
            results.append(row)
            print(json.dumps({k: v for k, v in row.items() if k not in ('public', 'heldout')}), flush=True)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(json.dumps(dict(evaluator=baseline['public']['evaluator'], gate_packages=packages,
                                             baseline=dict(public_passed=baseline['public']['passed'], heldout_passed=baseline['heldout']['passed'],
                                                           combined_score=score(baseline['public']['rows'] + baseline['heldout']['rows'])['score']),
                                             prefixes=results), indent=2) + '\n')
    finally:
        target.write_bytes(original)
        subprocess.run(['git', '-C', str(KERNEL), 'status', '--short', '--', FILE])


if __name__ == '__main__':
    main()
