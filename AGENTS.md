# Bench-CoreMark

## Purpose

Client-only Crucible integration for unmodified EEMBC CoreMark, validated on x86_64 across the ten userenvs listed in `README.md` using the shared Workshop `default` profile. CPU partitioning remains disabled; other architectures and partitioned runs are outside the validated scope.

## Source and contracts

- Upstream source pin: `eembc/coremark` commit `1f483d5b8316753a742cbf5590caf5bd0a4e4777`.
- Keep upstream benchmark algorithms and native output/reporting behavior unmodified.
- Read `DEPENDENCY-DESIGN.md` before changing the build/runtime contract.
- Keep Workshop build inputs separate from Multiplex runtime options. Only prepared 1- and 2-context variants are supported.
- With CPU partitioning, exclude `HK_CPUS`, request `WORKLOAD_CPUS`, and verify the kernel-effective affinity after cgroup filtering. The engine may inherit an HK-only mask; do not intersect an explicit workload set with that mask. Without partitioning, use inherited affinity.
- Only publish a performance metric after both standard seed modes pass native CRC/error checks and each native measurement is at least ten seconds.
- Preserve raw native logs, process timing, measurement-time uncertainty, and build provenance.
- Every runtime process has a bounded deadline and must be cleaned up on timeout, abort signal, or exceptions.
- Do not claim userenv or architecture support without a build and native-run record for that exact target.

## Validation

Run `python3 -m unittest discover -s tests -v` and non-live syntax/schema checks described in `README.md`. Do not imply those local checks replace a Workshop image build or Crucible engine run.

## CI gate

The `.github/workflows/crucible-ci.yaml` workflow runs unit tests before the
registered `coremark` benchmark CI on non-fork code changes and manual
dispatches; docs-only pull requests use faux CI. Keep the callable unit test
command in `.github/workflows/unittest.yaml` aligned with
`python3 -m unittest discover -s tests -v`. The workflow uses the standard
`all` userenv filter for CoreMark's recorded x86_64 compatibility coverage.
The stable completion check is `crucible-ci-complete`; the ruleset backup
records it as required, and the live default-branch ruleset should require it
after its first successful pull request run.
