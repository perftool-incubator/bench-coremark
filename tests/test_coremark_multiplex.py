import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from coremark_common import parse_cli

CLIENT_SPEC = importlib.util.spec_from_file_location("coremark_client", REPO_ROOT / "coremark-client.py")
CLIENT = importlib.util.module_from_spec(CLIENT_SPEC)
CLIENT_SPEC.loader.exec_module(CLIENT)


def locate_multiplex_home():
    configured = os.environ.get("MULTIPLEX_HOME")
    candidates = [Path(configured)] if configured else []
    candidates.extend(
        [
            Path("/opt/crucible/subprojects/core/multiplex"),
            REPO_ROOT.parents[1] / "sources" / "multiplex",
        ]
    )
    for candidate in candidates:
        if (candidate / "multiplex.py").is_file() and (candidate / "JSON" / "req-schema.json").is_file():
            return candidate
    return None


MULTIPLEX_HOME = locate_multiplex_home()


@unittest.skipUnless(MULTIPLEX_HOME, "set MULTIPLEX_HOME to an installed/source Multiplex checkout")
class ActualMultiplexContractTests(unittest.TestCase):
    def expand(self, params):
        document = {"global-options": [], "sets": [{"params": params}]}
        with tempfile.TemporaryDirectory(prefix="coremark-multiplex-test-") as temporary:
            work = Path(temporary)
            input_path = work / "input.json"
            output_path = work / "output.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(MULTIPLEX_HOME / "multiplex.py"),
                    "--requirements",
                    str(REPO_ROOT / "multiplex.json"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=MULTIPLEX_HOME,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(output_path.read_text(encoding="utf-8"))

    @staticmethod
    def values(expanded_set):
        return {parameter["arg"]: parameter["val"] for parameter in expanded_set}

    def test_empty_parameter_set_uses_single_thread_default_and_all_runtime_defaults(self):
        expanded = self.expand([])
        self.assertEqual(len(expanded), 1)
        self.assertEqual(self.values(expanded[0]), {"threads": "1", "iterations": "0", "deadline": "300"})

    def test_partial_thread_selections_do_not_expand_to_both_variants(self):
        for selected in ("1", "2"):
            with self.subTest(threads=selected):
                expanded = self.expand([{"arg": "threads", "vals": [selected]}])
                self.assertEqual(len(expanded), 1)
                self.assertEqual(self.values(expanded[0]), {"threads": selected})
                effective = CLIENT.effective_requested_parameters(parse_cli(["--threads", selected]))
                self.assertEqual(effective["threads"], int(selected))
                self.assertEqual(effective["iterations"], 0)
                self.assertEqual(effective["deadline_seconds_per_mode"], 300)

    def test_explicit_runtime_values_survive_actual_multiplex_expansion(self):
        params = [
            {"arg": "threads", "vals": ["2"]},
            {"arg": "iterations", "vals": ["12345"]},
            {"arg": "deadline", "vals": ["60"]},
        ]
        expanded = self.expand(params)
        self.assertEqual(len(expanded), 1)
        self.assertEqual(self.values(expanded[0]), {"threads": "2", "iterations": "12345", "deadline": "60"})
        argv = []
        for arg, value in self.values(expanded[0]).items():
            argv.extend(["--" + arg, value])
        effective = CLIENT.effective_requested_parameters(parse_cli(argv))
        self.assertEqual(effective["threads"], 2)
        self.assertEqual(effective["iterations"], 12345)
        self.assertEqual(effective["deadline_seconds_per_mode"], 60)
        self.assertEqual(effective["standard_total_data_bytes"], 2000)

    def test_omitted_thread_uses_client_default_with_other_values_explicit(self):
        params = [
            {"arg": "iterations", "vals": ["12345"]},
            {"arg": "deadline", "vals": ["60"]},
        ]
        expanded = self.expand(params)
        self.assertEqual(len(expanded), 1)
        self.assertEqual(self.values(expanded[0]), {"iterations": "12345", "deadline": "60"})
        argv = []
        for arg, value in self.values(expanded[0]).items():
            argv.extend(["--" + arg, value])
        effective = CLIENT.effective_requested_parameters(parse_cli(argv))
        self.assertEqual(effective["threads"], 1)
        self.assertEqual(effective["iterations"], 12345)
        self.assertEqual(effective["deadline_seconds_per_mode"], 60)


if __name__ == "__main__":
    unittest.main()
