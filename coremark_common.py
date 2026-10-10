#!/usr/bin/env python3
# -*- mode: python; indent-tabs-mode: nil; python-indent-level: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python

"""Shared parameter and native-output validation for the CoreMark adapter."""

import argparse
import math
import re


UPSTREAM_COMMIT = "1f483d5b8316753a742cbf5590caf5bd0a4e4777"
SUPPORTED_THREADS = (1, 2)
DEFAULT_ITERATIONS = 0
MAX_ITERATIONS = 2147483647
DEFAULT_DEADLINE = 300
MIN_DEADLINE = 30
MAX_DEADLINE = 3600
STANDARD_DATA_BYTES = 2000

RUNS = {
    "performance": {
        "seeds": ("0x0", "0x0", "0x66"),
        "seed_crc": 0xE9F5,
        "header": "2K performance run parameters for coremark.",
        "component_crc": {"crclist": 0xE714, "crcmatrix": 0x1FD7, "crcstate": 0x8E3A},
    },
    "validation": {
        "seeds": ("0x3415", "0x3415", "0x66"),
        "seed_crc": 0x18F2,
        "header": "2K validation run parameters for coremark.",
        "component_crc": {"crclist": 0xE3C1, "crcmatrix": 0x0747, "crcstate": 0x8D84},
    },
}


def parse_cli(argv):
    parser = argparse.ArgumentParser(description="CoreMark runtime controls")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--deadline", type=int, default=DEFAULT_DEADLINE)
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        raise ValueError("unsupported CoreMark option(s): " + " ".join(unknown))
    if args.threads not in SUPPORTED_THREADS:
        raise ValueError(
            "threads must select an installed variant: "
            + ", ".join(str(value) for value in SUPPORTED_THREADS)
        )
    if not 0 <= args.iterations <= MAX_ITERATIONS:
        raise ValueError(
            "iterations must be between 0 (upstream auto calibration) and %d" % MAX_ITERATIONS
        )
    if not MIN_DEADLINE <= args.deadline <= MAX_DEADLINE:
        raise ValueError(
            "deadline must be between %d and %d seconds per run mode"
            % (MIN_DEADLINE, MAX_DEADLINE)
        )
    return args


def parse_cpu_list(value):
    """Parse Linux cpulist notation such as `1,3-5` without expanding invalid ranges."""
    if not value or not value.strip():
        raise ValueError("WORKLOAD_CPUS is empty")
    cpus = []
    seen = set()
    for token in value.split(","):
        token = token.strip()
        if not token:
            raise ValueError("WORKLOAD_CPUS contains an empty CPU entry")
        if re.fullmatch(r"[0-9]+", token):
            first = last = int(token)
        else:
            match = re.fullmatch(r"([0-9]+)-([0-9]+)", token)
            if not match:
                raise ValueError("invalid CPU list entry in WORKLOAD_CPUS: " + token)
            first, last = map(int, match.groups())
            if last < first:
                raise ValueError("descending CPU range in WORKLOAD_CPUS: " + token)
        for cpu in range(first, last + 1):
            if cpu not in seen:
                seen.add(cpu)
                cpus.append(cpu)
    return cpus


def parse_native_output(text, mode, expected_threads, return_code=0, expected_iterations=0):
    """Validate one unmodified CoreMark output log and return its native result."""
    if mode not in RUNS:
        raise ValueError("unknown CoreMark mode: " + str(mode))
    if return_code != 0:
        raise ValueError("CoreMark %s exited with status %d" % (mode, return_code))
    if not text.strip():
        raise ValueError("CoreMark %s output is empty" % mode)

    spec = RUNS[mode]
    if text.count(spec["header"]) != 1:
        raise ValueError("CoreMark %s output does not identify the expected 2K seed mode" % mode)
    if text.count("Correct operation validated.") != 1:
        raise ValueError("CoreMark %s did not report one successful validation" % mode)
    if re.search(r"(?:ERROR!|Errors detected|Cannot validate operation)", text, re.IGNORECASE):
        raise ValueError("CoreMark %s output contains a native error marker" % mode)

    def one(pattern, label, flags=0):
        matches = re.findall(pattern, text, flags)
        if len(matches) != 1:
            raise ValueError("CoreMark %s output must contain exactly one %s" % (mode, label))
        return matches[0]

    seed_crc = int(one(r"^seedcrc\s*:\s*(0x[0-9a-fA-F]+)\s*$", "seedcrc", re.MULTILINE), 16)
    if seed_crc != spec["seed_crc"]:
        raise ValueError("CoreMark %s seedcrc 0x%04x does not match the pinned 2K run rules" % (mode, seed_crc))

    duration = float(one(r"^Total time \(secs\):\s*([0-9]+(?:\.[0-9]+)?)\s*$", "native elapsed time", re.MULTILINE))
    rate = float(one(r"^Iterations/Sec\s*:\s*([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\s*$", "iterations/sec", re.MULTILINE))
    iterations = int(one(r"^Iterations\s*:\s*([0-9]+)\s*$", "iteration count", re.MULTILINE))
    size = int(one(r"^CoreMark Size\s*:\s*([0-9]+)\s*$", "CoreMark size", re.MULTILINE))
    if not math.isfinite(duration) or duration < 10.0:
        raise ValueError("CoreMark %s native measured duration is below the 10-second reporting minimum" % mode)
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("CoreMark %s iterations/sec is not finite and positive" % mode)
    if iterations <= 0 or size <= 0:
        raise ValueError("CoreMark %s reported a nonpositive iteration count or size" % mode)
    if expected_iterations and iterations != expected_iterations * expected_threads:
        raise ValueError(
            "CoreMark %s reported %d aggregate iterations; requested %d across %d contexts"
            % (mode, iterations, expected_iterations, expected_threads)
        )
    expected_rate = iterations / duration
    if not math.isclose(rate, expected_rate, rel_tol=0.005, abs_tol=0.01):
        raise ValueError("CoreMark %s native rate does not match iterations divided by native time" % mode)

    if not one(r"^Compiler version\s*:\s*(.+?)\s*$", "compiler version", re.MULTILINE).strip():
        raise ValueError("CoreMark %s compiler version is empty" % mode)
    if not one(r"^Compiler flags\s*:\s*(.+?)\s*$", "compiler flags", re.MULTILINE).strip():
        raise ValueError("CoreMark %s compiler flags are empty" % mode)
    if not one(r"^Memory location\s*:\s*(.+?)\s*$", "memory location", re.MULTILINE).strip():
        raise ValueError("CoreMark %s memory location is empty" % mode)

    parallel_counts = re.findall(r"^Parallel\s+[^:\n]+\s*:\s*([0-9]+)\s*$", text, re.MULTILINE | re.IGNORECASE)
    if expected_threads == 1:
        if parallel_counts:
            raise ValueError("single-context CoreMark output unexpectedly reports parallel contexts")
    elif parallel_counts != [str(expected_threads)]:
        raise ValueError("CoreMark output did not report the requested parallel context count")

    crc_values = {}
    for context, kind, crc_text in re.findall(
        r"^\[([0-9]+)\]\s*(crclist|crcmatrix|crcstate|crcfinal)\s*:\s*(0x[0-9a-fA-F]+)\s*$",
        text,
        re.MULTILINE,
    ):
        key = (int(context), kind)
        if key in crc_values:
            raise ValueError("CoreMark %s output repeats CRC %s for context %s" % (mode, kind, context))
        crc_values[key] = int(crc_text, 16)

    expected_crc_keys = {
        (context, kind)
        for context in range(expected_threads)
        for kind in ("crclist", "crcmatrix", "crcstate", "crcfinal")
    }
    if set(crc_values) != expected_crc_keys:
        missing = sorted(expected_crc_keys - set(crc_values))
        extra = sorted(set(crc_values) - expected_crc_keys)
        raise ValueError("CoreMark %s CRC coverage mismatch (missing=%s extra=%s)" % (mode, missing, extra))

    for context in range(expected_threads):
        for kind, expected in spec["component_crc"].items():
            actual = crc_values[(context, kind)]
            if actual != expected:
                raise ValueError(
                    "CoreMark %s context %d %s CRC 0x%04x did not match 0x%04x"
                    % (mode, context, kind, actual, expected)
                )

    result = {
        "mode": mode,
        "seed_crc": "0x%04x" % seed_crc,
        "native_total_time_seconds": duration,
        "iterations": iterations,
        "iterations_per_second": rate,
        "reported_size_per_algorithm": size,
        "requested_total_data_bytes": STANDARD_DATA_BYTES,
        "context_count": expected_threads,
        "context_crcs": {
            str(context): {
                kind: "0x%04x" % crc_values[(context, kind)]
                for kind in ("crclist", "crcmatrix", "crcstate", "crcfinal")
            }
            for context in range(expected_threads)
        },
        "compiler_version": one(r"^Compiler version\s*:\s*(.+?)\s*$", "compiler version", re.MULTILINE).strip(),
        "compiler_flags": one(r"^Compiler flags\s*:\s*(.+?)\s*$", "compiler flags", re.MULTILINE).strip(),
        "memory_location": one(r"^Memory location\s*:\s*(.+?)\s*$", "memory location", re.MULTILINE).strip(),
        "native_validation": "Correct operation validated.",
    }
    if mode == "performance":
        summary_rate = float(
            one(r"^CoreMark 1\.0\s*:\s*([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\s*/", "CoreMark 1.0 score", re.MULTILINE)
        )
        if not math.isclose(summary_rate, rate, rel_tol=0.005, abs_tol=0.01):
            raise ValueError("CoreMark performance summary score does not match Iterations/Sec")
    return result
