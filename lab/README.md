# Verification lab

Everything here assumes you run commands from the repository root. Python scripts locate their files relative to this directory, and `lab/kernel/source` is a link to `../../kernel`, so the probe and the controller find the kernel where the original prototype kept it.

The root [README](../README.md) covers building the probe and reproducing the baseline. [`ROUND2.md`](../ROUND2.md) is the launch sheet for the next search. This file covers the pieces.

## Files

| File | Role |
| --- | --- |
| `probe/` | `kernel-probe`. One recipe in; mesh and topology observations out as JSON, one point and triangle range per B-rep shell. |
| `verify.py` | Frozen evaluator. `case <recipe>` judges one recipe, `suite public\|heldout --out <file> [--workers n]` judges a split. `--binary` picks a different probe build. Every suite result carries the evaluator revision. |
| `oracle.py` | Closed-form expectations, the per-shell closure check and the body count used by `verify.py`. |
| `evaluator.json`, `EVALUATOR-CHANGES.md` | The evaluator revision and the log of every change to it, with controls and re-baseline numbers. |
| `test_oracle.py` | Rejection controls: a valid cube and broken variants, the contact contract on synthetic two-body meshes, and the seven round 1 contact results judged as round 1 judged them. Expects `target/baseline-probe`. |
| `compare_baseline.py` | The CI gate. Compares a suite result with `results/frozen-baseline-<split>.json` and refuses to compare across evaluator revisions. |
| `check_identities.py`, `contact_audit.py` | Diagnostics. Boolean volume identities, and the contact cases judged shell by shell next to the merged-mesh view. Neither changes the score. |
| `generate.py` | Regenerates the public (seed 73129) and held-out (seed 946271) recipes. Running it overwrites `corpus/`. |
| `overnight.py` | The round 2 search controller: lanes, hard gates, minimized failures, rate-limit backoff, resumable runs. `--dry-run` prints the first prompt and sandbox command. |
| `loop-config.json` | Agent harness, model, effort and per-attempt budget; wall-clock budget; lanes with their groups, editable paths and focus; gate and minimizer settings. Read on every attempt, so a running loop picks up edits. |
| `agent_command.py` | The sandboxed agent command for the `codex` and `claude` harnesses, the rate-limit detector and the API-key guard. |
| `compile_command.py` | The offline, sandboxed probe compile. |
| `gates.py` | The kernel test suite and the release check with warnings denied, offline, for the crates an editable path affects. Also a CLI: `python3 lab/gates.py tests\|release\|affected`. |
| `minimize.py` | Shrinks a failing recipe to the simplest variant that still fails the same way. |
| `test_controller.py` | Unit checks for lane choice, forbidden edits, snapshots, rate-limit detection, harness commands and the minimizer. No agent, no build. |
| `watch_loop.py` | Independent liveness monitor for a running controller. |
| `final_audit.py` | After a run, rebuilds the retained source in a clean target, repeats both suites and judges a fresh sealed sample. |
| `review_run.py` | Replays the kept patches and summarises a finished run. |
| `revalidate_round1.py` | Applies the round 1 kept patches prefix by prefix and judges each under the current evaluator and gates. Its record is in `research/2026-10-13-round2-prep/`. |
| `upstream-tests/Cargo.lock` | The dependency lock used for kernel tests and the gates. |
| `kernel-pin.json`, `fixture-manifest.json` | Kernel commit and NIST fixture provenance. |

## How an attempt runs

1. **Lane.** The controller takes the first lane in `lane_order` that still has failing visible cases. A lane that has gone `stall_attempts` attempts without a keep hands over to the next open lane and gets another turn later. With no failing visible case in any lane the run stops; round 1 burned its last 82 minutes on a file with nothing left to gain.
2. **Feedback.** `agent-scratch/feedback.json` holds up to `minimize.cases` of the lane's visible failures in minimized form (unrotated, at the origin, round dimensions, still failing with the same reasons under the current probe), the expected and actual mass properties and topology, the remaining visible failures, what earlier attempts in the lane tried and why they were rejected, and the last rejected patch. The probe source is mounted read-only at `/work/probe` so the agent can see how a recipe becomes kernel calls.
3. **Agent.** `codex exec` or `claude -p` runs in Bubblewrap with the kernel read-only except the lane's editable paths (files or whole directories), its own scratch directory and a private home holding only a subscription login. The model, effort, seconds and tool-call budget come from the config or the command line.
4. **Pre-build rejection.** A candidate that touched a test file, an existing `#[cfg(test)]` block, a non-Rust file, or anything outside the editable paths is rejected before it is built.
5. **Compile and score.** The probe is compiled offline. Both suites run. The candidate must raise the visible pass count with no case that passed before now failing, no new incorrect success and no new timeout, crash or panic, on either split.
6. **Hard gates.** The kernel's own tests for the crates the editable paths affect and every crate that depends on them, then `cargo check --release` for the same crates, which is where every crate's `deny(warnings)` applies. Both offline, both must pass. The whole CI workspace selection is proved once on the starting source before attempt 1.
7. **Repeat.** Both suites run again and every verdict must repeat.
8. **Keep or restore.** A kept candidate updates `best-*.json`, its diff is saved as `kept.patch` in the attempt directory and the editable files are mirrored to `overnight/best-source/`. Otherwise the editable paths are restored from the pre-attempt snapshot, new files included.

The controller hashes every protected file before and after each attempt and stops if one changed. Every attempt leaves its prompt, agent log, diff, build log, suite verdicts and gate logs in `overnight/attempt-NNN/` and one record in `overnight/experiments.jsonl`.

### Rate limits and stops

When the agent log shows a usage or rate limit, the attempt is recorded as `rate_limited`, the controller waits `rate_limit.base_wait_seconds` doubling each time up to `max_wait_seconds`, and stops cleanly once `total_wait_seconds` of waiting is used. The agent environment is a fixed allow-list without API keys, `forbid_api_keys` refuses to start if one is present in the agent home or the process environment, and the agent home is the only credential source the sandbox can see, so a limit can only slow the run down or stop it.

`touch lab/overnight/pause-between-rounds` holds the loop between attempts; `touch lab/overnight/stop-after-attempt` stops it cleanly after the current attempt. SIGTERM and SIGINT restore the editable files and record a `stopped` state. `python3 lab/overnight.py --resume` continues from the records, restoring the editable paths to the last kept state first if they drifted.

## Running a search

1. Install the [Codex CLI](https://github.com/openai/codex) and sign in with a ChatGPT account. Copy its `auth.json` into `lab/agent-home/.codex/auth.json` with mode 600. Git ignores `lab/agent-home/`. Never commit it. For the `claude` harness, copy `~/.claude/.credentials.json` to `lab/agent-home/.claude/.credentials.json` instead.
2. Fetch the kernel's test resources once (the kernel tests read fixtures from them; CI does the same):

   ```bash
   mkdir -p kernel/resources && cd kernel/resources && git init -q && \
     git remote add origin https://github.com/ricosjp/resources4truck.git && \
     git fetch -q --depth 1 origin 9bf9de1426c5fc2f2b8d63f501dca0d3c53ebd91 && git checkout -q FETCH_HEAD && cd ../..
   ```

3. Build the probe and fetch the kernel dependencies into the lab cache, then prove the gates on the starting source:

   ```bash
   mkdir -p lab/agent-home lab/agent-scratch lab/cache/cargo lab/tmp lab/target lab/gate-target lab/logs
   . lab/env.sh
   cargo build --locked --manifest-path lab/probe/Cargo.toml
   cp lab/target/debug/kernel-probe lab/target/baseline-probe
   cp lab/upstream-tests/Cargo.lock kernel/Cargo.lock && (cd kernel && cargo fetch --locked)
   python3 lab/test_oracle.py && python3 lab/test_controller.py
   python3 lab/gates.py tests && python3 lab/gates.py release
   ```

   The first gate run compiles the workspace cold and takes about 15 minutes; later runs only rebuild what changed.

4. Check that `results/frozen-baseline-*.json` were recorded under the evaluator revision in `evaluator.json` and on the exact kernel source you will search from. If not, re-baseline:

   ```bash
   python3 lab/verify.py suite public --out lab/results/frozen-baseline-public.json --workers 3
   python3 lab/verify.py suite heldout --out lab/results/frozen-baseline-heldout.json --workers 3
   ```

5. Start the controller. Defaults come from `loop-config.json`; flags override them:

   ```bash
   python3 lab/overnight.py --harness codex --model gpt-6-astra --effort high --hours 5 --lanes planar,revolve,fillet,curved,step
   ```

   `RESEARCH_STATUS_HOOK`, if set, names a Python script that receives a state and a message when the first change is kept, when the run pauses for a rate limit, when it ends and when it fails.

The controller writes everything to `lab/overnight/`, which git ignores, and refuses to start if a run is already recorded there without `--resume`. When it finishes, `lab/overnight/kept.patch` holds the retained diff relative to `kernel/`. Run `python3 lab/final_audit.py`, then `python3 lab/review_run.py`, then move the run into `research/<date>-<name>/` as the first run was.

## What the sandboxes allow

- The coding agent sees the kernel source read-only, except the lane's editable paths, plus the probe source read-only, its scratch directory and its own home. It has network access, because the subscription login needs it. So this is a filesystem boundary, not a full security boundary. The prompt forbids network research and web search is disabled in the harness.
- Compilation, the kernel tests and the release check run offline with only the kernel source, the probe, the Cargo cache and a target directory mounted.
- Each probe run gets one stripped recipe, no network, no corpus and no credentials, under `prlimit` limits of 4 GiB address space, 8 CPU seconds and a 16 MiB output file.

## Changing the evaluator

Do not edit `oracle.py`, `verify.py` or the probe during a run. A change is a new evaluator revision: bump `evaluator.json`, add an entry to `EVALUATOR-CHANGES.md` with the reason and the controls that prove it, extend `test_oracle.py`, re-record both baselines under the new revision and compare the verdicts case by case with the previous ones. The loop refuses to start when the config, `evaluator.json` and the baselines disagree.

## Studying the round 1 patches

`research/2026-10-13-overnight/kept.patch` is the whole round 1 stack. To apply it for study, not to ship it:

```bash
git apply --directory=kernel research/2026-10-13-overnight/kept.patch
. lab/env.sh
cargo build --locked --manifest-path lab/probe/Cargo.toml
python3 lab/verify.py suite public --out lab/tmp/public-patched.json
```

Revert with `git checkout -- kernel` when you are done. `python3 lab/revalidate_round1.py` judges each cumulative prefix of the 12 kept patches under the current evaluator and gates and leaves the kernel as it found it.
