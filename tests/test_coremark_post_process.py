import importlib.util
import re
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

POST_SPEC = importlib.util.spec_from_file_location(
    "coremark_post_process", REPO_ROOT / "coremark-post-process.py"
)
POST = importlib.util.module_from_spec(POST_SPEC)
POST_SPEC.loader.exec_module(POST)

from coremark_common import UPSTREAM_COMMIT, parse_native_output


FIXTURES = REPO_ROOT / "tests" / "fixtures"


def valid_manifest_and_logs(threads=1):
    """Use genuine raw output with explicitly synthetic timestamp metadata."""
    completion_ns = 1_800_000_000_000_000_000
    logs = {}
    modes = {}
    for index, mode in enumerate(("performance", "validation")):
        text = (FIXTURES / ("coremark-%d-threads-%s.txt" % (threads, mode))).read_text(
            encoding="utf-8"
        )
        logs[mode] = text
        parsed = parse_native_output(text, mode, threads)
        mode_completion = completion_ns + index * 1_000_000_000
        parsed["measurement_end_epoch_ms_estimate"] = mode_completion // 1_000_000
        parsed["measurement_begin_epoch_ms_estimate"] = int(
            mode_completion / 1_000_000 - parsed["native_total_time_seconds"] * 1000
        )
        modes[mode] = {
            "return_code": 0,
            "timed_out": False,
            "interrupted": False,
            "launch_begin_epoch_ns": mode_completion - 60_000_000_000,
            "process_completion_epoch_ns": mode_completion,
            "launch_to_completion_seconds": 60.0,
            "native_result": parsed,
        }
    manifest = {
        "status": "valid",
        "upstream_commit": UPSTREAM_COMMIT,
        "requested": {"threads": threads, "iterations": 0},
        "modes": modes,
    }
    return manifest, logs


class PostProcessIntegrityTests(unittest.TestCase):
    def test_genuine_logs_and_consistent_estimated_intervals_validate(self):
        manifest, logs = valid_manifest_and_logs()
        checked = POST.validate_manifest_outputs(manifest, logs)
        self.assertEqual(set(checked), {"performance", "validation"})
        self.assertEqual(
            checked["performance"]["native_result"]["iterations_per_second"],
            checked["performance"]["parsed_result"]["iterations_per_second"],
        )

    def test_fixed_positive_count_matches_aggregate_in_both_postprocessed_modes(self):
        for threads in (1, 2):
            with self.subTest(threads=threads):
                manifest, logs = valid_manifest_and_logs(threads)
                for mode in ("performance", "validation"):
                    duration = manifest["modes"][mode]["native_result"]["native_total_time_seconds"]
                    aggregate = threads
                    rate = aggregate / duration
                    text = re.sub(
                        r"^Iterations\s*:\s*[0-9]+$",
                        "Iterations       : %d" % aggregate,
                        logs[mode],
                        flags=re.M,
                    )
                    text = re.sub(
                        r"^Iterations/Sec\s*:\s*[0-9.]+$",
                        "Iterations/Sec   : %.6f" % rate,
                        text,
                        flags=re.M,
                    )
                    text = re.sub(
                        r"^(CoreMark 1\.0\s*:\s*)[0-9.]+",
                        r"\g<1>%.6f" % rate,
                        text,
                        flags=re.M,
                    )
                    logs[mode] = text
                    old_native = manifest["modes"][mode]["native_result"]
                    parsed = parse_native_output(
                        text, mode, threads, expected_iterations=1
                    )
                    parsed["measurement_begin_epoch_ms_estimate"] = old_native[
                        "measurement_begin_epoch_ms_estimate"
                    ]
                    parsed["measurement_end_epoch_ms_estimate"] = old_native[
                        "measurement_end_epoch_ms_estimate"
                    ]
                    manifest["modes"][mode]["native_result"] = parsed
                manifest["requested"]["iterations"] = 1
                checked = POST.validate_manifest_outputs(manifest, logs)
                self.assertEqual(checked["performance"]["parsed_result"]["iterations"], threads)

    def test_rejects_manifest_duration_changed_without_raw_output_change(self):
        manifest, logs = valid_manifest_and_logs()
        manifest["modes"]["performance"]["native_result"]["native_total_time_seconds"] += 999
        with self.assertRaisesRegex(ValueError, "does not match raw output"):
            POST.validate_manifest_outputs(manifest, logs)

    def test_rejects_manifest_endpoints_changed_without_raw_output_change(self):
        manifest, logs = valid_manifest_and_logs()
        native = manifest["modes"]["performance"]["native_result"]
        native["measurement_begin_epoch_ms_estimate"] = 1
        native["measurement_end_epoch_ms_estimate"] = 2
        with self.assertRaisesRegex(ValueError, "estimated measurement endpoints"):
            POST.validate_manifest_outputs(manifest, logs)

    def test_rejects_measurement_estimate_outside_process_bounds(self):
        manifest, logs = valid_manifest_and_logs()
        mode = manifest["modes"]["performance"]
        mode["launch_begin_epoch_ns"] = mode["process_completion_epoch_ns"] - 5_000_000_000
        with self.assertRaisesRegex(ValueError, "outside process bounds"):
            POST.validate_manifest_outputs(manifest, logs)

    def test_rejects_nonpositive_or_unordered_process_timestamps(self):
        manifest, logs = valid_manifest_and_logs()
        manifest["modes"]["performance"]["process_completion_epoch_ns"] = 0
        with self.assertRaisesRegex(ValueError, "completion timestamp"):
            POST.validate_manifest_outputs(manifest, logs)

    def test_rejects_requested_count_that_disagrees_with_native_aggregate(self):
        manifest, logs = valid_manifest_and_logs()
        manifest["requested"]["iterations"] = 1
        with self.assertRaisesRegex(ValueError, "aggregate iterations"):
            POST.validate_manifest_outputs(manifest, logs)

    def test_rejects_manifest_aggregate_count_that_disagrees_with_raw_output(self):
        manifest, logs = valid_manifest_and_logs()
        manifest["modes"]["performance"]["native_result"]["iterations"] += 1
        with self.assertRaisesRegex(ValueError, "field iterations"):
            POST.validate_manifest_outputs(manifest, logs)

    def test_rejects_interrupted_mode_even_when_manifest_says_valid(self):
        manifest, logs = valid_manifest_and_logs()
        manifest["modes"]["validation"]["interrupted"] = True
        with self.assertRaisesRegex(ValueError, "interrupted"):
            POST.validate_manifest_outputs(manifest, logs)

    def test_rejects_missing_timing_or_raw_output_fields(self):
        manifest, logs = valid_manifest_and_logs()
        del manifest["modes"]["performance"]["process_completion_epoch_ns"]
        with self.assertRaisesRegex(ValueError, "completion timestamp"):
            POST.validate_manifest_outputs(manifest, logs)

        manifest, logs = valid_manifest_and_logs()
        del logs["validation"]
        with self.assertRaisesRegex(ValueError, "raw output is missing"):
            POST.validate_manifest_outputs(manifest, logs)


if __name__ == "__main__":
    unittest.main()
