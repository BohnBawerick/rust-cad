# Round 2 launch sheet

Round 2 runs the search loop described in [`lab/README.md`](lab/README.md) against the kernel in this repository, with the round 1 weaknesses closed: the kernel's own tests and the release check are hard keep gates, the oracle judges each shell on its own and cannot be satisfied by gluing bodies together, the agent works in lanes with a few editable modules each and moves on when a lane has nothing visible left to gain, and every failing case reaches it minimized.

Public rules for everything the run produces: synthetic or public geometry only, no private paths in anything committed (redact to `/workspace` as round 1 did), no credentials or tokens anywhere under version control. `lab/agent-home/`, `lab/overnight/` and the caches are ignored by git for that reason.

## Starting point

Round 2 starts from the **unpatched kernel**, monstertruck `d2ad1ed7`, judged by evaluator `oracle-v2`. The round 1 kept patches were re-validated prefix by prefix under the new gates (`research/2026-10-13-round2-prep/`): no prefix passes the kernel's own boolean tests, so none is applied. The first kept patch already breaks `punched_cube`, and the full stack breaks `adjacent_cubes_or`. Their ideas remain available to the agent only through the research record, which it cannot see; it must derive them again under gates that would have rejected them.

Frozen baseline under `oracle-v2` on that source:

| Split | Passed | Score |
| --- | ---: | ---: |
| public | 122/318 | 58.7425372457 |
| held-out | 39/102 | 60.6481481481 |
| combined | 161/420 | 59.7364373100 |

## Preflight

All commands run from the repository root. Steps 1 to 3 are one-off per machine.

1. Codex CLI installed and signed in with a ChatGPT account. Copy its login:

   ```bash
   mkdir -p lab/agent-home/.codex && cp ~/.codex/auth.json lab/agent-home/.codex/auth.json && chmod 600 lab/agent-home/.codex/auth.json
   ```

   The controller refuses to start if that file holds an API key or if `OPENAI_API_KEY` is set. Rate limits back off and stop; they never fall through to a paid key.

2. Kernel test resources (the gates read fixtures from them):

   ```bash
   mkdir -p kernel/resources && cd kernel/resources && git init -q && \
     git remote add origin https://github.com/ricosjp/resources4truck.git && \
     git fetch -q --depth 1 origin 9bf9de1426c5fc2f2b8d63f501dca0d3c53ebd91 && git checkout -q FETCH_HEAD && cd ../..
   ```

3. Probe, dependency cache and checks:

   ```bash
   mkdir -p lab/agent-home lab/agent-scratch lab/cache/cargo lab/tmp lab/target lab/gate-target lab/logs
   . lab/env.sh
   cargo build --locked --manifest-path lab/probe/Cargo.toml
   cp lab/target/debug/kernel-probe lab/target/baseline-probe
   cp lab/upstream-tests/Cargo.lock kernel/Cargo.lock && (cd kernel && cargo fetch --locked)
   python3 lab/test_oracle.py && python3 lab/test_controller.py
   ```

4. Confirm the baseline reproduces on this machine before every launch:

   ```bash
   python3 lab/verify.py suite public --out lab/tmp/public.json --workers 3 && python3 lab/compare_baseline.py public lab/tmp/public.json
   python3 lab/verify.py suite heldout --out lab/tmp/heldout.json --workers 3 && python3 lab/compare_baseline.py heldout lab/tmp/heldout.json
   ```

   Both must print no `REGRESSION` line and no new passes. `lab/overnight/` must not exist from an earlier run; move it into `research/` or delete it.

## Launch

```bash
. lab/env.sh
nohup python3 lab/overnight.py --harness codex --model gpt-6-astra --effort high --hours 5 \
  --lanes planar,revolve,fillet,curved,step > lab/logs/round2.log 2>&1 &
echo $! > lab/overnight-launcher.pid
python3 lab/watch_loop.py &
```

Those flags repeat the defaults in `lab/loop-config.json`, so plain `python3 lab/overnight.py` is the same run; they are spelled out so the record shows what was asked for. Before attempt 1 the controller compiles the probe and proves the full gate selection (kernel tests and release check for the whole CI workspace) on the starting source; cold, that takes about 15 minutes and is part of the 5 hours. `--hours` counts from launch; pass `--deadline 2026-10-14T06:00:00Z` instead to pin an absolute end.

Per attempt the agent has 900 seconds and 40 tool calls at `high` reasoning effort. Compile, two suites, the lane's gates and the repeat run add 4 to 12 minutes to a candidate that gains, so expect 12 to 25 attempts in 5 hours. Edit `lab/loop-config.json` while the run is going to change budgets or lane order; it is read before every attempt.

## Lanes, in priority order

Visible headroom is counted on the public split under the frozen baseline. Each lane's editable paths are in `lab/loop-config.json`; its gate covers the crates owning those paths and everything that depends on them.

| Lane | Groups | Visible failing | Editable modules | Success looks like |
| --- | --- | ---: | --- | --- |
| planar | boxes | 117 of 157 | `monstertruck-solid` classic boolean pipeline, polyline construction, the `integrate` entry points, `alternative.rs` | Disjoint, containing, contained, face-, edge- and vertex-touching, thin and near-coincident box pairs pass for all three operations. Touching unions come back as two closed shells; a face-sharing union as one. |
| revolve | revolve | 1 of 13 | `monstertruck-modeling` builder and sweeps, `revolved_curve.rs`, `monstertruck-meshing` tessellation | The remaining revolve case stops losing 22% of its volume, and no apex degenerate triangles are needed to close a revolved shell. |
| fillet | fillet | 14 of 14 | `monstertruck-fillet`, the modeling fillet glue, the rolling-ball and approximate fillet surfaces, edge blends | A one-edge round fillet passes the kernel's geometric consistency check without the check being loosened. |
| curved | cylinders, holes | 63 of 91 | the planar modules plus `intersection_curve` | Equal-radius cylinder pairs at every spacing, including coincident and tangent, and the box through hole as one genus-one shell. |
| step | step | 1 of 4 | `monstertruck-io` STEP load, `monstertruck-assembly` | The NIST assembly import returns solids. |

The loop leaves a lane when it has no failing visible case or after 6 attempts without a keep, and returns to it after visiting the others. Revolve is second because the captain asked for it; with one visible case it will be short.

## What success and failure look like

Success for the round is any kept change, because every keep now means: a visible gain, no regression on either split, no new wrong success or crash, the kernel's own tests for the affected crates green, a warning-free release check, and verdicts that repeat. Several keeps in the planar lane that bring box booleans from 57 to past 150 of 208 combined would match round 1's early progress under rules that would have rejected round 1's stack. A keep in the fillet lane would be new ground; nothing improved fillets in round 1.

Partial success is a run whose rejected attempts are informative: candidates that gained and then failed a gate (`kernel_tests_failed`, `release_check_failed`) show exactly which kernel test the idea broke. Those records are the input to the next design pass.

Failure is a run with no keeps and no gate-failed candidates, that is, the agent never produced a compiling, gaining change; or a run that ends on the rate-limit budget or on three consecutive agent failures. A run that stops early with `no_visible_headroom` is not a failure; it means every lane's visible cases pass and the held-out and sealed audits decide what that is worth.

Numbers that matter afterwards: `combined_score` and `combined_passed` from `lab/review_run.py`, the per-group table, the count of attempts by `reason`, and `lab/final_audit.py`'s sealed-sample comparison. A score rise with sealed regressions is not progress.

## Stop rules

The controller stops on its own when:

- the deadline passes or `max_attempts` is reached (`finished`, reason `deadline_or_attempt_limit`);
- no lane has a failing visible case (`finished`, reason `no_visible_headroom`);
- the agent has been rate limited for `rate_limit.total_wait_seconds` (2 hours) in total, or a wait would cross the deadline (`stopped`, reason `rate_limit_budget_exhausted`);
- the agent fails or times out three times in a row (`failed`);
- a protected file changed, the starting source does not compile, or a gate fails on the starting source (`failed`).

Stop it by hand with `touch lab/overnight/stop-after-attempt` for a clean stop after the current attempt, or `kill $(cat lab/overnight/controller.pid)` (SIGTERM) to stop now; both restore the editable files. Continue a stopped or killed run with `python3 lab/overnight.py --resume`, adding `--hours` or `--deadline` to extend the window. `lab/overnight/controller-state.json` shows the current state and lane; `lab/overnight/experiments.jsonl` has one record per attempt.

## After the run

```bash
. lab/env.sh
python3 lab/final_audit.py
python3 lab/review_run.py
python3 lab/contact_audit.py          # needs lab/target/final-probe from final_audit
```

Then move `lab/overnight/`, `lab/final-audit/`, `lab/contact-audit/`, `lab/results/run-review.json` and the logs into `research/<date>-round2/` as round 1 was recorded, redact absolute paths, drop the raw agent transcripts, and write the README from the numbers. Kept patches are evidence, not fixes: each root cause still gets its own reviewed change before it lands in `kernel/`.
