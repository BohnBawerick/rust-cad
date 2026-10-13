# Round 2 research record, 13 October 2026

gpt-6-astra at high moved the problem. The retained stack passes every public and held-out case, the required kernel gates, and the fresh sealed comparison without regressions or new incorrect successes.

Combined passes rose from 161/420 to 420/420. The score rose from 59.7364373100 to 100.0000000000. Kept patches remain evidence; none is applied to `kernel/` in this commit.

## Run and validation

The controller ran from 07:19:12 to 11:03:43 UTC, 3 hours 44 minutes 30 seconds. The attempt window lasted 3 hours 37 minutes 48 seconds. It was launched with a 5.5-hour budget and a 2026-10-13T12:49:12.421290+00:00 deadline, but stopped early with `no_visible_headroom`, the brief's permitted completion condition. This was not five hours of actual loop time.

The starting kernel was unpatched monstertruck `d2ad1ed7`, on the round 2 redesign. The editor was Codex `gpt-6-astra` at `high`, with 900 seconds and 40 tool calls per attempt. Lanes ran in the configured order: planar, revolve, fillet, curved, step. Budgets, lane order, evaluator `oracle-v2`, corpus, oracle controls and keep gates did not change during the run.

The preflight reproduced public 122/318 and held-out 39/102 exactly, with no regressions or new passes; both oracle and controller test scripts passed. The initial workspace gate proof passed in 320.701 seconds for kernel tests and 30.581 seconds for the release check. Each of the 11 keeps passed its affected-crate tests, a warning-free release check and identical repeated verdicts. The clean rebuild repeated both suites and patch replay matched the retained source byte for byte.

Two startup shells killed their background process groups before any attempt completed. Firstmate supplied a transient user-service launch, which survived later tool calls. The independent watcher also crashed because `experiments.jsonl` did not yet exist. The only harness fix treats that missing file as zero attempts; it was reproduced and checked before this run. It changes observation, not candidate judgments. The run used a copied ChatGPT subscription login, with API credentials absent and the private agent home excluded from this record.

Frozen-file manifests from all 20 attempts agree on 785 protected lab, probe, corpus and fixture hashes, which also match the files after the run. The hash summary is in `results/frozen-evaluator-audit.json`. No rate limits or agent failures occurred.

## Passes and score

| Split | Baseline passes | Final passes | Baseline score | Final score |
| --- | ---: | ---: | ---: | ---: |
| public | 122/318 | 318/318 | 58.7425372457 | 100.0000000000 |
| heldout | 39/102 | 102/102 | 60.6481481481 | 100.0000000000 |
| combined | 161/420 | 420/420 | 59.7364373100 | 100.0000000000 |

The score averages each geometry group's pass fraction with equal weight. Held-out cases participate in keep decisions, so they are validation data. The fresh sealed sample was generated after the search.

| Group | Public baseline / final | Held-out baseline / final | Combined baseline / final |
| --- | ---: | ---: | ---: |
| boxes | 40 / 157 of 157 | 17 / 51 of 51 | 57 / 208 of 208 |
| cylinders | 28 / 78 of 78 | 3 / 24 of 24 | 31 / 102 of 102 |
| extrude | 13 / 13 of 13 | 4 / 4 of 4 | 17 / 17 of 17 |
| revolve | 12 / 13 of 13 | 4 / 4 of 4 | 16 / 17 of 17 |
| fillet | 0 / 14 of 14 | 0 / 4 of 4 | 0 / 18 of 18 |
| chamfer | 13 / 13 of 13 | 4 / 4 of 4 | 17 / 17 of 17 |
| holes | 0 / 13 of 13 | 0 / 4 of 4 | 0 / 17 of 17 |
| patterns | 13 / 13 of 13 | 4 / 4 of 4 | 17 / 17 of 17 |
| step | 3 / 4 of 4 | 3 / 3 of 3 | 6 / 7 of 7 |

| Lane | Attempts | Keeps | Public baseline / final | Combined baseline / final |
| --- | ---: | ---: | ---: | ---: |
| planar | 4 | 2 | 40 / 157 of 157 | 57 / 208 of 208 |
| revolve | 1 | 1 | 12 / 13 of 13 | 16 / 17 of 17 |
| fillet | 2 | 1 | 0 / 14 of 14 | 0 / 18 of 18 |
| curved | 12 | 6 | 28 / 91 of 91 | 31 / 119 of 119 |
| step | 1 | 1 | 3 / 4 of 4 | 6 / 7 of 7 |

## Attempts and rejected ideas

| Reason | Attempts |
| --- | ---: |
| `regression` | 5 |
| `improved_without_regression` | 11 |
| `kernel_tests_failed` | 1 |
| `no_gain` | 2 |
| `build_failed` | 1 |

Attempt 3 gained on both splits but failed `transversal::integrate::tests::adjacent_cubes_or` in `monstertruck-solid`: 30 faces where the kernel requires 12. Its planar arrangement left subdivision fragments as separate faces. Attempt 4 added source-face coalescing and then passed that test and every other keep gate. This is the only kernel-gate-failed candidate; no candidate failed the release check. See `overnight/attempt-003/kernel_tests.log`.

Attempt 1 introduced a wrong success on `public-262`. Attempt 6 regressed 12 public and four held-out cases and introduced runtime failures. Attempt 8 introduced a timeout on `public-250`. Attempts 10 and 11 regressed `heldout-053`. Attempts 12 and 13 gained nothing. Attempt 14 failed to compile; attempt 15 repaired its type error. Each rejected patch, summary and available suite verdict remains in its attempt directory.

## Kept changes

File abbreviations below are relative to `kernel/`. `classic/` expands to `monstertruck-solid/src/transversal/classic/`; `solid/` to `monstertruck-solid/src/transversal/`; `geometry/` to `monstertruck-geometry/src/decorators/`; `meshing/boundary/` to `monstertruck-meshing/src/tessellation/triangulation/boundary/`; `modeling/` to `monstertruck-modeling/src/`; `io/` to `monstertruck-io/src/`.

| Attempt | Lane | Combined passes | Combined score | Files | Fix |
| ---: | --- | ---: | ---: | --- | --- |
| 2 | planar | 235/420 | 64.5221336398 | `classic/{mod.rs,faces_classification.rs,shell_classification.rs}` | Classify uncut shells with oriented winding and preserve complement, cavity and empty-solid semantics. |
| 4 | planar | 327/420 | 69.4366635543 | `classic/mod.rs, classic/planar.rs, classic/planar/{assemble.rs,coalesce.rs}` | Build planar arrangements and merge fragments from the same face, preserving separate shells at edge and vertex contacts. This repairs attempt 3's face-count failure. |
| 5 | revolve | 328/420 | 70.0902583256 | `geometry/revolved_curve.rs, meshing/boundary/projection.rs` | Avoid Newton seeds at the radial cusp and keep axis-pole positions when duplicating UV coordinates. |
| 7 | fillet | 346/420 | 81.2013694367 | `modeling/fillet_impl/mod.rs` | Keep exact rational isoparametric sections for fillet end trims instead of straight chords, checked against both carrier surfaces. |
| 9 | curved | 354/420 | 86.4301276066 | `classic/{mod.rs,exact_section.rs}` | Recover exact rational plane-intersection sections for through-hole rims and reuse validated UV trims. |
| 15 | curved | 362/420 | 91.6588857765 | `classic/divide_face.rs, classic/divide_face/interior.rs` | Keep paired interior trim loops even when their UV area is small, preserving disk and annulus partitions. |
| 16 | curved | 386/420 | 94.2732648615 | `classic/{mod.rs,coincident.rs}, solid/integrate/mod.rs` | Certify equal oriented boundaries before applying coincident-solid union, intersection and difference identities. |
| 17 | curved | 410/420 | 96.8876439465 | `classic/mod.rs, classic/circular_extrusion/{mod.rs,recognize.rs}` | Certify circular extrusions, split existing arcs at analytic crossings and assemble shared cap and side edges. |
| 18 | curved | 418/420 | 97.7591036415 | `classic/circular_extrusion/mod.rs` | Treat externally tangent cylinders as disjoint interiors: two shells for union, empty intersection and unchanged difference. |
| 19 | curved | 419/420 | 98.4126984127 | `classic/{mod.rs,shell_classification.rs}` | Respect face orientation and complemented solids when classifying residual faces; remove the exterior cap that prevented one hole from closing. |
| 20 | step | 420/420 | 100.0000000000 | `io/step/load/convert/{mod.rs,assembly_shapes.rs}` | Follow non-transforming representation relationships to recover assembly solids, with cycle guards and ID deduplication. |

The aggregate is `kept.patch`, SHA-256 `e0e5f9479e91197f8ac9accb94cbb75393f70af23999647b50dbb410665e9db3`. The 11 individual kept patches replay in attempt order. Full relative file names are also in `results/run-review.json` and each experiment record.

## Fresh sealed and contact audits

| Fresh sealed sample | Baseline | Retained stack |
| --- | ---: | ---: |
| Passes | 136/351 | 351/351 |
| Score | 61.1022079772 | 100.0000000000 |

Previously passing sealed cases that regressed: 0. New incorrect successes: 0. The seed, recipe hashes and binary hashes are in `final-audit/seal-manifest.json`; recipes and both result sets are included.

The contact audit passes 8/8 cases under the shell-by-shell oracle. It records each shell count and the merged-mesh closure alongside raw geometry in `contact-audit/`. Edge-touching boxes and tangent cylinders may have a non-manifold merged mesh while each returned shell is closed; separate bodies are checked explicitly.

The first contact diagnostic timed out after eight seconds on `public-229`, after saving six raw results. An unchanged retry passed all eight cases. The first failure log is retained as `logs/contact-audit-first.log`. Tangent cases ran close to the wall-clock limit in the suite, so their performance needs review before promotion.

These recipes cover the tested geometry families. The cylinder path certifies a limited circular-extrusion form; arbitrary curved solids, unequal-height cylinders and other fillet profiles still need review and broader tests. Each root cause needs its own reviewed kernel change before any patch is promoted.

## Evidence

`overnight/` holds configurations, prompts, minimized failures, candidate and kept patches, verdicts, build and gate logs, and controller, watcher and worker health checks. `final-audit/` holds the clean rebuild, repeated suites, identity checks and fresh sealed comparison. `results/` holds replay review, combined metrics, timing and the protected-file hash summary. `logs/` holds preflight, launch, watcher-failure and audit logs.

Raw agent transcripts, executable binaries, duplicated best-source files, stale process handles and per-attempt frozen manifests are omitted. Absolute worktree and sandbox paths are redacted to `/workspace`. The private agent home, credentials and caches are not included.
