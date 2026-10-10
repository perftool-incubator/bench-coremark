import hashlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SPEC = importlib.util.spec_from_file_location("coremark_build", REPO_ROOT / "coremark-build.py")
BUILD = importlib.util.module_from_spec(BUILD_SPEC)
BUILD_SPEC.loader.exec_module(BUILD)


class PinnedBuildInputTests(unittest.TestCase):
    def test_posix_compilation_inputs_have_reviewed_commit_locks(self):
        self.assertEqual(
            BUILD.PINNED_INPUTS["posix/core_portme.mak"],
            "25a50c96fe353523a331f3589fcda1702d6b622c94428df7766dee3e068940fb",
        )
        self.assertEqual(
            BUILD.PINNED_INPUTS["posix/core_portme_posix_overrides.h"],
            "1dc67b5c1b9c773cccc740b911d708333d3bf154c3313f77b8a52e18209eda59",
        )
        self.assertEqual(len(BUILD.PINNED_INPUTS), 11)

    def test_each_new_posix_input_mutation_fails_before_compiler_or_make(self):
        previous_cwd = Path.cwd()
        try:
            for relative_path in (
                "posix/core_portme.mak",
                "posix/core_portme_posix_overrides.h",
            ):
                with self.subTest(path=relative_path), tempfile.TemporaryDirectory() as temporary:
                    work = Path(temporary)
                    (work / "coremark.md5").write_text("pinned source marker\n", encoding="utf-8")
                    changed = work / relative_path
                    changed.parent.mkdir(parents=True, exist_ok=True)
                    changed.write_bytes(b"mutated source input\n")
                    expected = hashlib.sha256(b"official pinned source input\n").hexdigest()
                    os.chdir(work)
                    with patch.object(BUILD, "PINNED_INPUTS", {relative_path: expected}), patch.object(
                        BUILD.platform, "machine", return_value="x86_64"
                    ), patch.object(BUILD, "INSTALL_DIR", work / "install"), patch.object(
                        BUILD.subprocess, "run"
                    ) as make, patch.object(BUILD.subprocess, "check_output") as compiler_probe:
                        with self.assertRaisesRegex(RuntimeError, "pinned upstream input digest mismatch"):
                            BUILD.main()
                    make.assert_not_called()
                    compiler_probe.assert_not_called()
        finally:
            os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
