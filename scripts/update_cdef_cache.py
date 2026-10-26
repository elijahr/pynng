#!/usr/bin/env python3
"""Regenerate the committed cdef caches from nng headers.

The caches let Python 3.10, which headerkit does not support, build pynng.
Run this with Python 3.11+ and headerkit whenever the bundled nng versions,
the exclude patterns, the cdef post-processing in build_pynng.py, or headerkit
change. After a build, the headers are in:

    v1: build/<tag>/_deps/nng-src/include
    v2: build/<tag>/nng_v2_install/include
"""

from __future__ import annotations

import argparse
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

import build_pynng


def write_cdef_caches(include_dirs: dict[str, str]) -> list[str]:
    """Write each cache in build_pynng.CDEF_CACHES and return the paths."""
    written = []
    for name, (headers, pattern_lists) in build_pynng.CDEF_CACHES.items():
        include_dir = include_dirs[name]
        variants = [
            (patterns, build_pynng.generate_cdef(headers, include_dir, patterns)[0])
            for patterns in pattern_lists
        ]
        text = build_pynng.format_cdef_cache(
            build_pynng.nng_headers_stamp(include_dir), variants
        )
        path = os.path.join(_PROJECT_ROOT, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--v1-include", required=True, help="nng v1 include dir")
    parser.add_argument("--v2-include", required=True, help="nng v2 include dir")
    args = parser.parse_args(argv)
    if not build_pynng._HEADERKIT_SUPPORTED:
        parser.error("headerkit, and so this script, requires Python 3.11+")
    for path in write_cdef_caches(
        {
            "_nng_cdef_cache.txt": args.v1_include,
            "_nng_v2_cdef_cache.txt": args.v2_include,
        }
    ):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
