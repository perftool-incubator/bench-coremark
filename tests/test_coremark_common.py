import sys
import unittest
import importlib.util
import json
import re
from pathlib import Path
from unittest.mock import call, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from coremark_common import MAX_ITERATIONS, parse_cli, parse_cpu_list, parse_native_output

CLIENT_SPEC = importlib.util.spec_from_file_location("coremark_client", REPO_ROOT / "coremark-client.py")
CLIENT = importlib.util.module_from_spec(CLIENT_SPEC)
CLIENT_SPEC.loader.exec_module(CLIENT)


FIXTURES = REPO_ROOT / "tests" / "fixtures"


class NativeOutputTests(unittest.TestCase):
    def read_fixture(self, threads, mode):
        path = FIXTURES / ("coremark-%d-threads-%s.txt" % (threads, mode))
        return path.read_text(encoding="utf-8")

    def test_genuine_pinned_source_fixtures_validate(self):
        for threads in (1, 2):
            for mode in ("performance", "validation"):
                with self.subTest(threads=threads, mode=mode):
                    result = parse_native_output(self.read_fixture(threads, mode), mode, threads)
                    self.assertGreaterEqual(result["native_total_time_seconds"], 10)
                    self.assertGreater(result["iterations_per_second"], 0)
                    self.assertEqual(result["context_count"], threads)
                    self.assertEqual(len(result["context_crcs"]), threads)

    def test_rejects_under_ten_second_measurement(self):
        text = self.read_fixture(1, "performance")
        text = text.replace("Total time (secs): 15.627000", "Total time (secs): 9.999000")
        with self.assertRaisesRegex(ValueError, "10-second"):
            parse_native_output(text, "performance", 1)

    def test_rejects_native_error_even_with_success_marker(self):
        text = self.read_fixture(1, "performance") + "ERROR! corrupted output\n"
        with self.assertRaisesRegex(ValueError, "native error marker"):
            parse_native_output(text, "performance", 1)

    def test_rejects_incomplete_crc_coverage(self):
        text = self.read_fixture(2, "validation")
        text = text.replace("[1]crcmatrix     : 0x0747\n", "")
        with self.assertRaisesRegex(ValueError, "CRC coverage mismatch"):
            parse_native_output(text, "validation", 2)

    def test_rejects_wrong_native_context_count(self):
        with self.assertRaisesRegex(ValueError, "context count"):
            parse_native_output(self.read_fixture(1, "performance"), "performance", 2)

    def test_rejects_nonzero_exit_despite_valid_output(self):
        with self.assertRaisesRegex(ValueError, "exited with status 1"):
            parse_native_output(self.read_fixture(1, "performance"), "performance", 1, 1)

    def test_fixed_iterations_must_match_aggregate_context_count(self):
        text = self.read_fixture(1, "performance")
        with self.assertRaisesRegex(ValueError, "aggregate iterations"):
            parse_native_output(text, "performance", 1, expected_iterations=1)

    def test_fixed_iteration_count_accepts_native_aggregate(self):
        for threads in (1, 2):
            text = self.read_fixture(threads, "performance")
            expected_count = threads
            duration = parse_native_output(text, "performance", threads)["native_total_time_seconds"]
            rate = expected_count / duration
            text = re.sub(r"^Iterations\s*:\s*[0-9]+$", "Iterations       : %d" % expected_count, text, flags=re.M)
            text = re.sub(r"^Iterations/Sec\s*:\s*[0-9.]+$", "Iterations/Sec   : %.6f" % rate, text, flags=re.M)
            text = re.sub(r"^(CoreMark 1\.0\s*:\s*)[0-9.]+", r"\g<1>%.6f" % rate, text, flags=re.M)
            result = parse_native_output(
                text, "performance", threads, expected_iterations=1
            )
            self.assertEqual(result["iterations"], expected_count)


class RuntimeInputTests(unittest.TestCase):
    def test_cpu_list_ranges_and_duplicates(self):
        self.assertEqual(parse_cpu_list("1,3-5,4"), [1, 3, 4, 5])

    def test_cpu_list_rejects_descending_range(self):
        with self.assertRaisesRegex(ValueError, "descending"):
            parse_cpu_list("4-2")

    def test_accepts_prepared_variant_and_native_auto_iterations(self):
        args = parse_cli(["--threads", "2", "--iterations", "0", "--deadline", "300"])
        self.assertEqual((args.threads, args.iterations, args.deadline), (2, 0, 300))

    def test_fixed_iterations_are_bounded_to_upstream_signed_32_bit(self):
        self.assertEqual(parse_cli(["--iterations", "0"]).iterations, 0)
        self.assertEqual(parse_cli(["--iterations", str(MAX_ITERATIONS)]).iterations, MAX_ITERATIONS)
        for invalid in ("-1", str(MAX_ITERATIONS + 1), "999999999999999999999999999999"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "iterations must be"):
                parse_cli(["--iterations", invalid])

    def test_multiplex_iteration_pattern_matches_the_same_upstream_bound(self):
        config = json.loads((REPO_ROOT / "multiplex.json").read_text(encoding="utf-8"))
        pattern = config["validations"]["iterations_or_auto"]["vals"]
        for value in ("0", "1", str(MAX_ITERATIONS)):
            with self.subTest(value=value):
                self.assertRegex(value, re.compile(pattern))
        for value in (str(MAX_ITERATIONS + 1), "999999999999999999999999999999", "-1"):
            with self.subTest(value=value):
                self.assertIsNone(re.fullmatch(pattern, value))

    def test_rejects_unprepared_thread_count(self):
        with self.assertRaisesRegex(ValueError, "installed variant"):
            parse_cli(["--threads", "3"])

    def test_workload_affinity_expands_inherited_housekeeping_mask_safely(self):
        # Rickshaw pins the engine to housekeeping CPUs; cgroup-effective
        # affinity after requesting WORKLOAD_CPUS decides usable workload CPUs.
        with patch.dict(
            "os.environ",
            {"WORKLOAD_CPUS": "4-6", "HK_CPUS": "1", "cpu_partitioning": "1"},
            clear=False,
        ), patch.object(CLIENT.os, "sched_getaffinity", side_effect=[{1}, {5, 6}, {5, 6}]), patch.object(
            CLIENT.os, "sched_setaffinity"
        ) as set_affinity:
            details = CLIENT.prepare_cpu_affinity(2)

        self.assertEqual(details["engine_affinity_before"], [1])
        self.assertEqual(details["requested_workload_cpus"], [4, 5, 6])
        self.assertEqual(details["effective_workload_cpus_after_cgroup_filter"], [5, 6])
        self.assertEqual(details["selected_affinity"], [5, 6])
        self.assertEqual(set_affinity.call_args_list, [call(0, {4, 5, 6}), call(0, {5, 6})])


if __name__ == "__main__":
    unittest.main()
