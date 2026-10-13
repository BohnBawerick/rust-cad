Evidence paths below are relative to `lab/`; `score-over-time.csv` is at the archive root.

The loop made measurable progress, but the full retained patch is not ready to ship. Across 69 Astra xhigh attempts over 8 hours 42 minutes, 12 changes raised the frozen score from 48.8987047811 to 75.9191924633. Passing cases rose from 141/420 to 381/420. A clean rebuild repeated those results, and a fresh sample also improved. The final audit found one new upstream test failure and a mesh-oracle weakness affecting seven checked contact unions. Those findings qualify the score; they are not hidden by it.

| Kept attempt | Completed UTC | Combined score | Visible / private passes | Change |
| --- | --- | ---: | ---: | --- |
| 3 | 2026-10-12 18:40 | 53.84675238 | 170 / 47 | Oriented shell winding, complement semantics and bounded curve conversion |
| 4 | 2026-10-12 18:49 | 58.06369556 | 208 / 63 | Matching patches and contact sewing |
| 6 | 2026-10-12 19:09 | 60.73463573 | 246 / 75 | Planar arrangement fallback |
| 9 | 2026-10-12 19:32 | 60.89489214 | 248 / 76 | Planar arrangement before marching |
| 10 | 2026-10-12 19:40 | 61.11275707 | 249 / 77 | Control-net separation bounds |
| 20 | 2026-10-12 20:57 | 61.27301348 | 252 / 77 | Planar support reconciliation |
| 27 | 2026-10-12 21:47 | 63.56059518 | 267 / 83 | Trim-preserving translational sweeps |
| 30 | 2026-10-12 22:09 | 63.88739256 | 270 / 83 | Endpoint parameter recovery |
| 43 | 2026-10-12 23:32 | 69.76974551 | 278 / 84 | Rational extrusion/plane intersection curves |
| 46 | 2026-10-12 23:55 | 74.99850367 | 283 / 87 | Nested boundary and hole reconstruction |
| 58 | 2026-10-13 01:14 | 75.26559769 | 287 / 88 | Subdivided trims at edge/point contacts |
| 59 | 2026-10-13 01:23 | 75.91919246 | 290 / 91 | Subdivided trims at curved contacts |

Of 69 attempts, 12 were kept, 52 were rejected for regression or no gain, one received the explicit timeout veto, three failed compilation, and the final attempt was cut off by the overall deadline. Rejected proposals included one with a private regression and 15 with newly incorrect successes; these counts overlap. No kept change broke a previously passing case in the fixed visible or private sets.

All 69 records are in `overnight/experiments.jsonl` and the handoff `score-over-time.csv`. Each kept diff is `overnight/attempt-NNN/kept.patch`, with its hash and full repeated verdicts beside it. Applying the 12 kept patches in order to the pinned original file reproduces the retained source byte for byte. The aggregate patch is `overnight/kept.patch`, SHA-256 `2c26c8673b8c2e51eb5152ed3ebfcfecfe09d592e4981064fa6b0bb48c36d6a7`. It adds 2,652 lines and removes 103 in one boolean implementation file. This is a substantial experimental rewrite, not a small verified bug fix.

| Group | Baseline passed / total | Final visible | Final private | Still failing |
| --- | ---: | ---: | ---: | --- |
| boxes | 56/208 | 157/157 | 50/51 | 1 private mesh-closure failure |
| cylinders | 28/102 | 78/78 | 22/24 | 2 private invalid-output-shell errors |
| extrude | 17/17 | 13/13 | 4/4 | none in this family |
| revolve | 0/17 | 0/13 | 0/4 | 17 failures, chiefly mesh closure |
| fillet | 0/18 | 0/14 | 0/4 | 18 geometrically inconsistent results |
| chamfer | 17/17 | 13/13 | 4/4 | none in this family |
| holes | 0/17 | 13/13 | 4/4 | none in this family |
| patterns | 17/17 | 13/13 | 4/4 | none in this family |
| step | 6/7 | 3/4 | 3/3 | 1 empty import success |

The 240 extra frozen-corpus passes comprise 151 box booleans, 72 cylinder booleans and 17 holes. Revolution, fillet and STEP failures remain. All editable visible boolean/hole cases pass by attempt 59. The final 10 attempts therefore had no visible-score headroom in the permitted file, yet the keep rule required a visible gain. The controller should have stopped or started a new, explicitly versioned operation lane. This wasted roughly the final 82 minutes.

The final audit compiled into a new empty target directory, then ran both original suites twice. Every verdict and failure reason repeated and matched the retained records. It generated 351 fresh cases after the agent window closed, including new STEP dimensions and 36 additional disjoint scale cases. Baseline passed 127/351, score 51.2241809117; retained source passed 324/351, score 77.6353276353. No previously passing fresh case failed and no new incorrect success appeared under the frozen evaluator. These cases use the same analytic families and the same oracle, so they do not independently validate that oracle. Seed, hashes, per-case results and build logs are in `final-audit/`. Final boolean volume identities pass 78/78 visible triples and 24/25 private triples; one private triple still has an operation error.

The post-search contact audit normalized collinear edge subdivisions before counting incidence. All seven checked contact successes from attempts 58 and 59 then had four incident faces on each shared geometric sub-edge. The unchanged disjoint-box control stayed valid. The frozen checker had counted differently subdivided edges separately and reported closure. `contact-audit/results.json`, its raw geometry and `contact_audit.py` reproduce this. These shapes can be meaningful as separate bodies touching along a boundary, but the current result schema and oracle do not distinguish that from a claimed manifold solid. The seven passes cannot be credited as proof of manifold hardening. Quarantine those two contact patches until the result contract and subdivision-invariant checks are settled. Do not infer malicious intent; the experiment rewards the checker it is given.

The four pinned upstream `boolean_smoke` tests pass. The library suite passes 8/9 after the patch, versus 9/9 on the pinned baseline under the same generated dependency lock. `adjacent_cubes_or` now produces 30 faces instead of the required 12 at `monstertruck-solid/src/transversal/integrate/tests.rs:41`; its preceding volume, centroid and bounding-box assertions pass. This is a new representation/test regression outside the frozen corpus. Logs are `logs/upstream-unit.log` and `logs/upstream-unit-baseline.log`. The baseline comparison restored the retained source afterward. The first offline smoke-test attempt lacked a cached workspace dependency; an online dependency resolution completed, then the smoke tests and offline library comparison ran.

Release checking exited 101. The retained file adds two unnecessary qualifications at lines 2614 and 2620. The crate denies warnings without debug assertions, so they are release-build errors. Evidence: `logs/release-check.log`. The research snapshot preserves them instead of silently changing the measured candidate after the final audit. A shipping follow-up must remove them and repeat validation.

The final stack is therefore an experimental result requiring revision, despite its higher score. Native tests, release builds and stronger topology checks must become hard keep gates. The sealed audit was not fed back into further kernel edits. The existing 420 recipes, trusted probe, generator and oracle hashes are identical across all 69 attempts; `results/frozen-evaluator-audit.json` records that check. Protecting the evaluator from edits did not protect it from its own blind spots.

The research code and retained patches need review before production use. Start with the independent checks and root-cause fixes; preserve the original measurements.
