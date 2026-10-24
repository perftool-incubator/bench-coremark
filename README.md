# CoreMark for Crucible

This project integrates the unmodified EEMBC CoreMark benchmark into Crucible as a client-only workload. The shared `default` Workshop profile has passed x86_64 smoke runs on `alma10`, `alma9`, `fedora43`, `fedora44`, `rhubi10`, `rhubi9`, `stream10`, `stream9`, `alma8`, and `rhubi8`. These results establish compatibility for those userenvs with CPU partitioning disabled; they do not establish support for other architectures or partitioned execution.

## Source and license

The benchmark source is the official [`eembc/coremark`](https://github.com/eembc/coremark) repository at commit [`1f483d5b8316753a742cbf5590caf5bd0a4e4777`](https://github.com/eembc/coremark/tree/1f483d5b8316753a742cbf5590caf5bd0a4e4777). Workshop fetches the archive by its full commit SHA. The source algorithms and native output/reporting rules are not modified. The complete upstream `LICENSE.md`, including the Apache 2.0 text and CoreMark acceptable-use/trademark agreement, is retained at [third-party/EEMBC-CoreMark-LICENSE.md](third-party/EEMBC-CoreMark-LICENSE.md). Use of the CoreMark name and mark follows those terms. The Crucible integration files are Apache-2.0 licensed in [LICENSE](LICENSE).

The upstream `coremark.md5` file has a stale checksum for `coremark.h` at the pinned commit: `make check PORT_DIR=posix` fails on that unchanged file. This was reproduced against the exact official source tree. The Workshop builder verifies SHA-256 values pinned here in `coremark-build.py` for all benchmark source files and headers, the upstream Makefile, and the POSIX port's C/header/make/override inputs before compiling; it records that check and the known upstream MD5 mismatch in build provenance. It does not patch upstream source or claim upstream `make check` passed.

## Build inputs and runtime options

Workshop builds two prepared upstream POSIX/GCC variants, `MULTITHREAD=1` and `MULTITHREAD=2`, with `-O2`, `USE_PTHREAD`, and pthread support. It records compiler version, flags, architecture, pinned source revision, variant, and binary SHA-256. It also checks the exact build inputs before compilation. Runtime does not install packages, download source, or rebuild binaries.

Multiplex exposes only settings supported by this integration. The `defaults` preset selects `threads=1`, `iterations=0`, and `deadline=300` when the input set is empty. Partial explicit sets can omit other options; the client parser fills those with the same runtime defaults, then records all effective values in the run manifest. There is no `essentials` preset because Multiplex essentials override explicit parameter values.

| Option | Meaning |
| --- | --- |
| `threads=1` or `threads=2` | Select a prepared binary. Other values fail. The runner verifies CoreMark reports the requested context count and selects CPUs from inherited affinity. Initial support requires `cpu-partitioning=false`; partitioned support is deferred. |
| `iterations=0` | Pass zero as CoreMark's native iteration argument so its own calibration selects a run of at least ten seconds. |
| `iterations=N` | Pass a fixed native iteration count from 1 through 2,147,483,647, the upstream signed 32-bit argument limit. The adapter verifies that CoreMark's aggregate `Iterations` equals this count times the requested contexts. It is reportable only if the native performance measurement still lasts at least ten seconds and all native validation checks pass. |
| `deadline=30..3600` | Bound each of the sequential performance and validation processes. It is a watchdog only and does not change CoreMark's duration or iteration behavior. |

Each sample runs both upstream seed modes with the 2K profile: standard performance (`0x0, 0x0, 0x66`) and validation (`0x3415, 0x3415, 0x66`). The client preserves each complete native output log. It validates process status, seed and component CRCs for every context, expected context count, success marker, absence of native errors, finite positive rate, and consistency of `Iterations/Sec` with native iterations divided by native seconds. CoreMark may print an error but exit zero, so exit status alone does not establish validity. Both modes must pass, and each must report at least ten native measured seconds; only the performance mode is indexed.

The runtime estimate bounds two sequential runs (`2 * deadline`). Rickshaw applies its normal additional 180-second runtime padding. The client starts each executable in its own process group and terminates that group on timeout, SIGTERM, SIGINT, or an exception. Roadblock receives failures through the toolbox `exit_error` helper. A new sample removes prior sample artifacts before execution, while partial logs and an invalid manifest are kept for diagnosis.

## Measurement and CDM metric

The primary metric is native `Iterations/Sec`, type `iterations-sec`, class `throughput`, in iterations per second. CoreMark's native rate already aggregates the selected contexts in one client, so the adapter does not multiply it by `threads`. The descriptor's `sum` aggregation combines total throughput across simultaneous client engines. Sequential samples remain separate periods; Crucible's result summary reports their mean and sample standard deviation. Validation-mode output is never indexed as performance.

The upstream POSIX timer reports total native seconds and the rate after the timed region, but provides no exact wall-clock endpoints for the measured interval. The adapter stores launch-begin and child-process completion epoch timestamps. CDM's estimated interval end is the process completion time, and its estimated begin is that completion time minus native elapsed seconds. Before indexing, the postprocessor reparses both raw mode logs, checks every parsed native field against the manifest, and verifies each estimated interval against the recorded process bounds and native duration (within one millisecond of timestamp rounding). Those CDM endpoints still carry unquantified post-timer output/CRC delay uncertainty; launch-to-completion duration is retained separately and is not represented as the native measurement duration. The run manifest carries the same explanation and the native measured duration.

## Local checks

The parser tests use authentic output captured from the pinned source and are under `tests/fixtures/`. Provenance and the exact local compiler/build command are recorded in `tests/fixtures/README.md`. Focused non-live checks can be run with:

```bash
python3 -m unittest discover -s tests -v
python3 -m json.tool rickshaw.json >/dev/null
python3 -m json.tool multiplex.json >/dev/null
python3 -m json.tool workshop.json >/dev/null
python3 -m json.tool benchmark-metadata.json >/dev/null
bash -n coremark-client coremark-base
```

These local checks are distinct from the Workshop and Crucible smoke runs recorded in [VALIDATION.md](VALIDATION.md). The 2026-10-23 one-sample matrix passed for all ten x86_64 userenvs above on the same remotehosts endpoint configuration used for the Stream and PHPBench smokes. Each run used one client, disabled tools and CPU partitioning, and exercised `threads=1,2`, `iterations=0`, and `deadline=300`. Both native seed modes passed for each variant, and Crucible indexed the performance metrics. These compatibility runs are not performance qualification. The earlier four-sample Alma 9 result and CDM comparison remain historical; the image builds reused layers where available and do not establish a cold base-image build. Crucible-level abort handling, upstream integration, aarch64, and partitioned execution remain untested. `.github/workflows/crucible-ci.yaml.example` is an inactive publication template, not a workflow GitHub will run. It uses the standard `all` userenv filter as the intended published matrix; do not activate it until CoreMark is registered and an official Rickshaw scenario exists.

## Project files

- `DEPENDENCY-DESIGN.md`: source, dependency, parameter-layer, and measurement worksheet.
- `rickshaw.json`: client scripts, runtime estimator, and post-processing hook.
- `multiplex.json`: supported parameters, defaults, and validation rules.
- `workshop.json`: pinned source and build driver for the initial userenv.
- `coremark-build.py`: immutable-input check, prepared variants, and build provenance.
- `coremark-client.py`, `coremark_common.py`, `coremark-client`, and `coremark-base`: bounded runtime, native output parser, inherited CPU affinity for the initial supported configuration, and toolbox lifecycle integration.
- `coremark-post-process.py`: revalidates logs and emits the performance CDM sample.
- `.github/workflows/crucible-ci.yaml.example`: inactive standard reusable CI template for later publication readiness.
