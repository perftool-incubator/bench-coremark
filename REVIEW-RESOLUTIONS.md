# Independent review resolutions

This log records fixes made after independent implementation review and the local Crucible development smoke.

## Local controller smoke follow-up: Multiplex essentials expanded both threads

The installed Multiplex README and source confirm that `essentials` override explicit non-repeatable values, while `defaults` only apply to empty parameter sets. The `threads=[1,2]` essential therefore produced both prepared variants for an explicit `threads=1` or `threads=2` request. The `essentials` block is now removed; the `defaults` block retains the empty-set values `threads=1`, `iterations=0`, and `deadline=300`. Explicit values remain selectable. Partial parameter sets may omit options from Multiplex output; the existing client parser supplies its defaults and records all effective values in the run manifest.

Regression evidence executes the actual installed Multiplex CLI for empty/default input, explicit selection of either thread variant, explicit `threads=2`, `iterations=12345`, `deadline=60`, and a partial set omitting threads while keeping explicit iteration/deadline. The output has one selected variant and preserves explicit runtime values. The empty set defaults to one thread; for partial sets, the client selects one thread when omitted and records effective defaults in manifest parameters.

## Local controller smoke follow-up: postprocessor executable mode

Rickshaw directly executes the configured `controller.post-script` command. The source file mode for `coremark-post-process.py` is now executable. A regression resolves each direct Rickshaw hook (`client.start`, `client.runtime`, and `controller.post-script`) from `rickshaw.json` and requires an executable file with a shebang. It also launches the configured postprocessor directly from a realistic sample directory through its shebang with `TOOLBOX_HOME` and `RS_CS_LABEL` set. Direct invocation against both captured valid local result directories also succeeded.

## P2: bound fixed iteration counts and verify aggregate counts

CoreMark's native iteration argument is a signed 32-bit value. The runtime CLI and the real Multiplex `iterations` validation now both accept `0..2147483647` and reject negative, out-of-range, and oversized inputs. For positive fixed counts, the adapter and postprocessor require native aggregate `Iterations == requested_iterations * contexts`; auto-calibrated `0` retains native calibration semantics.

Regression evidence:

- Runtime tests cover zero, the maximum, maximum plus one, and a much larger integer.
- A test reads and applies the regex from `multiplex.json`, checking zero, one, the maximum, and out-of-range values.
- Parser tests check aggregate counts for both prepared variants and reject mismatched counts.
- Postprocessor tests reject a requested/native mismatch and a manifest/native mismatch.

## P2: validate raw output, process bounds, and estimated measurement timing

The postprocessor now reparses both raw logs and compares every parsed native result field against the corresponding manifest result. It requires both modes to be complete and uninterrupted, validates positive ordered launch/completion timestamps, reconstructs the estimated measured interval from process completion and parsed native duration, and checks its bounds and duration agreement within one millisecond of timestamp rounding. The estimate remains explicitly uncertain because upstream emits output and performs CRC reporting after the timed region.

Regression evidence covers changed native duration, changed endpoints, process-bound violations, nonpositive/unordered timestamps, requested/native and manifest/native count mismatches, interrupted records, and missing timestamps or raw output. The postprocessor was rerun on both captured client fixture runs and emitted valid CDM data from the performance result only.

## P2: lock all POSIX compilation inputs

The source SHA-256 map now contains 11 inputs, including:

- `posix/core_portme.mak`: `25a50c96fe353523a331f3589fcda1702d6b622c94428df7766dee3e068940fb`
- `posix/core_portme_posix_overrides.h`: `1dc67b5c1b9c773cccc740b911d708333d3bf154c3313f77b8a52e18209eda59`

Both digests were independently recomputed from the clean official source checkout at commit `1f483d5b8316753a742cbf5590caf5bd0a4e4777`. Separate temporary copies with each input modified failed at the expected lock before compiler probing, `make`, or install-directory creation. Unit regressions retain the reviewed digests and verify the pre-build rejection path.

## Final local checks

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`: 33 passed, including four cases using actual installed Multiplex and direct-hook executable-mode/invocation coverage.
- Python syntax compilation for build/client/shared parser/runtime/postprocessor and tests: passed.
- Shell syntax for lifecycle entrypoints: passed.
- Rickshaw, Multiplex, Workshop, metadata, and example run-file Draft-7 schema validation: passed.
- Inactive CI example YAML parsed successfully; the intended `userenv_filter: all` remains visible.
- Actual postprocessor/CDM runs on both captured valid sample directories: passed.
- Final revised Workshop build driver compiled both prepared variants from a fresh temporary copy of the pinned source after all 11 locks passed.

## Throughput aggregation correction

CoreMark's native rate already aggregates every context in one client. The postprocessor now emits that rate unchanged with `default-aggregation=sum`, which combines throughput across simultaneous client engines. The Crucible result summary separately computes the mean and sample standard deviation across repeated sample periods. Tests run the configured postprocessor for both prepared variants, inspect the emitted metric descriptor, and assert one metric data row equals the parsed native rate without multiplying by context count.

The earlier four-period API check predates the aggregation correction. After restoring stock CDM, the corrected descriptor was used to reprocess all four retained samples; the default API queries matched native scores and estimated endpoints without overrides. CoreMark's throughput descriptor does not depend on a CDM change. See [VALIDATION.md](VALIDATION.md) for the distinction between the historical API check and current stock-CDM evidence.

The local checks are supplemented by the 2026-10-10 Workshop requirements-stage build and corrected-tree four-sample Crucible development run documented in [VALIDATION.md](VALIDATION.md). The corrected-tree run reused the built image; the stage build used a cached base layer. Cold base-image validation, Crucible-level abort handling, upstream integration, and broader userenv/architecture coverage remain open. Initial support uses `cpu-partitioning=false`.
