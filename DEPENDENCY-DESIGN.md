# CoreMark dependency and measurement design

This worksheet records the initial CoreMark build/runtime boundary before implementation. It follows the repository and framework sources inspected on 2026-10-09. Later Workshop and Crucible evidence, including the 2026-10-23 x86_64 userenv matrix, is recorded in [VALIDATION.md](VALIDATION.md).

## Tested scope and environment

- **Topology:** one client engine; no server role.
- **Tested target set:** x86_64 on `alma10`, `alma9`, `fedora43`, `fedora44`, `rhubi10`, `rhubi9`, `stream10`, `stream9`, `alma8`, and `rhubi8`, with `cpu-partitioning=false`. The 2026-10-23 smoke matrix in [VALIDATION.md](VALIDATION.md) records a successful build and native run for each userenv. No aarch64 or partitioned execution is claimed.
- **Workload revision:** official `eembc/coremark` commit `1f483d5b8316753a742cbf5590caf5bd0a4e4777`; Workshop acquires the archive by full commit SHA. Source is built unmodified and verified against 11 commit-specific SHA-256 locks covering benchmark source/headers, Makefile, and POSIX port C/header/make/override inputs. At this exact revision, upstream `make check` rejects the unchanged `coremark.h` because the bundled MD5 is stale; see README.
- **Port/compiler:** upstream POSIX port, GCC, `-O2`, POSIX threads. The build must record the actual compiler version, flags, architecture, source revision, thread variant, and installed executable digest.
- **Prepared variants:** one and two POSIX contexts, compiled separately through Workshop using upstream `MULTITHREAD`/`USE_PTHREAD` settings. Runtime thread selection only selects one of these installed binaries. There is no runtime compile step and no arbitrary thread-count build.

## Dependency ownership and Workshop plan

The tested userenvs supply the compiler, `make`, Python 3, and archive tools. The benchmark adds only the pinned EEMBC source and builds two executables. A Workshop `files` requirement supplies a small build driver; a pinned `source` requirement unpacks the immutable GitHub archive, verifies the pinned source hashes, then builds and installs the variants and per-variant provenance under `/usr/local/libexec/coremark/`. EL8 runs use Python 3.6, so the driver formats displayed commands with `shlex.quote` rather than the newer `shlex.join`.

The shared `workshop.json` selects `default`, validated against the ten userenvs above. Do not infer compatibility for other profiles or architectures. No runtime package installation, source checkout, download, or compilation is allowed.

## Runtime controls versus build inputs

| Setting | Layer | Meaning |
|---|---|---|
| CoreMark commit, POSIX port, compiler, `-O2`, `MULTITHREAD=1/2`, `USE_PTHREAD`, build recipe | Workshop | Determines installed software and source/build provenance. |
| `threads=1` or `threads=2` | Multiplex/client runtime | Chooses an already installed thread-count variant; rejects any unprepared value. Initial supported runs use `cpu-partitioning=false` and the inherited process affinity. |
| `iterations=0` or 1 through 2,147,483,647 | Multiplex/client runtime | Passes CoreMark's native signed 32-bit fourth CLI argument. `0` requests CoreMark's built-in iteration calibration; positive values request that exact count per prepared context. The adapter verifies the native aggregate count equals the request times the context count. A fixed count is accepted only if the native result validates and its performance interval is at least ten seconds. |
| `deadline` | Multiplex/client runtime | Per-mode watchdog only; it does not alter CoreMark's iteration or measurement behavior. The runner executes performance and validation modes sequentially, each with its own bounded deadline, and kills only the owned process group on timeout. |
| CPU binding | Client runtime | Initial supported runs use `cpu-partitioning=false`, so the client uses inherited process affinity. Conditional partitioning code exists but partitioned execution is not part of initial support. |
| samples/repetition and endpoint/userenv/image | Rickshaw/run file | Controls orchestration and provisioned environment, not CoreMark compilation. |

Multiplex `defaults` set the empty-set behavior to one thread, automatic iterations, and a 300-second per-mode deadline. No `essentials` are used because they overwrite explicit runtime values. If a partial set omits an option, the client parser supplies that option's default, and the run manifest records the effective parsed parameters.

CoreMark's own Makefile supports the native iteration argument (`0` means automatic calibration), and `MULTITHREAD` is a compile-time setting. The upstream `run` flow executes separate performance and validation seed modes. The adapter will preserve both raw outputs and require both native CRC-validation successes; only the performance mode emits the CDM score. The native executable reports an error below ten measured seconds. The adapter independently enforces that duration and never indexes calibration-only, invalid, incomplete, or sub-ten-second output.

## Measurement and result contract

- Primary metric: native `Iterations/Sec` from the performance mode, in iterations/second; CoreMark already aggregates the selected contexts in this value, so the client must not multiply by thread count. CDM class is `throughput`; default aggregation is `sum` across simultaneous client engines. Repeated sample periods remain separate, and Crucible's result summary computes their mean and sample standard deviation. Do not index the validation mode as a score.
- Capture the unmodified performance and validation stdout/stderr, adapter launch-begin and child-process completion epoch timestamps, selected build-provenance record, parameters, and native `Total time (secs)` for each mode.
- CoreMark prints the duration and rate after its timed region, but does not expose exact wall-clock start/end timestamps for that region. The post-processor derives the CDM interval as process completion time minus native duration, reparses both raw logs, and verifies all native fields and timing bounds before indexing. This is an estimated interval: report formatting and CRC checks occur after timing. Retain the process timestamps and state this uncertainty in README/results. Do not describe the entire process interval as the measurement interval.
- Accept a reportable performance score only when process exit is zero, the expected performance seed CRC is present, CoreMark prints `Correct operation validated.`, no native error marker appears, all expected CRC fields exist for every requested context, actual native duration is at least ten seconds, and native `Iterations/Sec` is finite and positive. Apply the same success/CRC requirements to the separate validation-seed run, without indexing a score from it.
- Any timeout, nonzero exit, unsupported variant, incomplete output, invalid CRC, missing metric, or invalid/sub-ten-second duration is a sample failure, surfaced through toolbox's Roadblock error message contract. Preserve partial raw logs for diagnosis and emit no valid score for that sample.

## Build evidence and remaining environment boundaries

The 2026-10-10 record documents the initial x86_64/`alma9` build and four-sample development run. On 2026-10-23, the shared `default` profile passed one-sample Crucible smoke runs on all ten x86_64 userenvs listed above, including both prepared variants, native seed validation, and normal result indexing. See [VALIDATION.md](VALIDATION.md) for run IDs and measurements. These results establish compatibility smoke coverage, not performance qualification; the Alma 9 build reused cached base layers, so a cold base-image build is not established. Crucible abort cleanup, upstream integration, aarch64, and CPU-partitioned execution remain outside the validated scope.

## Source/code references inspected

- `benchmark-expansion-plan/PLAN.md` CoreMark scope and shared benchmark contracts.
- `benchmark-expansion-plan/EXISTING-BENCHMARK-PATTERNS.md` lifecycle, parameter routing, CDM aggregation, fixture, and CI patterns.
- `benchmark-expansion-plan/SOFTWARE-DEPENDENCIES.md` Workshop/userenv behavior and provisioning acceptance.
- `benchmark-expansion-plan/TEST-PROCEDURE.md` local-to-development validation gate and acceptance cases.
- `benchmark-expansion-plan/sources/crucible/AGENTS.md`, `docs/implementing-a-new-benchmark.md`, `docs/developer-guide.md`, `docs/how-benchmark-execution-works.md`, `docs/how-engines-work.md`, `docs/how-run-files-work.md`, and `docs/how-ci-works.md`.
- Framework source snapshots: Crucible `be1257d6aa109ecd75be116a51dfcedbf21d56df`, Rickshaw `a01579b12f72678d69074a13189cecb3aa83eefb`, Multiplex `7c1c73bd04be35730a6e6d8775f30e7342d3d729`, Workshop `7fbd13c0ca330b7e2c1cc47849e8204d44cad78c`, toolbox `2bc9eb35bad27825fa327934ccf959a650e5540d`.
- Benchmark references: `bench-sleep`, `bench-cyclictest`, `bench-perftest`, `bench-fio`, and `bench-iperf` in the source snapshot; CoreMark upstream was cloned from `https://github.com/eembc/coremark` and checked out at the full SHA above.
