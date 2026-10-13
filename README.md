# rust-cad

A pure-Rust CAD geometry engine. The long-term aim is a solid modeller that can replace SolidWorks for everyday part design, with no C++ kernel underneath.

The kernel starts as a fork of [monstertruck](https://github.com/virtualritz/monstertruck) (Apache-2.0). Around it sits a verification loop. A command-line probe builds geometry with the kernel, an independent Python checker compares the result against closed-form answers, and a controller lets a coding agent propose kernel changes. It keeps only the changes that raise the score without breaking any case that already passed. The idea comes from Karpathy's [autoresearch](https://github.com/karpathy/autoresearch), adapted for geometry, where a better average can never excuse a newly wrong solid.

This is early research. Nothing here is ready for production use, and the kernel in this repository is upstream monstertruck with no changes yet.

## Layout

| Path | What it holds |
| --- | --- |
| `kernel/` | monstertruck at commit `d2ad1ed7aa420b7f32cd2c1e3ad319b46d593652`, unpatched, with its `LICENSE`. |
| `lab/probe/` | `kernel-probe`, the Rust CLI. It reads one JSON recipe, runs the operation and prints mesh coordinates plus B-rep topology. It prints observations, not verdicts. |
| `lab/verify.py`, `lab/oracle.py` | The frozen evaluator. It runs the probe in a sandbox and judges its output. |
| `lab/check_identities.py`, `lab/contact_audit.py` | Diagnostics. Boolean volume identities, and an edge-incidence check that ignores how an edge was subdivided. |
| `lab/generate.py`, `lab/corpus/` | The recipe generator and the 420 recipes it produced, plus 351 fresh audit recipes in `corpus/sealed/`. |
| `lab/fixtures/` | One public NIST STEP file. Source and hash are in `lab/fixture-manifest.json`. |
| `lab/overnight.py` and friends | The search loop controller. See [`lab/README.md`](lab/README.md). |
| `lab/results/frozen-baseline-*.json` | The recorded baseline verdicts that CI compares against. |
| `research/2026-10-13-overnight/` | The record of the first overnight run, including its patch stack. Not applied. See [its README](research/2026-10-13-overnight/README.md). |

## Requirements

Linux, Rust 1.98.1 (stable), Python 3, [Bubblewrap](https://github.com/containers/bubblewrap) (`bwrap`) and `prlimit` from util-linux. The evaluator runs every probe call inside `bwrap --unshare-all`, so unprivileged user namespaces must be allowed. On Ubuntu 24.04 that means `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`.

The kernel carries a `rust-toolchain.toml` that asks for nightly. The baseline was recorded on stable 1.98.1, and every command below runs from the repository root, where rustup does not see that file.

## Reproduce the baseline

```bash
mkdir -p lab/cache/cargo lab/tmp lab/target
. lab/env.sh
cargo build --locked --manifest-path lab/probe/Cargo.toml
python3 lab/verify.py case lab/corpus/public/public-315.json
python3 lab/verify.py suite public --out lab/tmp/public.json
python3 lab/verify.py suite heldout --out lab/tmp/heldout.json
python3 lab/compare_baseline.py public lab/tmp/public.json
python3 lab/compare_baseline.py heldout lab/tmp/heldout.json
```

`lab/env.sh` keeps Cargo's home, the build output and temporary files inside `lab/`. The `case` command prints one JSON verdict and exits 1 when the case fails. `public-315` fails on purpose. It is the disjoint-box subtraction that comes back empty instead of a unit cube.

A suite command exits 0 whenever evaluation finishes, however many cases fail. `compare_baseline.py` is the gate. It exits 1 if a case that passed in the recorded baseline now fails, if a failing case starts returning geometry it did not return before, if a new timeout or crash appears, or if the score drops.

You should get exactly the recorded numbers:

| Split | Passed | Score |
| --- | ---: | ---: |
| public (visible to the search agent) | 108/318 | 48.2012267044 |
| held-out | 33/102 | 48.8562091503 |
| combined | 141/420 | 48.8987047811 |

The score is `100 * mean(passed / total)` over nine operation groups (box booleans, cylinder booleans, extrude, revolve, fillet, chamfer, holes, patterns, STEP). It is not the raw pass percentage. A full run takes about a minute on a desktop machine.

## Run the kernel's own tests

```bash
cp lab/upstream-tests/Cargo.lock kernel/Cargo.lock
git clone https://github.com/ricosjp/resources4truck.git kernel/resources
git -C kernel/resources checkout 9bf9de1426c5fc2f2b8d63f501dca0d3c53ebd91
cargo test --locked --manifest-path kernel/Cargo.toml --workspace \
  --exclude monstertruck-gpu --exclude monstertruck-render \
  --exclude monstertruck-wasm --exclude example-pages-generator \
  -- --test-threads=1
```

The lock file is the one the overnight run used. Upstream ignores `Cargo.lock`, so the copy does not dirty the tree. `kernel/resources` is upstream's test-data submodule, which this repository does not vendor. Some `monstertruck-io` tests read from it.

Use one test thread. `monstertruck-traits` keeps a process-wide work meter, and with parallel threads `the_work_meter_charges_what_the_division_spends` fails at random. On the pinned commit this run passes 1,140 tests with 26 ignored.

## What the verifier checks

A recipe is a small JSON file. This one subtracts two disjoint unit cubes:

```json
{"id":"demo","group":"boxes","op":"difference","a":{"kind":"box","origin":[0,0,0],"size":[1,1,1]},"b":{"kind":"box","origin":[2,0,0],"size":[1,1,1]},"boolean_tol":0.05,"mesh_tol":0.002}
```

`verify.py` strips the recipe down to the operation inputs and runs the probe with no network, no corpus and limits of 8 seconds, 8 CPU seconds and 4 GiB. `oracle.py` computes the expected volume, area and centroid from closed-form formulas. Box booleans use an independent cell decomposition. Cylinder booleans use the equal-radius lens formula. Extrusion, revolution, one-edge fillet and chamfer, through holes and translated patterns use direct integrals. It then integrates the probe's mesh itself and checks that every welded edge has two uses with opposite winding. It also checks that each B-rep edge has two opposite uses and that each shell's Euler characteristic is even and at most two. An empty result passes only where empty is the right answer.

These are coarse research checks. Equal mass properties do not prove a shape is right, and the cylinder, revolve, hole, fillet and chamfer groups allow 1% error. `research/2026-10-13-overnight/README.md` lists what the oracle misses.

## How the loop works

`lab/overnight.py` runs bounded attempts until a deadline. Each attempt:

1. Gives the coding agent one editable kernel file, a few visible failing recipes and recent feedback. The agent cannot read the corpus, the evaluator or the held-out cases.
2. Compiles the candidate offline in a separate sandbox.
3. Runs both suites and keeps the change only if the public and combined scores both rise, no previously passing case fails, no new incorrect success or runtime failure appears, and a repeat run gives identical verdicts.
4. Otherwise restores the file. Every attempt's diff, prompt, build log and verdicts are written to an append-only record.

The controller also hashes every protected file before and after each attempt and stops if one changed. [`lab/README.md`](lab/README.md) covers configuration, authentication and the audit scripts.

## The first overnight run

On 12 and 13 October 2026 the loop ran 69 attempts over 8 hours 42 minutes and kept 12. The combined score rose from 48.8987047811 to 75.9191924633, and passing cases from 141/420 to 381/420. No kept change broke a case that passed before. A clean rebuild repeated every verdict, and 351 fresh recipes generated after the run closed went from 127 to 324 passes (score 51.2241809117 to 77.6353276353) with no regressions.

That stack is not in the kernel, and you should not apply it as a trusted fix. The audit after the run found three problems:

- It breaks one of the kernel's own tests. `adjacent_cubes_or` in `monstertruck-solid` now builds 30 faces where the test requires 12. The library suite passes 8/9 with the patch and 9/9 without.
- It fails the release build. Two unnecessary qualifications at lines 2614 and 2620 of the patched file become errors because the crate denies warnings in release builds.
- Seven of its contact passes rest on an oracle bug. They are unions of boxes touching along an edge and of tangent cylinders (`public-007`, `-046`, `-085`, `-124`, `-166`, `-178`, `-229`). The frozen checker counted subdivided edges separately and reported a closed mesh. Once collinear subdivisions are merged, each shared sub-edge has four incident faces, so the result is not a manifold solid. The result format cannot yet say "two bodies touching", so those passes prove nothing.

The patch is also large: 2,652 lines added and 103 removed in one file. The run record keeps it as `research/2026-10-13-overnight/kept.patch` (SHA-256 `2c26c8673b8c2e51eb5152ed3ebfcfecfe09d592e4981064fa6b0bb48c36d6a7`), with each of the 12 steps beside it.

## Next steps

These come from the run's report and are not done yet:

- Fix the oracle so edge subdivision cannot change a verdict, and define what a result of separate touching bodies looks like.
- Make the kernel's own tests and the release build hard gates in the loop, not only in CI.
- Review the kept patches one root cause at a time, starting with the winding and complement fix, and land each one only after the review passes.
- Add a recipe schema with units and explicit contact semantics, and separate error kinds for unsupported input, non-convergence, invalid topology, geometric inconsistency, precision failure and conversion loss.
- Generate a new private validation set. The held-out recipes here are now public, so they are ordinary regression tests.
- Then resume the search, with focused modules instead of one ever-growing file.

## Licence

Apache-2.0, matching monstertruck. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE) for third-party attributions.
