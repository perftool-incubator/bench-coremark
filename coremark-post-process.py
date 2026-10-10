#!/usr/bin/env python3
# -*- mode: python; indent-tabs-mode: nil; python-indent-level: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python

"""Index only a fully validated native performance result."""

import json
import math
import os
import sys
from pathlib import Path

from coremark_common import MAX_ITERATIONS, UPSTREAM_COMMIT, parse_native_output


MANIFEST = Path("coremark-run-manifest.json")
MODES = ("performance", "validation")
MILLISECONDS_PER_SECOND = 1000
NANOSECONDS_PER_MILLISECOND = 1_000_000


def _required_integer(value, label, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError("CoreMark manifest %s is missing or invalid" % label)
    return value


def validate_manifest_outputs(manifest, log_texts):
    """Reparse both raw logs and cross-check result fields and estimated timing."""
    if manifest.get("status") != "valid" or manifest.get("upstream_commit") != UPSTREAM_COMMIT:
        raise ValueError("CoreMark manifest is invalid or has a different upstream source pin")

    requested = manifest.get("requested")
    if not isinstance(requested, dict):
        raise ValueError("CoreMark manifest has no requested parameters")
    threads = requested.get("threads")
    if type(threads) is not int or threads not in (1, 2):
        raise ValueError("CoreMark manifest does not identify a supported prepared thread variant")
    iterations = requested.get("iterations")
    if type(iterations) is not int or not 0 <= iterations <= MAX_ITERATIONS:
        raise ValueError("CoreMark manifest has an invalid requested iteration count")

    modes = manifest.get("modes")
    if not isinstance(modes, dict):
        raise ValueError("CoreMark manifest has no mode records")
    verified = {}
    for mode in MODES:
        record = modes.get(mode)
        if not isinstance(record, dict):
            raise ValueError("CoreMark %s mode record is missing" % mode)
        if record.get("interrupted") is not False:
            raise ValueError("CoreMark %s mode is interrupted or has no interruption status" % mode)
        if record.get("timed_out") is not False or record.get("return_code") != 0:
            raise ValueError("CoreMark %s mode did not complete successfully" % mode)
        if record.get("validation_error"):
            raise ValueError("CoreMark %s mode is not validated" % mode)
        native = record.get("native_result")
        if not isinstance(native, dict):
            raise ValueError("CoreMark %s native result is missing" % mode)
        if mode not in log_texts or not isinstance(log_texts[mode], str):
            raise ValueError("CoreMark %s raw output is missing" % mode)

        parsed = parse_native_output(
            log_texts[mode],
            mode,
            threads,
            return_code=record["return_code"],
            expected_iterations=iterations,
        )
        for key, value in parsed.items():
            if key not in native or native[key] != value:
                raise ValueError("CoreMark %s manifest field %s does not match raw output" % (mode, key))

        launch_ns = _required_integer(record.get("launch_begin_epoch_ns"), mode + " launch timestamp")
        completion_ns = _required_integer(
            record.get("process_completion_epoch_ns"), mode + " completion timestamp"
        )
        if completion_ns <= launch_ns:
            raise ValueError("CoreMark %s process timestamps are not ordered" % mode)
        process_seconds = record.get("launch_to_completion_seconds")
        if (
            isinstance(process_seconds, bool)
            or not isinstance(process_seconds, (int, float))
            or not math.isfinite(process_seconds)
            or process_seconds <= 0
        ):
            raise ValueError("CoreMark %s process elapsed time is missing or invalid" % mode)

        begin = _required_integer(native.get("measurement_begin_epoch_ms_estimate"), mode + " measurement start")
        end = _required_integer(native.get("measurement_end_epoch_ms_estimate"), mode + " measurement end")
        if begin >= end:
            raise ValueError("CoreMark %s estimated measurement endpoints are not ordered" % mode)
        completion_ms = completion_ns // NANOSECONDS_PER_MILLISECOND
        launch_ms = launch_ns // NANOSECONDS_PER_MILLISECOND
        estimated_begin_ms = int(
            completion_ns / NANOSECONDS_PER_MILLISECOND
            - parsed["native_total_time_seconds"] * MILLISECONDS_PER_SECOND
        )
        if abs(end - completion_ms) > 1 or abs(begin - estimated_begin_ms) > 1:
            raise ValueError("CoreMark %s estimated measurement endpoints do not match native timing" % mode)
        if begin < launch_ms - 1 or end > completion_ms + 1:
            raise ValueError("CoreMark %s estimated measurement interval is outside process bounds" % mode)
        native_elapsed_ms = parsed["native_total_time_seconds"] * MILLISECONDS_PER_SECOND
        if abs((end - begin) - native_elapsed_ms) > 1.0:
            raise ValueError("CoreMark %s estimated interval disagrees with native duration by over 1 ms" % mode)

        verified[mode] = {
            "native_result": native,
            "parsed_result": parsed,
            "begin": begin,
            "end": end,
        }
    return verified


def _load_cdm_metrics():
    toolbox_home = os.environ.get("TOOLBOX_HOME")
    if not toolbox_home:
        raise ValueError("CoreMark post-processing requires TOOLBOX_HOME")
    toolbox_python = Path(toolbox_home) / "python"
    if not toolbox_python.is_dir():
        raise ValueError("CoreMark post-processing cannot find %s" % toolbox_python)
    sys.path.append(str(toolbox_python))
    from toolbox.cdm_metrics import CDMMetrics

    return CDMMetrics


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    log_texts = {
        mode: Path("coremark-%s.txt" % mode).read_text(encoding="utf-8", errors="replace")
        for mode in MODES
    }
    verified = validate_manifest_outputs(manifest, log_texts)
    performance = verified["performance"]
    native_result = performance["native_result"]
    begin = performance["begin"]
    end = performance["end"]

    CDMMetrics = _load_cdm_metrics()
    metrics = CDMMetrics()
    metrics.log_sample(
        "0",
        {
            "source": "coremark",
            "class": "throughput",
            "type": "iterations-sec",
            "default-aggregation": "sum",
        },
        {},
        {"begin": begin, "end": end, "value": native_result["iterations_per_second"]},
    )
    metric_file = metrics.finish_samples()
    sample_data = {
        "rickshaw-bench-metric": {"schema": {"version": "2021.04.12"}},
        "benchmark": "coremark",
        "primary-period": "measurement",
        "primary-metric": "iterations-sec",
        "periods": [{"name": "measurement", "metric-files": [metric_file]}],
    }
    output_dir = Path("postprocess")
    output_dir.mkdir(exist_ok=True)
    (output_dir / "post-process-data.json").write_text(
        json.dumps(sample_data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("CoreMark post-processing failed: %s" % exc, file=sys.stderr)
        sys.exit(1)
