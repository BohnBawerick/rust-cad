#!/usr/bin/env python3
"""Round 2 search controller: lanes, hard gates, minimized failures, resumable runs.

One attempt:

1. Pick a lane: the first lane in the configured order that still has failing visible cases
   and has not stalled. A lane stalls after `stall_attempts` attempts without a keep; the
   controller then moves on and comes back later. With no visible headroom anywhere the run
   stops instead of burning the clock.
2. Give the coding agent the lane's editable paths, read-write, inside the sandbox. Feed it
   the lane's visible failures in minimized form, the recent history and any vetoes.
3. Reject the candidate outright if it touched a test file or an existing `#[cfg(test)]`
   block, or anything outside the editable paths.
4. Compile the probe offline. Run both suites. A candidate must raise the visible pass count
   with no case that passed before now failing, no new incorrect success and no new timeout,
   crash or panic.
5. Then the hard gates: the kernel's own test suite and the release check with warnings
   denied, both offline. A failure rejects the candidate.
6. Then a repeat of both suites must reproduce every verdict.
7. Keep or restore. Every attempt leaves its prompt, diff, logs and verdicts in
   `lab/overnight/attempt-NNN/` and one record in `experiments.jsonl`.

A rate-limited agent backs off exponentially and the run stops cleanly when the configured
total wait is used up; nothing ever falls back to an API key. `--resume` continues a stopped
run from its records and restores the editable files to the last kept state first.

    python3 lab/overnight.py --hours 5                      # defaults from loop-config.json
    python3 lab/overnight.py --model gpt-6-astra --effort high --lanes planar,revolve,fillet
    python3 lab/overnight.py --resume
    python3 lab/overnight.py --dry-run                      # print the first prompt and command
"""
import argparse
import concurrent.futures
import datetime
import difflib
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

import agent_command
import gates
from compile_command import ENV as COMPILE_ENV, command as compile_command
from minimize import minimize
from verify import score

ROOT = Path(__file__).resolve().parent
KERNEL = ROOT / 'kernel/source'
RUN = ROOT / 'overnight'
CONFIG = ROOT / 'loop-config.json'
EVALUATOR = ROOT / 'evaluator.json'
EVAL_ENV = os.environ.copy()
EVAL_ENV.update(CARGO_HOME=str(ROOT / 'cache/cargo'), CARGO_TARGET_DIR=str(ROOT / 'target'), TMPDIR=str(ROOT / 'tmp'),
                XDG_CACHE_HOME=str(ROOT / 'cache'), CARGO_BUILD_JOBS='4', RAYON_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
PROTECTED_LAB = ['oracle.py', 'verify.py', 'generate.py', 'agent_command.py', 'compile_command.py', 'overnight.py',
                 'gates.py', 'minimize.py', 'evaluator.json', 'probe/Cargo.toml', 'probe/Cargo.lock']
CFG_TEST = re.compile(r'#\[cfg\(test\)\]')

CHILD = None
CURRENT = None
SNAPSHOT = None


# ----- small helpers -----------------------------------------------------------------------

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, obj):
    temp = path.with_suffix('.new')
    temp.write_text(json.dumps(obj, indent=2) + '\n')
    temp.replace(path)


def read_json(path):
    return json.loads(path.read_text())


def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj) + '\n')
        f.flush()
        os.fsync(f.fileno())


def status(state, message):
    hook = os.environ.get('RESEARCH_STATUS_HOOK')
    if hook:
        subprocess.run(['python3', hook, state, message], check=True)


def set_state(**fields):
    write_json(RUN / 'controller-state.json', dict(at=now(), attempt=CURRENT, **fields))


def parse_deadline(text):
    return datetime.datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()


def iso(timestamp):
    return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).isoformat()


def kill_child():
    global CHILD
    if CHILD and CHILD.poll() is None:
        try:
            os.killpg(CHILD.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        CHILD.wait()
    CHILD = None


def run(cmd, log, budget, env, deadline):
    """Run a child under a budget and the deadline. Exit 124 means it was cut off."""
    global CHILD
    limit = min(budget, max(0, deadline - time.time()))
    if limit < 1:
        return 124, 0
    start = time.monotonic()
    with Path(log).open('wb') as out:
        CHILD = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        write_json(RUN / 'child.json', dict(pid=CHILD.pid, at=now(), log=str(Path(log).relative_to(ROOT)), budget=limit))
        try:
            rc = CHILD.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            os.killpg(CHILD.pid, signal.SIGKILL)
            CHILD.wait()
            rc = 124
    CHILD = None
    return rc, round(time.monotonic() - start, 3)


# ----- editable paths, snapshots and protection ----------------------------------------------

def validate_editable(paths):
    for path in paths:
        parts = Path(path).parts
        if '..' in parts or Path(path).is_absolute() or '/tests/' in '/' + path + '/' or path.endswith('tests.rs'):
            raise ValueError(f'invalid editable path {path!r}')
        if not (KERNEL / path).exists():
            raise ValueError(f'editable path {path!r} does not exist under kernel/')
        if (KERNEL / path).is_file() and not path.endswith('.rs'):
            raise ValueError(f'editable file {path!r} is not a Rust source file')


def editable_files(paths):
    """Relative paths of every Rust file under the editable paths."""
    files = set()
    for path in paths:
        full = KERNEL / path
        if full.is_file():
            files.add(path)
        else:
            files.update(str(p.relative_to(KERNEL)) for p in full.rglob('*.rs'))
    return sorted(files)


def snapshot(paths):
    return {rel: (KERNEL / rel).read_bytes() for rel in editable_files(paths)}


def restore(snap, paths):
    """Put the editable paths back to a snapshot, deleting files the snapshot lacks."""
    for rel in editable_files(paths):
        if rel not in snap:
            (KERNEL / rel).unlink()
    for rel, data in snap.items():
        (KERNEL / rel).parent.mkdir(parents=True, exist_ok=True)
        (KERNEL / rel).write_bytes(data)


def unified_diff(before, after):
    """One patch covering changed, added and removed files, paths relative to kernel/."""
    chunks = []
    for rel in sorted(set(before) | set(after)):
        old = before.get(rel, b'').decode(errors='replace').splitlines(True)
        new = after.get(rel, b'').decode(errors='replace').splitlines(True)
        if old == new:
            continue
        chunks.append(''.join(difflib.unified_diff(old, new, fromfile='a/' + rel if rel in before else '/dev/null',
                                                   tofile='b/' + rel if rel in after else '/dev/null')))
    return ''.join(chunks)


def test_blocks(text):
    """Verbatim text of every `#[cfg(test)]` item, by brace matching."""
    blocks = []
    for match in CFG_TEST.finditer(text):
        start = match.start()
        brace = text.find('{', match.end())
        semicolon = text.find(';', match.end())
        if brace < 0 or (0 <= semicolon < brace):
            blocks.append(text[start:semicolon + 1] if semicolon >= 0 else text[start:])
            continue
        depth, i = 0, brace
        while i < len(text):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        blocks.append(text[start:i + 1])
    return blocks


def forbidden_edits(before, after):
    """Reasons a candidate is rejected before it is built."""
    reasons = []
    for rel in sorted(set(before) | set(after)):
        if before.get(rel) == after.get(rel):
            continue
        if '/tests/' in '/' + rel or rel.endswith('tests.rs'):
            reasons.append(f'{rel}: test file changed')
            continue
        if not rel.endswith('.rs'):
            reasons.append(f'{rel}: not a Rust source file')
            continue
        if rel in before and rel in after:
            new_text = after[rel].decode(errors='replace')
            for block in test_blocks(before[rel].decode(errors='replace')):
                if block not in new_text:
                    reasons.append(f'{rel}: an existing #[cfg(test)] block was changed or removed')
                    break
    return reasons


def fingerprint(editable):
    """Hashes of everything the agent must not change: evaluator, corpus, probe, other kernel files."""
    paths = [ROOT / p for p in PROTECTED_LAB]
    paths += list((ROOT / 'probe/src').glob('*.rs')) + list((ROOT / 'corpus').rglob('*.json')) + list((ROOT / 'fixtures').glob('*'))
    tracked = subprocess.check_output(['git', '-C', str(KERNEL), 'ls-files'], text=True).splitlines()
    editable_set = set(editable_files(editable))
    prefixes = tuple(p.rstrip('/') + '/' for p in editable if (KERNEL / p).is_dir())
    for rel in tracked:
        if rel in editable_set or rel.startswith(prefixes):
            continue
        if (KERNEL / rel).is_file():
            paths.append(KERNEL / rel)
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(set(paths))}


# ----- verdict bookkeeping ---------------------------------------------------------------------

def regress(old, new):
    return sorted({r['id'] for r in old['rows'] if r['pass']} - {r['id'] for r in new['rows'] if r['pass']})


def unsafe(rows):
    return {r['id'] for r in rows if not r['pass'] and 'actual' in r}


def runtime_failures(rows):
    return {r['id'] for r in rows if any(s == 'timeout' or s.startswith(('crash:', 'panic:', 'evaluator_error:')) for s in r['reasons'])}


def pass_map(result):
    return {r['id']: r['pass'] for r in result['rows']}


def lane_passed(result, lane):
    return sum(r['pass'] for r in result['rows'] if r['group'] in lane['groups'])


def headroom(result, lane):
    return sum(not r['pass'] for r in result['rows'] if r['group'] in lane['groups'])


def suite(directory, split, suffix, cfg, deadline):
    path = directory / f'{suffix}-{split}.json'
    cmd = ['python3', str(ROOT / 'verify.py'), 'suite', split, '--out', str(path), '--workers', str(cfg['suite_workers'])]
    rc, seconds = run(cmd, directory / f'{suffix}-{split}.log', cfg['suite_seconds'], EVAL_ENV, deadline)
    if rc:
        return None, dict(exit=rc, seconds=seconds)
    return read_json(path), dict(exit=rc, seconds=seconds)


# ----- lanes -------------------------------------------------------------------------------------

def lanes_in_order(cfg):
    by_name = {lane['name']: lane for lane in cfg['lanes']}
    missing = [n for n in cfg['lane_order'] if n not in by_name]
    if missing:
        raise ValueError(f'lane_order names unknown lanes {missing}')
    return [by_name[n] for n in cfg['lane_order']]


def choose_lane(cfg, lane_state, public):
    """The lane to work in next, or None when nothing visible is left to gain."""
    order = lanes_in_order(cfg)
    open_lanes = [lane for lane in order if headroom(public, lane) > 0]
    if not open_lanes:
        return None, 'no_visible_headroom'
    current = lane_state.get('current')
    names = [lane['name'] for lane in open_lanes]
    if current in names:
        state = lane_state.setdefault(current, {})
        stall = cfg['lanes'][[l['name'] for l in cfg['lanes']].index(current)].get('stall_attempts', cfg['stall_attempts'])
        if state.get('since_keep', 0) < stall:
            return next(l for l in open_lanes if l['name'] == current), 'continue'
        state['since_keep'] = 0
        state['stalls'] = state.get('stalls', 0) + 1
        following = names[(names.index(current) + 1) % len(names)]
        return next(l for l in open_lanes if l['name'] == following), 'stalled' if following != current else 'stalled_only_lane'
    return open_lanes[0], 'entered' if current is None else 'lane_closed'


# ----- feedback and prompt ---------------------------------------------------------------------

def minimized_failures(public, lane, cfg, binary, attempt):
    """Minimized versions of the lane's visible failures, rotating through them by attempt."""
    failing = [r for r in public['rows'] if not r['pass'] and r['group'] in lane['groups']]
    if not failing:
        return []
    n = min(cfg['minimize']['cases'], len(failing))
    start = (attempt * n) % len(failing)
    chosen = (failing + failing)[start:start + n]
    recipes = [read_json(ROOT / 'corpus/public' / f"{r['id']}.json") for r in chosen]
    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg['minimize']['workers']) as pool:
        return list(pool.map(lambda recipe: minimize(recipe, binary, RUN / 'minimized'), recipes))


def feedback(public, hidden, lane, cfg, history, attempt, keeps, binary):
    failing = [r for r in public['rows'] if not r['pass'] and r['group'] in lane['groups']]
    lane_history = [h for h in history if h.get('lane') == lane['name']][-6:]
    return dict(
        attempt=attempt, lane=lane['name'], groups=lane['groups'], focus=lane['focus'],
        visible=dict(score=public['score'], passed=public['passed'], total=public['total'], groups=public['groups']),
        lane_headroom=dict(failing=len(failing), total=sum(r['group'] in lane['groups'] for r in public['rows'])),
        minimized_failures=minimized_failures(public, lane, cfg, binary, attempt),
        other_visible_failures=[dict(id=r['id'], group=r['group'], op=r['op'], reasons=r['reasons']) for r in failing][:40],
        kept_so_far=[dict(attempt=h['attempt'], lane=h.get('lane'), hypothesis=h.get('hypothesis', '')[:400]) for h in history if h.get('kept')],
        lane_history=lane_history, recent_history=history[-4:],
        rules=dict(editable=lane['editable'],
                   gates=['probe compiles offline', 'both suites: visible gain, no regression, no new wrong success or crash',
                          'kernel test suite passes', 'cargo check --release with warnings denied passes', 'repeat run identical']))


def prompt(cfg, lane, attempt):
    agent = cfg['agent']
    allowed = ', '.join('/work/kernel/' + p for p in lane['editable'])
    return f'''You are the coding subject in a bounded kernel repair loop, attempt {attempt}, lane "{lane['name']}". Work yourself; do not delegate or contact anyone.
Task: {lane['focus']}
Groups this lane is scored on: {', '.join(lane['groups'])}. The score is the mean pass rate over nine operation groups; this lane's groups are where visible failures remain.
Definition: boolean difference A minus B preserves A when the solids are disjoint, is empty when A is inside B, and keeps a cavity shell when B is inside A. Union and intersection keep their regularized solid meanings. Two solids that touch only along an edge or a vertex have a union of two bodies: two closed shells whose point sets touch. A union across a whole shared face is one body. Every shell is judged on its own as a closed oriented surface; a shell that glues two bodies along an edge is rejected. Empty valid outputs differ from failed operations.
Editable: {allowed}. Everything else under /work/kernel is read-only. You may add new .rs files under an editable directory and declare them from an editable module. Never change tests, existing #[cfg(test)] blocks, Cargo.toml, dependency files or configuration; a candidate that does is rejected before it is built. Do not commit. The controller owns evaluation and keep/revert.
Start by reading /work/scratch/feedback.json. It holds minimized failing recipes with the expected and actual mass properties and topology, the remaining visible failures, what previous attempts in this lane tried and why they were rejected, and the last rejected patch when one exists at /work/scratch/last-candidate.patch. /work/probe/main.rs shows read-only how a recipe is turned into kernel calls, so you can reproduce a failure exactly. The full corpus, evaluator, hidden cases and host home are absent. Hidden cases veto regressions. Do not seek them. No web or network use. Derive the algorithm from the local source.
Does not count: refusing or returning inputs unchanged to hide failed operations; geometry-specific answer tables; case-id checks; changing tolerances, tests, output metrics or the evaluator; a bounding-box test on vertices as a proof that curved surfaces are separated; replacing exact B-rep with a mesh approximation; an explanation without a source patch.
Keep gates, all hard: the probe compiles offline; the visible pass count rises with no previously passing case failing, no new incorrect success and no new timeout, crash or panic; the kernel's own test suite passes; `cargo check --release` passes with warnings denied, so no unused imports, variables or qualifications, and nothing clippy::all rejects; a repeat run reproduces every verdict. The evaluator and oracle are immutable to you.
Write one coherent implementation hypothesis that fixes a root cause, not one recipe. Prefer a focused change in the module that owns the defect over a large rewrite in one file. Read nearby source as needed but do not build here; build caches and the harness are absent. If the previous patch failed to compile or a gate, repair that hypothesis from the error feedback. If it was rejected for no gain, choose a materially different hypothesis.
Budget: {agent['seconds']} seconds, at most {agent['max_tool_calls']} tool calls. Use it for a concrete artifact. If near budget or outside scope, write partial findings to /work/scratch/partial.txt and return a short summary. Redirect output longer than 2000 tokens to scratch and read selectively.
Return after writing the candidate, with at most 300 words covering modified files, the mathematical reason, expected scope and unresolved risks. Never claim tests passed here. The controller decides retention.'''


# ----- configuration -----------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--config', type=Path, default=CONFIG)
    p.add_argument('--harness', help='codex or claude')
    p.add_argument('--model')
    p.add_argument('--effort')
    p.add_argument('--agent-seconds', type=int)
    p.add_argument('--hours', type=float, help='wall-clock budget from start; sets the deadline')
    p.add_argument('--deadline', help='absolute UTC deadline, ISO 8601; overrides --hours')
    p.add_argument('--lanes', help='comma-separated lane names in priority order')
    p.add_argument('--max-attempts', type=int)
    p.add_argument('--resume', action='store_true', help='continue the run recorded in lab/overnight')
    p.add_argument('--skip-gate-baseline', action='store_true', help='do not prove the gates pass on the starting source')
    p.add_argument('--dry-run', action='store_true', help='print the first prompt and agent command, then exit')
    return p.parse_args(argv)


def load_config(args):
    cfg = read_json(args.config)
    cfg.setdefault('stall_attempts', 6)
    cfg.setdefault('suite_workers', 2)
    cfg.setdefault('gate_seconds', 1800)
    cfg.setdefault('kernel_test_packages', None)
    cfg.setdefault('minimize', dict(cases=4, workers=2))
    cfg.setdefault('rate_limit', dict(base_wait_seconds=300, max_wait_seconds=3600, total_wait_seconds=7200))
    cfg['agent'].setdefault('max_tool_calls', 40)
    for key, value in [('harness', args.harness), ('model', args.model), ('effort', args.effort), ('seconds', args.agent_seconds)]:
        if value is not None:
            cfg['agent'][key] = value
    if args.lanes:
        cfg['lane_order'] = [n.strip() for n in args.lanes.split(',') if n.strip()]
    if args.max_attempts is not None:
        cfg['max_attempts'] = args.max_attempts
    if args.deadline:
        cfg['deadline_utc'] = args.deadline
    elif args.hours is not None:
        cfg['budget_hours'] = args.hours
        cfg['deadline_utc'] = None
    lanes_in_order(cfg)
    for lane in cfg['lanes']:
        validate_editable(lane['editable'])
    evaluator = read_json(EVALUATOR)['revision']
    if cfg['evaluator'] != evaluator:
        raise RuntimeError(f"config expects evaluator {cfg['evaluator']!r} but lab/evaluator.json is {evaluator!r}")
    for split in ['public', 'heldout']:
        recorded = read_json(ROOT / f'results/frozen-baseline-{split}.json').get('evaluator')
        if recorded != evaluator:
            raise RuntimeError(f'results/frozen-baseline-{split}.json was recorded under {recorded!r}, not {evaluator!r}; re-baseline first')
    return cfg


def all_editable(cfg):
    seen = []
    for lane in cfg['lanes']:
        for path in lane['editable']:
            if path not in seen:
                seen.append(path)
    return seen


# ----- gates ---------------------------------------------------------------------------------------

def gate_packages(cfg, editable):
    """Crates a gate runs for: the configured list, or the closure affected by the editable paths.

    `None` for the whole CI workspace selection."""
    configured = cfg['kernel_test_packages']
    if configured == 'workspace' or editable is None:
        return None
    if configured:
        return configured
    return gates.affected_packages(editable)


def run_gates(directory, cfg, deadline, label, editable=None):
    """Kernel tests then the release check. Returns (passed, details)."""
    details = {}
    gates.prepare()
    (ROOT / 'gate-target').mkdir(exist_ok=True)
    packages = gate_packages(cfg, editable)
    details['packages'] = packages or 'workspace'
    for name, cmd in [('kernel_tests', gates.test_command(packages)), ('release_check', gates.release_command(packages))]:
        set_state(state=f'{label}:{name}')
        rc, seconds = run(cmd, directory / f'{name}.log', cfg['gate_seconds'], gates.ENV, deadline)
        details[name] = dict(exit=rc, seconds=seconds)
        if rc:
            return False, details
    return True, details


# ----- rate limits ---------------------------------------------------------------------------------

def backoff(run_state, cfg, deadline):
    """Sleep before retrying a rate-limited agent. Returns False when the run must stop."""
    limits = cfg['rate_limit']
    hits = run_state.get('rate_limit_hits', 0)
    wait = min(limits['base_wait_seconds'] * 2 ** hits, limits['max_wait_seconds'])
    total = run_state.get('rate_limit_wait', 0) + wait
    run_state.update(rate_limit_hits=hits + 1, rate_limit_wait=total)
    write_json(RUN / 'run.json', run_state)
    if total > limits['total_wait_seconds'] or time.time() + wait >= deadline:
        return False
    set_state(state='rate_limited', wait_seconds=wait, resume_at=iso(time.time() + wait))
    status('paused', f'Agent rate limited; waiting {wait} seconds before attempt {CURRENT + 1}.')
    end = time.time() + wait
    while time.time() < end:
        if (RUN / 'stop-after-attempt').exists():
            return False
        time.sleep(min(30, end - time.time()))
    return True


# ----- main loop ------------------------------------------------------------------------------------

def stopped(signum, frame):
    kill_child()
    if SNAPSHOT:
        restore(SNAPSHOT['data'], SNAPSHOT['paths'])
    set_state(state='stopped', signal=signum)
    raise SystemExit(128 + signum)


def start_run(args, cfg):
    """The run record: deadline, lane state and provenance. Created fresh or loaded on resume."""
    if (RUN / 'experiments.jsonl').exists() or (RUN / 'run.json').exists():
        if not args.resume:
            raise RuntimeError('lab/overnight already holds a run; pass --resume to continue it or move it away')
        run_state = read_json(RUN / 'run.json')
        if args.deadline or args.hours is not None:
            run_state['deadline'] = cfg['deadline_utc'] or iso(time.time() + cfg['budget_hours'] * 3600)
        run_state['resumed'] = run_state.get('resumed', []) + [now()]
    else:
        if args.resume:
            raise RuntimeError('nothing to resume in lab/overnight')
        run_state = dict(started=now(), deadline=cfg['deadline_utc'] or iso(time.time() + cfg['budget_hours'] * 3600),
                         revision=cfg['revision'], evaluator=cfg['evaluator'], agent=cfg['agent'],
                         kernel_commit=subprocess.check_output(['git', '-C', str(KERNEL), 'rev-parse', 'HEAD'], text=True).strip(),
                         lanes={}, rate_limit_hits=0, rate_limit_wait=0)
    write_json(RUN / 'run.json', run_state)
    return run_state


def retained_patch(cfg):
    """The whole retained diff against the pinned kernel, new files included."""
    pristine = {}
    for rel in editable_files(all_editable(cfg)):
        shown = subprocess.run(['git', '-C', str(KERNEL), 'show', 'HEAD:./' + rel], capture_output=True)
        if shown.returncode == 0:
            pristine[rel] = shown.stdout
    tracked = subprocess.check_output(['git', '-C', str(KERNEL), 'ls-files', '--'] + all_editable(cfg), text=True).splitlines()
    for rel in tracked:
        if rel not in pristine and rel.endswith('.rs'):
            pristine[rel] = subprocess.check_output(['git', '-C', str(KERNEL), 'show', 'HEAD:./' + rel])
    return unified_diff(pristine, snapshot(all_editable(cfg)))


def save_best_source(cfg):
    best = RUN / 'best-source'
    if best.exists():
        shutil.rmtree(best)
    for rel, data in snapshot(all_editable(cfg)).items():
        (best / rel).parent.mkdir(parents=True, exist_ok=True)
        (best / rel).write_bytes(data)


def restore_best_source(cfg):
    """On resume, put the editable paths back to the last kept state if they drifted."""
    best = RUN / 'best-source'
    if not best.exists():
        return False
    wanted = {str(p.relative_to(best)): p.read_bytes() for p in best.rglob('*.rs')}
    current = snapshot(all_editable(cfg))
    if wanted == current:
        return False
    restore(wanted, all_editable(cfg))
    return True


def main(argv=None):
    global CURRENT, SNAPSHOT
    args = parse_args(argv)
    cfg = load_config(args)
    RUN.mkdir(exist_ok=True)
    for sub in ['agent-home', 'agent-scratch', 'cache/cargo', 'tmp', 'target', 'gate-target']:
        (ROOT / sub).mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        lane = lanes_in_order(cfg)[0]
        print(prompt(cfg, lane, 1))
        print()
        print(' '.join(agent_command.command(cfg['agent'], '<prompt>', lane['editable'])))
        return
    lock = (RUN / 'controller.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (RUN / 'controller.pid').write_text(str(os.getpid()) + '\n')
    for sig in [signal.SIGTERM, signal.SIGINT]:
        signal.signal(sig, stopped)
    agent_command.forbid_api_keys(cfg['agent']['harness'])
    run_state = start_run(args, cfg)
    deadline = parse_deadline(run_state['deadline'])
    records = [json.loads(line) for line in (RUN / 'experiments.jsonl').read_text().splitlines()] if (RUN / 'experiments.jsonl').exists() else []
    if args.resume and restore_best_source(cfg):
        append(RUN / 'design-changes.jsonl', dict(at=now(), event='resume_restored_editable_files'))
    public = read_json(RUN / 'best-public.json' if records else ROOT / 'results/frozen-baseline-public.json')
    hidden = read_json(RUN / 'best-heldout.json' if records else ROOT / 'results/frozen-baseline-heldout.json')
    write_json(RUN / 'best-public.json', public)
    write_json(RUN / 'best-heldout.json', hidden)
    history = read_json(RUN / 'public-history.json') if (RUN / 'public-history.json').exists() else []
    keeps = sum(r['kept'] for r in records)
    last_revision = records[-1]['revision'] if records else None
    last_hour = time.time()
    failures = 0
    binary = ROOT / 'target/debug/kernel-probe'
    if not records:
        set_state(state='baseline')
        build_rc, build_s = run(compile_command(), RUN / 'baseline-build.log', cfg['compile_seconds'], COMPILE_ENV, deadline)
        if build_rc:
            raise RuntimeError('the starting source does not compile; see lab/overnight/baseline-build.log')
        if not args.skip_gate_baseline:
            ok, details = run_gates(RUN, cfg, deadline, 'baseline')
            run_state['gate_baseline'] = details
            write_json(RUN / 'run.json', run_state)
            if not ok:
                raise RuntimeError(f'the gates fail on the starting source: {details}; a gate that fails before any change is not a gate')
        run_state['probe_sha256'] = digest(binary.read_bytes())
        write_json(RUN / 'run.json', run_state)
        save_best_source(cfg)
    lane_state = run_state.setdefault('lanes', {})
    start_attempt = records[-1]['attempt'] + 1 if records else 1
    for i in range(start_attempt, 100000):
        CURRENT = i
        if time.time() >= deadline or i > cfg['max_attempts']:
            break
        while (RUN / 'pause-between-rounds').exists() and time.time() < deadline:
            set_state(state='between_rounds', keeps=keeps)
            time.sleep(5)
        if (RUN / 'stop-after-attempt').exists():
            (RUN / 'stop-after-attempt').unlink()
            set_state(state='stopped', reason='stop_requested', keeps=keeps)
            status('paused', f'Stopped on request after attempt {i - 1}; resume with --resume.')
            return
        if time.time() >= deadline:
            break
        lane, why = choose_lane(cfg, lane_state, public)
        if lane is None:
            set_state(state='finished', reason='no_visible_headroom', attempts=i - 1, keeps=keeps)
            status('working', 'Every visible case in every lane passes; the run stopped early with nothing left to gain.')
            break
        lane_state['current'] = lane['name']
        state = lane_state.setdefault(lane['name'], dict(attempts=0, kept=0, since_keep=0, stalls=0))
        write_json(RUN / 'run.json', run_state)
        directory = RUN / f'attempt-{i:03d}'
        directory.mkdir()
        allowed = lane['editable']
        frozen = fingerprint(allowed)
        write_json(directory / 'frozen-manifest.json', frozen)
        write_json(directory / 'config.json', dict(cfg, lane=lane['name'], lane_switch=why))
        if cfg['revision'] != last_revision:
            append(RUN / 'design-changes.jsonl', dict(at=now(), revision=cfg['revision'], config=cfg))
            last_revision = cfg['revision']
        before = snapshot(allowed)
        SNAPSHOT = dict(data=before, paths=allowed)
        set_state(state='minimizing', lane=lane['name'], keeps=keeps)
        write_json(ROOT / 'agent-scratch/feedback.json', feedback(public, hidden, lane, cfg, history, i, keeps, binary))
        text = prompt(cfg, lane, i)
        (directory / 'prompt.txt').write_text(text)
        set_state(state='proposing', lane=lane['name'], keeps=keeps, lane_switch=why)
        for stale in ['last-message.txt', 'partial.txt']:
            if (ROOT / 'agent-scratch' / stale).exists():
                (ROOT / 'agent-scratch' / stale).unlink()
        started = now()
        rc, seconds = run(agent_command.command(cfg['agent'], text, allowed), directory / 'agent.jsonl',
                          cfg['agent']['seconds'], agent_command.ENV, deadline)
        summary = agent_command.summary(cfg['agent'], directory / 'agent.jsonl')
        (directory / 'agent-summary.txt').write_text(summary)
        after = snapshot(allowed)
        diff = unified_diff(before, after)
        (directory / 'candidate.patch').write_text(diff)
        changed_files = sorted(rel for rel in set(before) | set(after) if before.get(rel) != after.get(rel))
        record = dict(attempt=i, lane=lane['name'], lane_switch=why, started=started, agent=cfg['agent'], agent_exit=rc,
                      agent_seconds=seconds, revision=cfg['revision'], evaluator=cfg['evaluator'], changed=bool(diff),
                      files_changed=changed_files, lines_added=sum(1 for l in diff.splitlines() if l.startswith('+') and not l.startswith('+++')),
                      lines_removed=sum(1 for l in diff.splitlines() if l.startswith('-') and not l.startswith('---')),
                      patch_sha256=digest(diff.encode()), kept=False, heldout_result='not_evaluated')
        if fingerprint(allowed) != frozen:
            raise RuntimeError('protected file changed')
        rate_limited = agent_command.rate_limited(directory / 'agent.jsonl') and (rc or not diff)
        newpub = newhid = None
        forbidden = forbidden_edits(before, after) if diff else []
        if rate_limited:
            record['reason'] = 'rate_limited'
        elif rc or not diff:
            record['reason'] = 'agent_timeout_or_failure' if rc else 'no_change'
        elif forbidden:
            record['reason'] = 'forbidden_edit'
            record['forbidden'] = forbidden
        else:
            set_state(state='compiling', lane=lane['name'], keeps=keeps)
            build_rc, build_s = run(compile_command(), directory / 'build.log', cfg['compile_seconds'], COMPILE_ENV, deadline)
            record.update(build_exit=build_rc, build_seconds=build_s)
            if build_rc:
                record['reason'] = 'build_failed'
            else:
                set_state(state='evaluating', lane=lane['name'], keeps=keeps)
                newpub, ep = suite(directory, 'public', 'first', cfg, deadline)
                newhid, eh = suite(directory, 'heldout', 'first', cfg, deadline)
                record.update(public_run=ep, hidden_run=eh)
                if newpub is None or newhid is None:
                    record['reason'] = 'evaluation_failed'
                else:
                    rp, rh = regress(public, newpub), regress(hidden, newhid)
                    nu = sorted(unsafe(newpub['rows'] + newhid['rows']) - unsafe(public['rows'] + hidden['rows']))
                    nr = sorted(runtime_failures(newpub['rows'] + newhid['rows']) - runtime_failures(public['rows'] + hidden['rows']))
                    base = score(public['rows'] + hidden['rows'])
                    sc = score(newpub['rows'] + newhid['rows'])
                    record.update(score_before=base['score'], score_after=sc['score'], public_score=newpub['score'],
                                  public_passed=newpub['passed'], heldout_score=newhid['score'], heldout_passed=newhid['passed'],
                                  lane_passed_before=lane_passed(public, lane), lane_passed_after=lane_passed(newpub, lane),
                                  public_regressions=rp, heldout_regressions=rh, new_incorrect_successes=nu,
                                  new_runtime_failures=nr, heldout_result='evaluated')
                    gain = newpub['passed'] > public['passed'] and sc['score'] > base['score'] and not rp and not rh and not nu and not nr
                    record['reason'] = 'regression' if rp or rh or nu or nr else 'no_gain'
                    if gain:
                        ok, details = run_gates(directory, cfg, deadline, 'gating', allowed)
                        record['gates'] = details
                        if not ok:
                            failed_gate = next(name for name, d in details.items() if name != 'packages' and d['exit'])
                            record['reason'] = failed_gate + '_failed'
                        else:
                            set_state(state='repeating', lane=lane['name'], keeps=keeps)
                            repeatpub, ep2 = suite(directory, 'public', 'repeat', cfg, deadline)
                            repeathid, eh2 = suite(directory, 'heldout', 'repeat', cfg, deadline)
                            stable = (repeatpub is not None and repeathid is not None and pass_map(newpub) == pass_map(repeatpub)
                                      and pass_map(newhid) == pass_map(repeathid))
                            record.update(repeat_public_run=ep2, repeat_hidden_run=eh2, stable=stable, kept=stable,
                                          reason='improved_without_regression' if stable else 'unstable_or_repeat_failed')
        if record['kept']:
            public, hidden = newpub, newhid
            keeps += 1
            write_json(RUN / 'best-public.json', public)
            write_json(RUN / 'best-heldout.json', hidden)
            (directory / 'kept.patch').write_text(diff)
            save_best_source(cfg)
            state.update(kept=state['kept'] + 1, since_keep=0)
            if keeps == 1:
                status('working', f"First improvement kept in lane {lane['name']}: score {record['score_before']:.6f} to {record['score_after']:.6f}; gates passed, repeat stable.")
        else:
            restore(before, allowed)
            if not rate_limited:
                state['since_keep'] = state.get('since_keep', 0) + 1
        SNAPSHOT = None
        if fingerprint(allowed) != frozen:
            raise RuntimeError('protected file changed after evaluation')
        if not rate_limited:
            state['attempts'] = state.get('attempts', 0) + 1
        record.update(finished=now(), keeps=keeps)
        append(RUN / 'experiments.jsonl', record)
        print(json.dumps(record), flush=True)
        entry = {k: v for k, v in record.items() if k in ['attempt', 'lane', 'agent_exit', 'build_exit', 'reason', 'kept', 'public_score',
                                                              'public_passed', 'public_regressions', 'files_changed', 'forbidden', 'gates']}
        entry['hypothesis'] = summary[:2000]
        if record['reason'] == 'build_failed':
            entry['build_error'] = '\n'.join((directory / 'build.log').read_text().splitlines()[-65:])[-7000:]
        for gate in ['kernel_tests', 'release_check']:
            if record['reason'] == gate + '_failed':
                log = (directory / f'{gate}.log').read_text(errors='replace').splitlines()
                failing = [l for l in log if 'FAILED' in l or l.startswith('error') or 'panicked' in l]
                entry['gate_error'] = '\n'.join(failing[-40:] + log[-25:])[-7000:]
        if newpub is not None and not record['kept']:
            changed_ids = set(record.get('public_regressions', [])) | {x for x in record.get('new_incorrect_successes', []) + record.get('new_runtime_failures', []) if x.startswith('public-')}
            entry['visible_vetoes'] = [dict(case=read_json(ROOT / 'corpus/public' / (r['id'] + '.json')), result={k: v for k, v in r.items() if k != 'actual'})
                                       for r in newpub['rows'] if r['id'] in changed_ids][:8]
        history.append(entry)
        write_json(RUN / 'public-history.json', history)
        (ROOT / 'agent-scratch/last-candidate.patch').write_text(diff)
        write_json(RUN / 'run.json', run_state)
        if rate_limited:
            if not backoff(run_state, cfg, deadline):
                set_state(state='stopped', reason='rate_limit_budget_exhausted', keeps=keeps)
                status('blocked', 'Agent rate limit wait budget used up; the run stopped cleanly and can be resumed with --resume.')
                return
            continue
        failures = failures + 1 if record['reason'] == 'agent_timeout_or_failure' else 0
        if failures >= 3:
            raise RuntimeError('three consecutive agent failures; supervisor intervention required')
        if time.time() - last_hour >= 3600:
            append(RUN / 'hourly-checks.jsonl', dict(at=now(), attempt=i, keeps=keeps, lane=lane['name'],
                                                     score=score(public['rows'] + hidden['rows'])['score'], controller_pid=os.getpid()))
            last_hour = time.time()
    (RUN / 'kept.patch').write_text(retained_patch(cfg))
    final = read_json(RUN / 'controller-state.json')
    if final.get('state') != 'finished':
        set_state(state='finished', reason='deadline_or_attempt_limit', attempts=(CURRENT or 1) - 1, keeps=keeps,
                  score=score(public['rows'] + hidden['rows'])['score'])
    status('working', 'Search window finished; results are ready for final audit.')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        kill_child()
        if SNAPSHOT:
            restore(SNAPSHOT['data'], SNAPSHOT['paths'])
        set_state(state='failed', error=str(e))
        status('blocked', f'Controller stopped: {e}. Evidence is in lab/overnight.')
        traceback.print_exc()
        raise
