#!/usr/bin/env python3
# -*- mode: python; indent-tabs-mode: nil; python-indent-level: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python

"""Build and install only the reviewed CoreMark thread variants in Workshop."""

import datetime
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path


UPSTREAM_COMMIT = "1f483d5b8316753a742cbf5590caf5bd0a4e4777"
VARIANTS = (1, 2)
INSTALL_DIR = Path(os.environ.get("COREMARK_INSTALL_DIR", "/usr/local/libexec/coremark"))
COMMON_FLAGS = ("-O2",)
PINNED_INPUTS = {
    "core_list_join.c": "ca00e4e010ece47d7f040cb92aa50a95345a00d3171b59d088f6b243be06ce7b",
    "core_main.c": "17884c93c5b94378eb0ff02b4df3725756cf2addb9b8cbcaa6200a4649ff5ca7",
    "core_matrix.c": "ecdff717b5a5c4907d221a606760e25499899cbf617582c05d40db71c91351e4",
    "core_state.c": "f4b84bb0a3452c45a4daa664ab502bfdccbd31cb57d93e9ac490c60937717a4e",
    "core_util.c": "a3fbfcb9bb943b638624b8ece01c5836dd56a96d7bcde2697b248d077447327f",
    "coremark.h": "42642b9a06c7ed2b3bd9eda971b7c3868c4f5d27bf7ef6c4bba11291a0c2598a",
    "Makefile": "1e4661a40784bba0ab08dd679b0159ddced6611757ae39d0927a83dbe9fabd60",
    "posix/core_portme.c": "f2b48f062058d528a5907e339ffd05d98f64d59e7c40d500fe05563eb5247ad0",
    "posix/core_portme.h": "a40e90ef4c5a5626d438afee1f8da628c2800105d4c3b5318e8810b34be554f2",
    "posix/core_portme.mak": "25a50c96fe353523a331f3589fcda1702d6b622c94428df7766dee3e068940fb",
    "posix/core_portme_posix_overrides.h": "1dc67b5c1b9c773cccc740b911d708333d3bf154c3313f77b8a52e18209eda59",
}


def run(command):
    print("$ " + shlex.join(command), flush=True)
    subprocess.run(command, check=True)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_pinned_inputs(source_dir=Path("."), pinned_inputs=None):
    """Reject modified or incomplete upstream source/build inputs before compiling."""
    for relative_path, expected_digest in (pinned_inputs or PINNED_INPUTS).items():
        path = Path(source_dir) / relative_path
        if not path.is_file() or sha256(path) != expected_digest:
            raise RuntimeError("pinned upstream input digest mismatch: %s" % relative_path)


def main():
    if platform.machine() != "x86_64":
        raise RuntimeError("the initial CoreMark Workshop recipe is validated only for x86_64")
    if not Path("coremark.md5").is_file():
        raise RuntimeError("not in the expected unmodified EEMBC CoreMark source tree")

    verify_pinned_inputs()
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    compiler_version = subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]
    compiler_release = subprocess.check_output(["gcc", "-dumpfullversion", "-dumpversion"], text=True).strip()
    built_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    for thread_count in VARIANTS:
        run(["make", "clean", "PORT_DIR=posix"])
        xcflags = "-DMULTITHREAD=%d -DUSE_PTHREAD -pthread" % thread_count
        run([
            "make",
            "compile",
            "CC=gcc",
            "PORT_DIR=posix",
            "PORT_CFLAGS=" + " ".join(COMMON_FLAGS),
            "ITERATIONS=0",
            "XCFLAGS=" + xcflags,
        ])

        binary = INSTALL_DIR / ("coremark-threads-%d" % thread_count)
        binary.write_bytes(Path("coremark.exe").read_bytes())
        binary.chmod(0o755)
        provenance = {
            "benchmark": "CoreMark",
            "upstream_repository": "https://github.com/eembc/coremark",
            "upstream_commit": UPSTREAM_COMMIT,
            "source_check": "all benchmark, Makefile, and POSIX compilation input SHA-256 locks passed",
            "source_sha256": PINNED_INPUTS,
            "upstream_make_check_note": (
                "The pinned upstream coremark.md5 has a stale coremark.h digest at this revision; "
                "make check rejects the unchanged official file. Exact commit-specific SHA-256 locks are used."
            ),
            "architecture": platform.machine(),
            "thread_count": thread_count,
            "compiler": "gcc",
            "compiler_version": compiler_version,
            "compiler_release": compiler_release,
            "compiler_flags": list(COMMON_FLAGS) + [
                "-DMULTITHREAD=%d" % thread_count,
                "-DUSE_PTHREAD",
                "-pthread",
                "-lrt",
            ],
            "port_cflags": list(COMMON_FLAGS),
            "link_flags": ["-lrt"],
            "port": "upstream POSIX port",
            "upstream_source_modified": False,
            "built_at_utc": built_at,
            "installed_path": str(binary),
            "binary_sha256": sha256(binary),
        }
        (INSTALL_DIR / ("coremark-threads-%d.build.json" % thread_count)).write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(provenance, sort_keys=True), flush=True)

    (INSTALL_DIR / "build-manifest.json").write_text(
        json.dumps(
            {
                "upstream_commit": UPSTREAM_COMMIT,
                "source_check": "all benchmark, Makefile, and POSIX compilation input SHA-256 locks passed",
                "source_sha256": PINNED_INPUTS,
                "architecture": platform.machine(),
                "prepared_thread_variants": list(VARIANTS),
                "built_at_utc": built_at,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print("CoreMark Workshop build failed: %s" % exc, file=sys.stderr)
        sys.exit(1)
