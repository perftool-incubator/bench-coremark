# Authentic native output fixtures

These four files are unmodified stdout/stderr captured from the official EEMBC CoreMark source at commit `1f483d5b8316753a742cbf5590caf5bd0a4e4777`. They were emitted by the real prepared 1-context and 2-context POSIX binaries, each running both native seed modes with `iterations=0` and the 2K command-line profile. They are not hand-written or synthetic.

The source came from a clean local clone of the pinned upstream commit. A temporary build copy passed the integration's commit-specific SHA-256 checks before compiling with GCC 15.2.1 on x86_64 using the same flags as the Workshop recipe. The native client adapter captured each process output as-is and accepted both modes for each variant. The run manifest recorded:

| Contexts | Mode | Native seconds | Iterations | Iterations/sec | Seed CRC | Binary SHA-256 |
| ---: | --- | ---: | ---: | ---: | --- | --- |
| 1 | performance | 15.627 | 300000 | 19197.542715 | `0xe9f5` | `8d04c03e182301a4faa5a2147381e016d9b1101ca81c51cd045450fbf3bfeaf5` |
| 1 | validation | 15.655 | 300000 | 19163.206643 | `0x18f2` | `8d04c03e182301a4faa5a2147381e016d9b1101ca81c51cd045450fbf3bfeaf5` |
| 2 | performance | 15.839 | 600000 | 37881.179367 | `0xe9f5` | `8366ec0a4afdf25b6cc5d4be71c0724e863005492b562a13ede481f5f06aee68` |
| 2 | validation | 15.974 | 600000 | 37561.036685 | `0x18f2` | `8366ec0a4afdf25b6cc5d4be71c0724e863005492b562a13ede481f5f06aee68` |

This is local parser/build evidence only. It does not establish a Workshop image build, any particular Crucible userenv image, or a live Crucible run.
