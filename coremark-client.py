#!/usr/bin/env python3
# -*- mode: python; indent-tabs-mode: nil; python-indent-level: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python

"""Run CoreMark's standard performance and validation seed modes."""

import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path

from coremark_common import (
    RUNS,
    UPSTREAM_COMMIT,
    parse_cli,
    parse_cpu_list,
    parse_native_output,
)


INSTALL_DIR = Path(os.environ.get("COREMARK_INSTALL_DIR", "/usr/local/libexec/coremark"))
ARTIFACTS = {
    "performance": Path("coremark-performance.txt"),
    "validation": Path("coremark-validation.txt"),
}
ACTIVE_PROCESS = None
SIGNAL_RECEIVED = None


class RunInterrupted(Exception):
    """Raised when Crucible asks this client process to stop."""


def handle_signal(signum, _frame):
    global SIGNAL_RECEIVED
    if SIGNAL_RECEIVED is None:
        SIGNAL_RECEIVED = signum


def raise_if_interrupted():
    if SIGNAL_RECEIVED is not None:
        raise RunInterrupted("CoreMark client interrupted by signal %s" % SIGNAL_RECEIVED)


def atomic_json(path, data):
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_path, path)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_cpu_affinity(thread_count):
    if not hasattr(os, "sched_getaffinity") or not hasattr(os, "sched_setaffinity"):
        raise RuntimeError("CoreMark CPU binding requires Linux sched_getaffinity/sched_setaffinity")
    current = sorted(os.sched_getaffinity(0))
    workload_cpus = os.environ.get("WORKLOAD_CPUS")
    housekeeping_cpus = os.environ.get("HK_CPUS")
    partitioning = os.environ.get("cpu_partitioning", "0") == "1"
    if partitioning and (not workload_cpus or not housekeeping_cpus):
        raise RuntimeError("CPU partitioning requires both WORKLOAD_CPUS and HK_CPUS")
    assigned = parse_cpu_list(workload_cpus) if workload_cpus else current
    housekeeping = parse_cpu_list(housekeeping_cpus) if housekeeping_cpus else []
    requested_workload = [cpu for cpu in assigned if cpu not in set(housekeeping)]
    if not requested_workload:
        raise RuntimeError("WORKLOAD_CPUS has no CPUs after excluding HK_CPUS")

    # Rickshaw pins its engine process to HK_CPUS. Asking the kernel to bind
    # this child to the assigned workload set lets cgroup cpuset restrictions
    # determine which requested workload CPUs are actually usable.
    try:
        os.sched_setaffinity(0, set(requested_workload))
    except OSError as exc:
        raise RuntimeError("could not bind CoreMark to assigned WORKLOAD_CPUS: %s" % exc)
    effective_workload = sorted(os.sched_getaffinity(0))
    invalid_effective = [
        cpu for cpu in effective_workload
        if cpu not in requested_workload or cpu in housekeeping
    ]
    if invalid_effective:
        raise RuntimeError("effective affinity contains CPUs outside WORKLOAD_CPUS: %s" % invalid_effective)
    if len(effective_workload) < thread_count:
        raise RuntimeError(
            "threads=%d requires at least %d effective WORKLOAD_CPUS after cgroup and HK_CPUS filtering; found %s"
            % (thread_count, thread_count, effective_workload)
        )
    selected = effective_workload[:thread_count]
    try:
        os.sched_setaffinity(0, set(selected))
    except OSError as exc:
        raise RuntimeError("could not bind CoreMark to selected workload CPUs: %s" % exc)
    actual_affinity = sorted(os.sched_getaffinity(0))
    if actual_affinity != selected:
        raise RuntimeError(
            "requested CoreMark affinity %s but kernel applied %s" % (selected, actual_affinity)
        )
    return {
        "workload_cpus_env": workload_cpus,
        "housekeeping_cpus_env": housekeeping_cpus,
        "cpu_partitioning": partitioning,
        "engine_affinity_before": current,
        "requested_workload_cpus": requested_workload,
        "effective_workload_cpus_after_cgroup_filter": effective_workload,
        "selected_affinity": selected,
    }


def load_variant(thread_count):
    if platform.machine() != "x86_64":
        raise RuntimeError("this CoreMark integration currently supports x86_64 only")
    binary = INSTALL_DIR / ("coremark-threads-%d" % thread_count)
    provenance_path = INSTALL_DIR / ("coremark-threads-%d.build.json" % thread_count)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError("prepared CoreMark thread variant is missing: %s" % binary)
    if not provenance_path.is_file():
        raise RuntimeError("prepared CoreMark build provenance is missing: %s" % provenance_path)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if provenance.get("upstream_commit") != UPSTREAM_COMMIT:
        raise RuntimeError("installed CoreMark source revision does not match the adapter pin")
    if provenance.get("architecture") != platform.machine():
        raise RuntimeError("installed CoreMark binary architecture does not match the engine")
    if provenance.get("thread_count") != thread_count:
        raise RuntimeError("installed CoreMark variant metadata has the wrong thread count")
    actual_sha = file_sha256(binary)
    if provenance.get("binary_sha256") != actual_sha:
        raise RuntimeError("installed CoreMark binary digest does not match build provenance")
    return binary, provenance


def terminate_process_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_mode(mode, binary, iterations, deadline, expected_threads):
    global ACTIVE_PROCESS
    raise_if_interrupted()
    spec = RUNS[mode]
    output_path = ARTIFACTS[mode]
    command = [
        str(binary),
        *spec["seeds"],
        str(iterations),
        "7",
        "1",
        "2000",
    ]
    start_ns = time.time_ns()
    monotonic_start = time.monotonic()
    timed_out = False
    interrupted = False
    interrupt_error = None
    with output_path.open("wb") as output:
        process = subprocess.Popen(
            command,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        ACTIVE_PROCESS = process
        try:
            deadline_at = time.monotonic() + deadline
            while True:
                if SIGNAL_RECEIVED is not None:
                    interrupted = True
                    interrupt_error = "CoreMark client interrupted by signal %s" % SIGNAL_RECEIVED
                    terminate_process_group(process)
                    return_code = process.returncode
                    break
                remaining = deadline_at - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    terminate_process_group(process)
                    return_code = process.returncode
                    break
                try:
                    return_code = process.wait(timeout=min(remaining, 0.5))
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                terminate_process_group(process)
            ACTIVE_PROCESS = None
    end_ns = time.time_ns()
    monotonic_end = time.monotonic()
    record = {
        "mode": mode,
        "command": command,
        "launch_begin_epoch_ns": start_ns,
        "process_completion_epoch_ns": end_ns,
        "launch_to_completion_seconds": monotonic_end - monotonic_start,
        "process_pid": process.pid,
        "process_group_id": process.pid,
        "return_code": return_code,
        "timed_out": timed_out,
        "interrupted": interrupted,
    }
    if interrupted:
        record["interrupt_error"] = interrupt_error
        return record
    if timed_out:
        record["timeout_seconds"] = deadline
        return record
    text = output_path.read_text(encoding="utf-8", errors="replace")
    try:
        record["native_result"] = parse_native_output(
            text,
            mode,
            expected_threads,
            return_code=return_code,
            expected_iterations=iterations,
        )
        record["native_result"]["measurement_begin_epoch_ms_estimate"] = int(
            end_ns / 1_000_000 - record["native_result"]["native_total_time_seconds"] * 1000
        )
        record["native_result"]["measurement_end_epoch_ms_estimate"] = end_ns // 1_000_000
    except ValueError as exc:
        record["validation_error"] = str(exc)
    return record


def effective_requested_parameters(args):
    """Record runtime values after Multiplex parameters and CLI defaults resolve."""
    return {
        "threads": args.threads,
        "iterations": args.iterations,
        "deadline_seconds_per_mode": args.deadline,
        "standard_total_data_bytes": 2000,
    }


def main(argv):
    global ACTIVE_PROCESS
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    manifest_path = Path("coremark-run-manifest.json")

    manifest = {
        "benchmark": "coremark",
        "upstream_commit": UPSTREAM_COMMIT,
        "status": "invalid",
        "requested": {},
        "timing_note": (
            "CoreMark emits native elapsed seconds but no exact wall-clock measurement endpoints. "
            "The estimated measurement end is the process completion timestamp; output formatting "
            "and CRC checks happen after the native timed region. Adapter launch and process-completion "
            "timestamps are also retained."
        ),
        "modes": {},
    }

    try:
        for artifact in [*ARTIFACTS.values(), manifest_path, Path("coremark-error.txt")]:
            artifact.unlink(missing_ok=True)
        args = parse_cli(argv)
        manifest["requested"] = effective_requested_parameters(args)
        cpu_info = prepare_cpu_affinity(args.threads)
        binary, provenance = load_variant(args.threads)
        manifest["cpu_affinity"] = cpu_info
        manifest["build_provenance"] = provenance
        for mode in ("performance", "validation"):
            result = run_mode(mode, binary, args.iterations, args.deadline, args.threads)
            manifest["modes"][mode] = result
            if result.get("validation_error"):
                raise RuntimeError("CoreMark %s output is invalid: %s" % (mode, result["validation_error"]))
            if result.get("timed_out"):
                raise RuntimeError(
                    "CoreMark %s run exceeded its %d-second deadline; owned process group was terminated"
                    % (mode, args.deadline)
                )
            if result.get("interrupted"):
                raise RuntimeError(result.get("interrupt_error", "CoreMark run interrupted"))
            raise_if_interrupted()
        manifest["status"] = "valid"
        atomic_json(manifest_path, manifest)
        print("CoreMark performance and validation modes passed for the prepared %d-thread variant" % args.threads)
        return 0
    except Exception as exc:
        if ACTIVE_PROCESS is not None and ACTIVE_PROCESS.poll() is None:
            terminate_process_group(ACTIVE_PROCESS)
            ACTIVE_PROCESS = None
        message = str(exc)
        manifest["error"] = message
        try:
            atomic_json(manifest_path, manifest)
            Path("coremark-error.txt").write_text(message + "\n", encoding="utf-8")
        except OSError as write_error:
            print("Could not preserve CoreMark failure details: %s" % write_error, file=sys.stderr)
        print("CoreMark error: %s" % message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
