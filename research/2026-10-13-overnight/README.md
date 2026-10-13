# First overnight run, 12 to 13 October 2026

This directory is the audit record of the first search run against monstertruck `d2ad1ed7`. It is evidence, not code to build on. Nothing here is applied to `kernel/`.

It comes from the run's public handoff archive, `rustcad-autoresearch-prototype.tar.gz`, SHA-256 `3216b144e891f5ac92c8ead0f6a15eedfa55ec10803ec42d13adc67f48aeef46`. Every file here except this README is byte-identical to the archive copy. [`RESULTS.md`](RESULTS.md) is the run's own summary.

## Setup

- Kernel: monstertruck `d2ad1ed7aa420b7f32cd2c1e3ad319b46d593652`.
- Editable: one file, `monstertruck-solid/src/transversal/classic/mod.rs`.
- Agent: `codex exec -m gpt-6-astra` at `xhigh` reasoning effort, on a ChatGPT subscription, with 600 seconds per attempt from revision v2.
- Window: 2026-10-12 18:02 UTC to 2026-10-13 02:45 UTC, 8 hours 42 minutes.
- Corpus: 318 public and 102 held-out synthetic recipes, frozen before the run. All 420 recipes and every evaluator file kept the same hashes across all 69 attempts (`results/frozen-evaluator-audit.json`).

## Result

| | Baseline | Retained stack |
| --- | ---: | ---: |
| Combined score | 48.8987047811 | 75.9191924633 |
| Public passes | 108/318 | 290/318 |
| Held-out passes | 33/102 | 91/102 |
| Fresh audit recipes (351) | 127, score 51.2241809117 | 324, score 77.6353276353 |

69 attempts ran. 12 were kept, 52 rejected for a regression or no gain, one vetoed for new timeouts, three failed to compile, and the deadline cut off the last. The 240 extra passes are 151 box booleans, 72 cylinder booleans and 17 through holes. Revolve (0/17), fillet (0/18) and one STEP import still fail. Attempt 59 already passed every public boolean and hole case, so the last ten attempts had no visible score left to gain.

## Why the stack is not trusted

1. **Kernel test regression.** With the patch, `adjacent_cubes_or` (`monstertruck-solid/src/transversal/integrate/tests.rs:41`) builds 30 faces where the test requires 12. Its volume, centroid and bounding-box assertions still pass. The library suite goes from 9/9 to 8/9. The four `boolean_smoke` tests pass. See `logs/upstream-unit.log` and `logs/upstream-unit-baseline.log`.
2. **Release build fails.** `cargo check --release` exits 101 on two unnecessary qualifications at lines 2614 and 2620 of the patched file. The crate denies warnings in release builds. See `logs/release-check.log`. The record keeps them as measured, unfixed.
3. **Contact passes rest on an oracle bug.** Attempts 58 and 59 turned seven contact unions into passes: boxes touching along an edge (`public-007`, `-046`, `-085`, `-124`) and tangent cylinders (`public-166`, `-178`, `-229`). The frozen mesh check counted differently subdivided edges as separate edges and reported a closed mesh. `contact_audit.py` merges collinear subdivisions first. Then each shared sub-edge has four incident faces in all seven, while the disjoint-box control stays valid. Two bodies touching along an edge can be a fair answer, but the result format cannot say so yet, so those passes do not show a manifold solid. Evidence is in `contact-audit/`. Quarantine attempts 58 and 59 until the oracle and contact contract are fixed.
4. **Size.** The aggregate patch adds 2,652 lines and removes 103 in one file. It uses planar arrangement and rational sweep algorithms, not case IDs or answer tables. Its sampled support tests and floating-point certificates still need expert review.

The evaluator also leaked a little information. Every keep decision used the held-out set, so it is validation data, not an untouched test set. Three STEP round-trip recipes appear in both splits (`results/split-overlap-audit.json`).

## The patches

| Attempt | Combined score | Public / held-out passes | Change |
| --- | ---: | ---: | --- |
| 3 | 53.84675238 | 170 / 47 | Oriented shell winding, complement semantics and bounded curve conversion |
| 4 | 58.06369556 | 208 / 63 | Matching patches and contact sewing |
| 6 | 60.73463573 | 246 / 75 | Planar arrangement fallback |
| 9 | 60.89489214 | 248 / 76 | Planar arrangement before marching |
| 10 | 61.11275707 | 249 / 77 | Control-net separation bounds |
| 20 | 61.27301348 | 252 / 77 | Planar support reconciliation |
| 27 | 63.56059518 | 267 / 83 | Trim-preserving translational sweeps |
| 30 | 63.88739256 | 270 / 83 | Endpoint parameter recovery |
| 43 | 69.76974551 | 278 / 84 | Rational extrusion/plane intersection curves |
| 46 | 74.99850367 | 283 / 87 | Nested boundary and hole reconstruction |
| 58 | 75.26559769 | 287 / 88 | Subdivided trims at edge/point contacts |
| 59 | 75.91919246 | 290 / 91 | Subdivided trims at curved contacts |

Each step is `overnight/attempt-NNN/kept.patch`. Applying the 12 in order to the pinned file reproduces the retained source byte for byte (`logs/patch-replay.log`). The aggregate is [`kept.patch`](kept.patch), SHA-256 `2c26c8673b8c2e51eb5152ed3ebfcfecfe09d592e4981064fa6b0bb48c36d6a7`. Its paths are relative to `kernel/`. [`lab/README.md`](../../lab/README.md) shows how to apply it for study.

Attempt 1 is worth reading although it was rejected. It had the same winding and complement idea as attempt 3 and the same gains, but it turned through-hole case `public-262` from an error into plausible numbers with `is_geometric_consistent=false`. The veto against new wrong successes caught it. Attempt 2 made all 17 hole cases time out, and the operator vetoed it. That led to revision v3, which rejects any new timeout, crash or panic.

## Contents

| Path | What it holds |
| --- | --- |
| `kept.patch` | The aggregate retained diff. |
| `score-over-time.csv` | One row per attempt: times, revision, scores, passes, decision, agent seconds. |
| `overnight/experiments.jsonl` | The full append-only experiment log, one JSON record per attempt. |
| `overnight/design-changes.jsonl` | Each controller revision (v1, v2, v3) and its configuration. |
| `overnight/hourly-checks.jsonl`, `independent-health-checks.jsonl` | Liveness checks from the controller and the separate watcher. |
| `overnight/best-*.json`, `public-history.json`, `controller-state.json` | Final retained verdicts, the feedback history the agent saw, and the controller's last state. |
| `overnight/attempt-NNN/` | Prompt, agent summary, candidate diff, build log and suite logs for every attempt that reached those stages. Kept attempts and attempts 1 and 2 also have their full verdict files. |
| `final-audit/` | Clean rebuild, repeated suites, identity checks and the 351-recipe fresh audit with its seed and hashes. |
| `contact-audit/` | Raw geometry and results for the seven contact cases and one control. |
| `results/` | Oracle controls, baseline determinism, overlap audit, upstream test results, token usage and the run review. |
| `logs/` | Kernel test logs, release check and patch replay. |

The public tree leaves out three things from the archive. These are the raw agent transcripts (`agent.jsonl`, 16.5 MB), the per-attempt frozen-file manifests (7.9 MB of hashes, summarised in `results/frozen-evaluator-audit.json`), and the verdict JSON files of rejected attempts other than 1 and 2. Their suite logs and the experiment log still record each decision.

Paths inside the logs were redacted to `/workspace` before the archive was made. The two frozen baselines this run started from are in `lab/results/`.
