# Verification lab

Everything here assumes you run commands from the repository root. Python scripts locate their files relative to this directory, and `lab/kernel/source` is a link to `../../kernel`, so the probe and the controller find the kernel where the original prototype kept it.

The root [README](../README.md) covers building the probe, reproducing the baseline and running the kernel's tests. This file covers the rest.

## Files

| File | Role |
| --- | --- |
| `probe/` | `kernel-probe`. One recipe in, mesh and topology observations out as JSON. |
| `verify.py` | Frozen evaluator. `case <recipe>` judges one recipe, `suite public\|heldout --out <file>` judges a split. `--binary` picks a different probe build. |
| `oracle.py` | Closed-form expectations and the independent mesh integrals used by `verify.py`. |
| `check_identities.py` | Checks `V(A-B)+V(A∩B)=V(A)` and `V(A∪B)+V(A∩B)=V(A)+V(B)` across a suite result. Diagnostic only. It does not change the score. |
| `contact_audit.py` | Re-checks seven contact cases after merging collinear edge subdivisions. Expects `target/final-probe`. |
| `compare_baseline.py` | The CI gate. Compares a suite result with `results/frozen-baseline-<split>.json`. |
| `test_oracle.py` | Feeds the oracle a valid cube and five broken variants and asserts it accepts only the valid one, plus three disjoint-box formula checks. Expects `target/baseline-probe`. |
| `generate.py` | Regenerates the public (seed 73129) and held-out (seed 946271) recipes. Running it overwrites `corpus/`. |
| `overnight.py` | The search controller. |
| `agent_command.py` | Builds the sandboxed coding-agent command. |
| `compile_command.py` | Builds the offline, sandboxed compile command. |
| `loop-config.json` | Deadline, budgets, the editable file list and the task focus. Read on every attempt. |
| `watch_loop.py` | Independent liveness monitor for a running controller. |
| `final_audit.py` | After a run, rebuilds the retained source in a clean target and tests it on fresh recipes. |
| `review_run.py` | Replays the kept patches and summarises a finished run. |
| `run_upstream.py`, `audit_upstream_baseline.py` | Run the kernel's own `monstertruck-solid` tests with and without the retained change. |
| `upstream-tests/Cargo.lock` | The dependency lock used for kernel tests. |
| `kernel-pin.json`, `fixture-manifest.json` | Kernel commit and NIST fixture provenance. |

`verify.py`, `oracle.py`, `check_identities.py` and `contact_audit.py` are byte-identical to the versions the overnight run used. Change them only as a new, recorded evaluator revision, and re-run the baseline under that revision before you compare anything.

## Running a new search

Do not start a search until the next steps in the root README are done. The current oracle rewards contact results it should not, and the loop does not yet run the kernel's own tests or a release build.

When you do run one:

1. Install the [Codex CLI](https://github.com/openai/codex) and sign in with your own account. Copy its `auth.json` into `lab/agent-home/.codex/auth.json` with mode 600. Git ignores `lab/agent-home/`. Never commit it.
2. Edit `loop-config.json`. Set a new `deadline_utc`, a new `revision` name, the editable files and the focus. The model and reasoning effort are set in `agent_command.py`.
3. Record a fresh baseline for the exact kernel source and corpus you will search from, and write it to `results/frozen-baseline-public.json` and `results/frozen-baseline-heldout.json`. Generate a new private held-out set first. The published one is no longer private.
4. Start the controller:

   ```bash
   mkdir -p lab/agent-home/.codex lab/agent-scratch lab/cache/cargo lab/tmp lab/target lab/logs
   . lab/env.sh
   cargo build --locked --manifest-path lab/probe/Cargo.toml
   cp lab/target/debug/kernel-probe lab/target/baseline-probe
   python3 lab/overnight.py
   ```

   `RESEARCH_STATUS_HOOK`, if set, names a Python script that receives a state and a message when the first change is kept, when the run ends and when it fails.

The controller writes everything to `lab/overnight/`, which git ignores. It refuses to start if `lab/overnight/experiments.jsonl` exists, unless `RESEARCH_RESUME=1` asks it to resume that run. Touch `lab/overnight/pause-between-rounds` to hold it between attempts. When it finishes, `lab/overnight/kept.patch` holds the retained diff relative to `kernel/`. Run `python3 lab/final_audit.py`, then move the run into `research/<date>-<name>/` as the first run was.

## What the sandboxes allow

- The coding agent sees the kernel source read-only, except for the editable files, plus its scratch directory and its own home. It has network access, because the Codex subscription needs it. So this is a filesystem boundary, not a full security boundary. The prompt forbids network research.
- Compilation runs offline with only the kernel source, the probe and the Cargo cache mounted.
- Each probe run gets one stripped recipe, no network, no corpus and no credentials, under `prlimit` limits of 4 GiB address space, 8 CPU seconds and a 16 MiB output file.

## Applying the first run's patch

To study the retained stack, not to ship it:

```bash
git apply --directory=kernel research/2026-10-13-overnight/kept.patch
. lab/env.sh
cargo build --locked --manifest-path lab/probe/Cargo.toml
python3 lab/verify.py suite public --out lab/tmp/public-patched.json
```

Revert with `git checkout -- kernel` when you are done.
