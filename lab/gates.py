#!/usr/bin/env python3
"""Hard keep gates beyond the score: the kernel's own tests and a release check.

Round 1 kept a change that broke `adjacent_cubes_or` and two that failed the release build,
because neither was a keep gate. Here both run on every candidate that improved the score,
before the repeat run, and a failure rejects the candidate.

Both commands run offline inside a Bubblewrap sandbox like the candidate compile's, with
the kernel source under a throwaway overlay (a few tests write files next to their crate),
and only the Cargo cache and a dedicated target directory writable for real. They mirror the CI job: the recorded dependency lock, the same crate exclusions,
one test thread. The release check uses `cargo check --release`, which is where every crate's
`#![cfg_attr(not(debug_assertions), deny(warnings))]` turns a warning into an error; CI also
runs the full release build.

Usage from the repository root:

    python3 lab/gates.py tests [--packages a b] [--log file]
    python3 lab/gates.py release [--packages a b] [--log file]
    python3 lab/gates.py affected monstertruck-solid/src/transversal/classic

A lane's gate covers the crates that own its editable paths and every crate that depends on
them (`affected_packages`); the loop proves the whole workspace once at run start.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KERNEL = ROOT / 'kernel/source'
LOCK = ROOT / 'upstream-tests/Cargo.lock'
RESOURCES = KERNEL / 'resources'
RESOURCES_COMMIT = '9bf9de1426c5fc2f2b8d63f501dca0d3c53ebd91'
EXCLUDE = ['monstertruck-gpu', 'monstertruck-render', 'monstertruck-wasm', 'example-pages-generator']
ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}


def prepare():
    """Put the recorded lock in place and insist on the upstream test resources."""
    lock = KERNEL / 'Cargo.lock'
    if not lock.exists() or lock.read_bytes() != LOCK.read_bytes():
        shutil.copyfile(LOCK, lock)
    if not (RESOURCES / '.git').exists() and not any(RESOURCES.iterdir() if RESOURCES.exists() else []):
        raise RuntimeError(
            f'{RESOURCES} is missing. The kernel tests read fixtures from it. Fetch it once:\n'
            f'  mkdir -p {RESOURCES} && cd {RESOURCES} && git init -q && '
            f'git remote add origin https://github.com/ricosjp/resources4truck.git && '
            f'git fetch -q --depth 1 origin {RESOURCES_COMMIT} && git checkout -q FETCH_HEAD')


def sandbox(target):
    return ['bwrap', '--unshare-all', '--die-with-parent',
            '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
            '--symlink', 'usr/bin', '/bin', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            # Some kernel tests write files into their crate directory. A throwaway overlay
            # takes those writes and the real source stays untouched.
            '--overlay-src', str(KERNEL.resolve()), '--tmp-overlay', '/work/kernel/source',
            '--bind', str(ROOT / 'cache/cargo'), '/cargo',
            '--bind', str(target), '/target',
            '--setenv', 'CARGO_HOME', '/cargo', '--setenv', 'CARGO_TARGET_DIR', '/target',
            '--setenv', 'TMPDIR', '/tmp', '--setenv', 'CARGO_BUILD_JOBS', '4',
            '--setenv', 'RAYON_NUM_THREADS', '1', '--chdir', '/work/kernel/source', '--']


def affected_packages(editable):
    """Workspace crates that own an editable path, plus every crate that depends on them.

    Tests outside that closure cannot see the change. The result is cut to the CI selection,
    so excluded crates never enter a gate.
    """
    prepare()
    meta = json.loads(subprocess.check_output(
        ['cargo', 'metadata', '--offline', '--locked', '--format-version', '1', '--no-deps'],
        cwd=KERNEL, env=dict(ENV, CARGO_HOME=str(ROOT / 'cache/cargo'), CARGO_TARGET_DIR=str(ROOT / 'gate-target'))))
    packages = {p['name']: Path(p['manifest_path']).parent for p in meta['packages']}
    reverse = {}
    for p in meta['packages']:
        for d in p['dependencies']:
            if d['name'] in packages:
                reverse.setdefault(d['name'], set()).add(p['name'])
    owners = {name for name, root in packages.items()
              if any((KERNEL / path).resolve().is_relative_to(root.resolve()) for path in editable)}
    closure = set()
    stack = list(owners)
    while stack:
        name = stack.pop()
        if name in closure:
            continue
        closure.add(name)
        stack.extend(reverse.get(name, ()))
    return sorted(closure - set(EXCLUDE))


def selection(packages):
    if packages:
        args = []
        for p in packages:
            args += ['-p', p]
        return args
    args = ['--workspace']
    for p in EXCLUDE:
        args += ['--exclude', p]
    return args


def test_command(packages=None, target=None):
    target = target or ROOT / 'gate-target'
    return sandbox(target) + ['/usr/bin/cargo', 'test', '--locked', '--offline'] + selection(packages) + \
        ['--no-fail-fast', '--', '--test-threads=1']


def release_command(packages=None, target=None):
    target = target or ROOT / 'gate-target'
    return sandbox(target) + ['/usr/bin/cargo', 'check', '--release', '--locked', '--offline'] + selection(packages)


def run(cmd, log, budget):
    """Run one gate with a wall-clock budget. Returns (exit code, seconds); 124 means timeout."""
    start = time.monotonic()
    with Path(log).open('wb') as out:
        child = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, env=ENV, start_new_session=True)
        try:
            rc = child.wait(timeout=budget)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            rc = 124
    return rc, round(time.monotonic() - start, 3)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('gate', choices=['tests', 'release', 'affected'])
    p.add_argument('paths', nargs='*', help='editable paths, for `affected`')
    p.add_argument('--packages', nargs='*', help='cargo packages; default is the CI workspace selection')
    p.add_argument('--log', type=Path, default=None)
    p.add_argument('--budget', type=int, default=1800)
    a = p.parse_args()
    if a.gate == 'affected':
        print(' '.join(affected_packages(a.paths)))
        return
    prepare()
    (ROOT / 'gate-target').mkdir(exist_ok=True)
    cmd = test_command(a.packages) if a.gate == 'tests' else release_command(a.packages)
    log = a.log or ROOT / f'tmp/gate-{a.gate}.log'
    log.parent.mkdir(exist_ok=True)
    rc, seconds = run(cmd, log, a.budget)
    print(f'{a.gate}: exit {rc} after {seconds}s, log {log}')
    sys.exit(rc)


if __name__ == '__main__':
    main()
