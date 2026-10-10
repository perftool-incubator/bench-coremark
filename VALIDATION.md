# Local validation record

Recorded 2026-10-10 from the local development environment. This record combines local source, adapter, and schema checks with an `alma9`/x86_64 Workshop build-stage check and a four-sample Crucible development run. It does not establish support beyond that target or complete the broader readiness matrix.

## Pinned upstream source/build

- Official repository: `https://github.com/eembc/coremark`
- Commit: `1f483d5b8316753a742cbf5590caf5bd0a4e4777`
- `git status --short` on the upstream clone was clean before making a temporary working copy.
- The integration build driver checked SHA-256 for all 11 pinned source/build inputs in `coremark-build.py` before compiling.
- Build command, run from an unmodified temporary copy of that pinned checkout: `COREMARK_INSTALL_DIR=<temporary-install-dir> python3 "$BENCHMARK_DIR/coremark-build.py"`, with `BENCHMARK_DIR` set to the CoreMark integration checkout.
- Result: passed for x86_64 using GCC 15.2.1; separately prepared 1- and 2-context binaries were installed under the selected temporary install directory. Compiler and binary digests are in `tests/fixtures/README.md` and in the build manifests.
- After the review fixes, the revised build driver was rerun from a fresh temporary copy of the same pinned checkout. All 11 locks passed before compilation, and both prepared variants rebuilt successfully with the same compiler and binary SHA-256 values shown in the fixture provenance.
- On 2026-10-10, Workshop successfully built the CoreMark requirements stage from the pinned source for the exact `alma9` x86_64 target. The later corrected-tree four-sample run reused that built image. Workshop reused an existing cached base layer, so this is not evidence of a cold base-image build.

The upstream `make check PORT_DIR=posix` command was also run against that exact pinned tree and failed only for `coremark.h`:

```text
core_list_join.c: OK
core_main.c: OK
core_matrix.c: OK
core_state.c: OK
core_util.c: OK
coremark.h: FAILED
md5sum: WARNING: 1 computed checksum did NOT match
```

The expected MD5 from upstream `coremark.md5` is `8ca974c013b380dc7f0d6d1afb76eb2d`; the unchanged checked-out `coremark.h` computes to `b0ec69b6c8e75853d06accb3b1bcf534` and byte-compares equal to the file at the pinned commit. The builder therefore does not claim `make check` passed. It verifies 11 commit-specific SHA-256 locks for benchmark algorithms/headers, the Makefile, and the POSIX port C/header/make/override inputs without modifying upstream files.

## Native fixture captures

The final client adapter was run locally against the two prepared binaries with `iterations=0` and per-mode deadline 120 seconds. Both modes passed native output validation for both variants; all four raw outputs are included in `tests/fixtures/`. Native durations were 15.627/15.655 seconds (performance/validation) for one context and 15.839/15.974 seconds for two contexts. The parser checked seed CRC, component CRCs for all contexts, final CRC presence, success markers, context count, rate arithmetic, and the ten-second minimum.

## Adapter and schema checks

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`: passed, 33 focused checks using the four genuine raw-output fixtures, derived test-only fixed-count logs and timestamp metadata, negative parser/runtime/postprocessor cases, two pre-build source-mutation cases, a mocked disjoint-HK/workload affinity regression, four actual Multiplex CLI cases, and direct-hook executable-mode/invocation coverage.
- Installed Multiplex CLI regression: empty input expands to the one-thread, `0` iteration, `300` second defaults; explicit `threads=1` and `threads=2` each produce only the requested variant; explicit `threads=2`, `iterations=12345`, `deadline=60` preserves all values; omitting threads from a partial set defaults to one in effective client parameters. Partial sets may omit fallback args from the Multiplex expansion; client parser defaults are present in the effective run manifest.
- Runtime estimate hook check: `python3 coremark-get-runtime --threads 2 --iterations 0 --deadline 300` returned `600` seconds for its two sequential per-mode deadlines; Rickshaw adds its inspected 180-second padding.
- `bash -n coremark-client coremark-base`: passed.
- Rickshaw's configured `client.start`, `client.runtime`, and `controller.post-script` paths all resolve to files with an executable bit and shebang. A test directly executes the configured postprocessor path through its shebang in a realistic sample directory with `TOOLBOX_HOME` and `RS_CS_LABEL`; the postprocessor was also run directly on both retained valid local fixture runs.
- Python `py_compile` for build, client, shared parser, runtime, postprocessor, and unit tests: passed. `PYTHONPYCACHEPREFIX` pointed to a temporary cache directory outside the repository.
- `python3 -m json.tool` syntax checks for Rickshaw, Multiplex, Workshop, metadata, and example files: passed.
- Draft-7 JSON Schema validation with installed `jsonschema` passed for `rickshaw.json` against Rickshaw `schema/benchmark.json`, `multiplex.json` against Multiplex `JSON/req-schema.json`, `workshop.json` against Workshop `schema.json`, `benchmark-metadata.json` against Crucible `schema/benchmark-metadata.json`, and the example run file against Rickshaw `schema/run-file.json`.
- The inactive `.github/workflows/crucible-ci.yaml.example` parsed with installed PyYAML and retained `userenv_filter: all`. Its `.example` suffix means GitHub Actions will not execute it.
- The postprocessor was run against the two captured valid client manifests/log sets with `TOOLBOX_HOME` pointing at the toolbox source checkout. It emitted one `coremark:throughput:iterations-sec` metric per sample from the performance log only; validation output did not create another metric. Sample rates were 19197.542715 and 37881.179367 iterations/sec, and each CDM interval was 15627 ms/15839 ms from native duration, while the native-versus-process-end estimate uncertainty remains documented. The descriptor now uses `sum`; the direct-hook regression verifies both prepared variants emit their native aggregate rate once, without multiplying by thread count.
- Review regression follow-up: `--iterations` and the actual Multiplex validation regex accept `0..2147483647` and reject negatives, `2147483648`, and oversized decimal input. Positive fixed counts are checked against CoreMark's aggregate `Iterations` in each client mode and again when postprocessing. The postprocessor rejects manifest/raw-output mismatches, invalid or interrupted process records, missing fields, and estimates outside process bounds or inconsistent with native duration by more than one millisecond.
- The two newly locked POSIX compilation inputs were independently hashed from the clean checkout at the pinned commit and matched their recorded SHA-256 values. In two temporary source copies, appending a mutation to either input caused the build driver to fail with that exact digest mismatch before compiler probing, `make`, or install-directory creation.
- Local SIGTERM abort exercise: started a long fixed-iteration run and sent SIGTERM to the adapter. It returned failure, wrote an invalid manifest and error text including an interrupted performance mode, terminated/reaped its owned CoreMark process group, and left no running child. This is local adapter evidence, not a live Crucible abort test.

The adapter contains conditional CPU-partitioning affinity handling based on the inspected Rickshaw engine bootstrap: the engine is pinned to housekeeping CPUs before launching the client. The focused mocked test covers the disjoint inherited-mask case. This conditional code is not part of initial support; current support uses `cpu-partitioning=false` and inherited affinity. A Crucible-level abort test remains pending.

## Workshop and Crucible development smoke (2026-10-10)

The corrected staged benchmark tree completed a four-sample Crucible development run using the prepared one- and two-thread variants, reusing the image from the earlier Workshop stage build described above. The native means were 41549.8688535 iterations/sec for one thread and 81358.972949 iterations/sec for two threads; the reported means and standard deviations were independently recalculated from the samples.

The first four-period API comparison was performed before the aggregation correction, while the CoreMark descriptor used `avg` and the development service included a period-scope patch. That historical comparison does not establish the current aggregation contract. After restoring the clean stock CDM baseline, the corrected postprocessor reprocessed the retained four valid samples; post-processing and indexing succeeded. Four default API queries with no aggregation override matched the native values within `1e-8` absolute tolerance and matched the estimated endpoints exactly. This reused the existing raw measurements and manifests; no new workload run was performed. The standard result-summary command then passed with all four native scores, the same means and standard deviations, `partial=false`, and no dropped engines. The bounded direct-hook test also verifies one unscaled native score per sample for both prepared variants. Crucible's result summary averages the independent native sample scores; `sum` applies to simultaneous engine throughput within a sample.

A focused stock-CDM aggregation fixture confirmed both scopes: simultaneous metric series with values 10 and 30 aggregate to 40, while separate sample periods with values 11 and 22 return 11 and 22 for their respective period queries.

The development run confirms this staged CoreMark path on the tested `alma9` x86_64 setup with CPU partitioning disabled. The reused cached base means a cold base-image build was not exercised. Crucible-level abort handling, upstream integration, and other userenv or architecture combinations remain pending. CPU partitioning is deferred and outside initial support. The CI workflow file remains an inactive example until official benchmark registration, an official Rickshaw scenario, and the intended supported matrix are ready.
