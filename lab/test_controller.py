#!/usr/bin/env python3
"""Unit checks for the controller's pure logic. No agent, no kernel build.

    python3 lab/test_controller.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_command  # noqa: E402
import overnight  # noqa: E402
from minimize import move_to_origin, round_dimensions  # noqa: E402

checks = {}


def result(rows):
    return dict(rows=[dict(id=f'public-{i:03d}', group=g, pass_=p, reasons=[]) | {'pass': p} for i, (g, p) in enumerate(rows)])


# --- lane choice ---------------------------------------------------------------------------------
cfg = dict(stall_attempts=2, lane_order=['planar', 'fillet'],
           lanes=[dict(name='planar', groups=['boxes'], editable=[]), dict(name='fillet', groups=['fillet'], editable=[])])
public = result([('boxes', False), ('boxes', True), ('fillet', False)])
state = {}
lane, why = overnight.choose_lane(cfg, state, public)
checks['first_open_lane_is_entered'] = (lane['name'], why) == ('planar', 'entered')
state['current'] = 'planar'
state['planar'] = dict(since_keep=1)
lane, why = overnight.choose_lane(cfg, state, public)
checks['lane_continues_below_stall'] = (lane['name'], why) == ('planar', 'continue')
state['planar'] = dict(since_keep=2)
lane, why = overnight.choose_lane(cfg, state, public)
checks['stalled_lane_hands_over'] = (lane['name'], why) == ('fillet', 'stalled') and state['planar']['since_keep'] == 0 and state['planar']['stalls'] == 1
state['current'] = 'fillet'
state['fillet'] = dict(since_keep=5)
lane, why = overnight.choose_lane(cfg, state, public)
checks['stall_wraps_around'] = (lane['name'], why) == ('planar', 'stalled')
closed = result([('boxes', True), ('fillet', False)])
state['current'] = 'planar'
state['planar'] = dict(since_keep=0)
lane, why = overnight.choose_lane(cfg, state, closed)
checks['closed_lane_is_skipped'] = (lane['name'], why) == ('fillet', 'lane_closed')
done = result([('boxes', True), ('fillet', True)])
checks['no_headroom_stops'] = overnight.choose_lane(cfg, state, done) == (None, 'no_visible_headroom')
only = dict(cfg, lane_order=['planar'])
state = {'current': 'planar', 'planar': dict(since_keep=9)}
lane, why = overnight.choose_lane(only, state, public)
checks['single_lane_keeps_going_after_stall'] = (lane['name'], why) == ('planar', 'stalled_only_lane')

# --- forbidden edits -------------------------------------------------------------------------------
src = b'pub fn f() {}\n#[cfg(test)]\nmod tests {\n    #[test]\n    fn t() { assert!(true); }\n}\n'
checks['test_block_extracted'] = overnight.test_blocks(src.decode()) == ['#[cfg(test)]\nmod tests {\n    #[test]\n    fn t() { assert!(true); }\n}']
checks['unchanged_test_block_allowed'] = overnight.forbidden_edits({'a/mod.rs': src}, {'a/mod.rs': src.replace(b'{}', b'{ let _x = 1; }')}) == []
checks['edited_test_block_rejected'] = any('cfg(test)' in r for r in overnight.forbidden_edits({'a/mod.rs': src}, {'a/mod.rs': src.replace(b'assert!(true)', b'assert!(false)')}))
checks['removed_test_block_rejected'] = any('cfg(test)' in r for r in overnight.forbidden_edits({'a/mod.rs': src}, {'a/mod.rs': b'pub fn f() {}\n'}))
checks['added_test_block_allowed'] = overnight.forbidden_edits({'a/mod.rs': src}, {'a/mod.rs': src + b'#[cfg(test)]\nmod more {}\n'}) == []
checks['test_file_rejected'] = any('test file' in r for r in overnight.forbidden_edits({'a/tests.rs': b'x'}, {'a/tests.rs': b'y'}))
checks['tests_dir_rejected'] = any('test file' in r for r in overnight.forbidden_edits({}, {'a/tests/new.rs': b'y'}))
checks['new_source_file_allowed'] = overnight.forbidden_edits({}, {'a/helper.rs': b'pub fn g() {}\n'}) == []
checks['non_rust_file_rejected'] = any('not a Rust' in r for r in overnight.forbidden_edits({}, {'a/notes.md': b'y'}))
inline = b'#[cfg(test)] use x::y;\nfn f() {}\n'
checks['item_level_cfg_test_handled'] = overnight.test_blocks(inline.decode()) == ['#[cfg(test)] use x::y;']

# --- snapshots, diffs and restore on a scratch kernel -----------------------------------------------
with tempfile.TemporaryDirectory() as td:
    kernel = Path(td) / 'kernel'
    (kernel / 'crate/src').mkdir(parents=True)
    (kernel / 'crate/src/mod.rs').write_text('fn a() {}\n')
    (kernel / 'crate/src/other.rs').write_text('fn b() {}\n')
    (kernel / 'crate/src/notes.txt').write_text('ignored\n')
    overnight.KERNEL = kernel
    paths = ['crate/src']
    before = overnight.snapshot(paths)
    checks['snapshot_lists_rust_files_only'] = sorted(before) == ['crate/src/mod.rs', 'crate/src/other.rs']
    (kernel / 'crate/src/mod.rs').write_text('fn a() { 1 }\n')
    (kernel / 'crate/src/new.rs').write_text('fn c() {}\n')
    (kernel / 'crate/src/other.rs').unlink()
    after = overnight.snapshot(paths)
    diff = overnight.unified_diff(before, after)
    checks['diff_covers_change_add_remove'] = all(s in diff for s in ['--- a/crate/src/mod.rs', '+++ /dev/null', '--- /dev/null', '+fn c() {}'])
    overnight.restore(before, paths)
    checks['restore_recovers_snapshot'] = overnight.snapshot(paths) == before and not (kernel / 'crate/src/new.rs').exists()
    checks['validate_rejects_tests_dir'] = False
    try:
        overnight.validate_editable(['crate/src/tests'])
    except ValueError:
        checks['validate_rejects_tests_dir'] = True
    checks['validate_rejects_missing'] = False
    try:
        overnight.validate_editable(['crate/missing'])
    except ValueError:
        checks['validate_rejects_missing'] = True
    overnight.validate_editable(['crate/src', 'crate/src/mod.rs'])
    checks['validate_accepts_dir_and_file'] = True

# --- rate limits ----------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    log = Path(td) / 'agent.jsonl'
    log.write_text('{"type":"error","message":"You have hit your usage limit. Try again in 3 hours."}\n')
    checks['usage_limit_detected'] = agent_command.rate_limited(log)
    log.write_text('{"type":"error","message":"HTTP 429 Too Many Requests"}\n')
    checks['http_429_detected'] = agent_command.rate_limited(log)
    log.write_text('{"type":"item.completed","text":"the rate of convergence is limited by tolerance"}\n')
    checks['ordinary_text_not_flagged'] = not agent_command.rate_limited(log)
    checks['missing_log_not_flagged'] = not agent_command.rate_limited(Path(td) / 'absent')

# --- harness commands ------------------------------------------------------------------------------
agent_command.binary_dir = lambda name: Path('/opt/fake')
codex = agent_command.command(dict(harness='codex', model='gpt-6-astra', effort='high'), 'P', ['monstertruck-solid/src'])
checks['codex_uses_model_and_effort'] = '-m' in codex and codex[codex.index('-m') + 1] == 'gpt-6-astra' and 'model_reasoning_effort="high"' in codex
checks['codex_runs_ephemeral_without_user_config'] = '--ephemeral' in codex and '--ignore-user-config' in codex
with tempfile.TemporaryDirectory() as td:
    log = Path(td) / 'agent.jsonl'
    log.write_text('{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}\n{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":1}}\n')
    checks['codex_usage_summed'] = agent_command.usage(dict(harness='codex'), log) == {'input_tokens': 15, 'output_tokens': 3}
checks['codex_mounts_editable_rw'] = '--bind' in codex and any(a.endswith('monstertruck-solid/src') for a in codex)
checks['probe_source_mounted_read_only'] = '/work/probe' in codex
claude = agent_command.command(dict(harness='claude', model='claude-opus-5-5', effort='high'), 'P', [])
checks['claude_uses_model_and_effort'] = claude[claude.index('--model') + 1] == 'claude-opus-5-5' and claude[claude.index('--effort') + 1] == 'high'
checks['unknown_harness_rejected'] = False
try:
    agent_command.command(dict(harness='other', model='m', effort='e'), 'P', [])
except ValueError:
    checks['unknown_harness_rejected'] = True
checks['no_api_key_in_agent_env'] = not any(k in agent_command.ENV for k in agent_command.API_KEY_VARIABLES)

# --- minimizer steps keep relations exact ---------------------------------------------------------------
touch = dict(op='union', a=dict(kind='box', origin=[1.234, 2.345, 3.456], size=[1.2345, 2.3456, 3.4567]),
             b=dict(kind='box', origin=[1.234 + 1.2345, 2.345 + 2.3456, 3.456], size=[1.2345, 2.3456, 3.4567]), rotation=.31)
moved = move_to_origin(touch)
checks['move_to_origin_keeps_offsets'] = moved['a']['origin'] == [0, 0, 0] and abs(moved['b']['origin'][0] - 1.2345) < 1e-12
rounded = round_dimensions(moved)
checks['round_keeps_shared_planes'] = rounded['b']['origin'][0] == rounded['a']['size'][0] and rounded['b']['origin'][1] == rounded['a']['size'][1]
checks['round_keeps_equal_sizes'] = rounded['b']['size'] == rounded['a']['size']
cyl = dict(op='union', a=dict(kind='cylinder', origin=[0, 0, 0], radius=.7119, height=.79), b=dict(kind='cylinder', origin=[1.4238, 0, 0], radius=.7119, height=.79))
rc = round_dimensions(cyl)
checks['round_keeps_tangent_ratio'] = abs(rc['b']['origin'][0] / rc['a']['radius'] - 2) < 1e-9

print(json.dumps(checks, indent=2))
failed = [k for k, ok in checks.items() if not ok]
if failed:
    print('FAILED: ' + ', '.join(failed), file=sys.stderr)
    sys.exit(1)
