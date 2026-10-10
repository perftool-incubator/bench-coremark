import csv
import json
import lzma
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from coremark_common import UPSTREAM_COMMIT, parse_native_output


def locate_toolbox_home():
    configured = os.environ.get("TOOLBOX_HOME")
    candidates = [Path(configured)] if configured else []
    candidates.append(REPO_ROOT.parents[1] / "sources" / "toolbox")
    for candidate in candidates:
        if (candidate / "python" / "toolbox" / "cdm_metrics.py").is_file():
            return candidate
    return None


TOOLBOX_HOME = locate_toolbox_home()


class RickshawEntrypointModeTests(unittest.TestCase):
    def test_every_direct_rickshaw_hook_resolves_to_executable_file(self):
        config = json.loads((REPO_ROOT / "rickshaw.json").read_text(encoding="utf-8"))
        direct_hooks = {
            "client.start": REPO_ROOT / config["client"]["start"],
            "client.runtime": REPO_ROOT / config["client"]["runtime"],
            "controller.post-script": REPO_ROOT
            / config["controller"]["post-script"].replace("%bench-dir%", ""),
        }
        for hook, path in direct_hooks.items():
            with self.subTest(hook=hook):
                self.assertTrue(path.is_file(), "%s does not resolve: %s" % (hook, path))
                self.assertTrue(path.stat().st_mode & stat.S_IXUSR, "%s lacks owner execute mode" % hook)
                self.assertTrue(os.access(path, os.X_OK), "%s is not directly executable" % hook)
                first_line = path.read_bytes().splitlines()[0]
                self.assertTrue(first_line.startswith(b"#!"), "%s has no interpreter line" % hook)

    @unittest.skipUnless(TOOLBOX_HOME, "TOOLBOX_HOME with toolbox/python is required")
    def test_post_script_emits_native_per_sample_rate_with_sum_default_for_both_variants(self):
        config = json.loads((REPO_ROOT / "rickshaw.json").read_text(encoding="utf-8"))
        post_script = REPO_ROOT / config["controller"]["post-script"].replace("%bench-dir%", "")
        completion_base_ns = 1_800_000_000_000_000_000
        for threads in (1, 2):
            with self.subTest(threads=threads), tempfile.TemporaryDirectory(
                prefix="coremark-direct-post-script-"
            ) as temporary:
                sample = Path(temporary)
                modes = {}
                parsed_performance = None
                for index, mode in enumerate(("performance", "validation")):
                    output = (
                        REPO_ROOT
                        / "tests"
                        / "fixtures"
                        / ("coremark-%d-threads-%s.txt" % (threads, mode))
                    ).read_text(encoding="utf-8")
                    (sample / ("coremark-%s.txt" % mode)).write_text(output, encoding="utf-8")
                    native = parse_native_output(output, mode, threads)
                    if mode == "performance":
                        parsed_performance = native
                    completion_ns = completion_base_ns + index * 1_000_000_000
                    native["measurement_end_epoch_ms_estimate"] = completion_ns // 1_000_000
                    native["measurement_begin_epoch_ms_estimate"] = int(
                        completion_ns / 1_000_000 - native["native_total_time_seconds"] * 1000
                    )
                    modes[mode] = {
                        "return_code": 0,
                        "timed_out": False,
                        "interrupted": False,
                        "launch_begin_epoch_ns": completion_ns - 60_000_000_000,
                        "process_completion_epoch_ns": completion_ns,
                        "launch_to_completion_seconds": 60.0,
                        "native_result": native,
                    }
                manifest = {
                    "benchmark": "coremark",
                    "upstream_commit": UPSTREAM_COMMIT,
                    "status": "valid",
                    "requested": {
                        "threads": threads,
                        "iterations": 0,
                        "deadline_seconds_per_mode": 300,
                        "standard_total_data_bytes": 2000,
                    },
                    "modes": modes,
                }
                (sample / "coremark-run-manifest.json").write_text(
                    json.dumps(manifest), encoding="utf-8"
                )
                environment = dict(
                    os.environ,
                    TOOLBOX_HOME=str(TOOLBOX_HOME),
                    RS_CS_LABEL="coremark-client-1",
                    PYTHONDONTWRITEBYTECODE="1",
                )
                result = subprocess.run(
                    [str(post_script)],
                    cwd=sample,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                sample_data = json.loads(
                    (sample / "postprocess" / "post-process-data.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(sample_data["primary-metric"], "iterations-sec")

                metric_types_path = sample / "postprocess" / "metric-data-0.json.xz"
                with lzma.open(metric_types_path, "rt", encoding="utf-8") as stream:
                    metric_types = json.load(stream)
                self.assertEqual(len(metric_types), 1)
                descriptor = metric_types[0]["desc"]
                self.assertEqual(descriptor["default-aggregation"], "sum")
                self.assertEqual(descriptor["class"], "throughput")

                data_path = sample / "postprocess" / "metric-data-0.csv.xz"
                with lzma.open(data_path, "rt", encoding="utf-8", newline="") as stream:
                    rows = list(csv.reader(stream))
                self.assertEqual(len(rows), 1, "one native score must be emitted per sample")
                emitted_rate = float(rows[0][3])
                self.assertAlmostEqual(
                    emitted_rate,
                    parsed_performance["iterations_per_second"],
                    places=9,
                )
                if threads == 2:
                    self.assertNotAlmostEqual(
                        emitted_rate,
                        parsed_performance["iterations_per_second"] * threads,
                        places=6,
                    )


if __name__ == "__main__":
    unittest.main()
