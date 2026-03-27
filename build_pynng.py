#!/usr/bin/env python3

"""Build the pynng CFFI interface.

Uses headerkit to parse NNG C headers and generate CFFI cdef declarations.
headerkit's two-layer cache (.hkcache/) enables builds without libclang
when the cache is committed to version control.
"""

import os
import re

from cffi import FFI
from headerkit import generate

NNG_INCLUDE_DIR = os.environ.get("NNG_INCLUDE_DIR")
if NNG_INCLUDE_DIR is None:
    raise RuntimeError(
        "NNG_INCLUDE_DIR environment variable must be set. "
        "This is normally set by the CMake build system."
    )

NNG_HEADERS = [
    "nng/nng.h",
    "nng/protocol/bus0/bus.h",
    "nng/protocol/pair0/pair.h",
    "nng/protocol/pair1/pair.h",
    "nng/protocol/pipeline0/push.h",
    "nng/protocol/pipeline0/pull.h",
    "nng/protocol/pubsub0/pub.h",
    "nng/protocol/pubsub0/sub.h",
    "nng/protocol/reqrep0/req.h",
    "nng/protocol/reqrep0/rep.h",
    "nng/protocol/survey0/survey.h",
    "nng/protocol/survey0/respond.h",
    "nng/supplemental/tls/tls.h",
    "nng/transport/tls/tls.h",
]

EXCLUDE_PATTERNS = [r"nng_tls_config_(pass|key)"]

# __file__ may not be defined when invoked via cffi_buildtool exec-python.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(
    __file__ if "__file__" in dir() else os.path.join(os.getcwd(), "build_pynng.py")
))


def _existing_header_list() -> list[str]:
    """Return the filtered list of NNG_HEADERS that exist on disk."""
    return [
        h for h in NNG_HEADERS if os.path.exists(os.path.join(NNG_INCLUDE_DIR, h))
    ]


def _extract_defines(nng_h_path: str) -> str:
    """Extract #define constants from nng.h that libclang may not capture."""
    with open(nng_h_path) as f:
        content = f.read()

    defines = []
    for m in re.finditer(
        r"^#define\s+(NNG_FLAG_\w+|NNG_\w+_VERSION|NNG_MAXADDRLEN)\b",
        content,
        re.MULTILINE,
    ):
        name = m.group(1)
        defines.append(f"#define {name} ...")

    return "\n".join(defines)


def generate_cdef() -> tuple[str, list[str]]:
    """Parse NNG headers and generate CFFI cdef declarations.

    Uses headerkit's generate() with two-layer caching. When .hkcache/
    is committed to the repo, builds succeed without libclang (PyPy,
    32-bit, or any platform lacking libclang).

    Returns:
        A tuple of (cdef_string, existing_headers) where existing_headers
        is the filtered list of NNG_HEADERS that exist on disk.
    """
    existing = _existing_header_list()
    includes = "\n".join(f"#include <{h}>" for h in existing)
    umbrella = f"""\
#define NNG_DECL
#define NNG_STATIC_LIB
#define NNG_DEPRECATED
{includes}
"""

    cdef = generate(
        "umbrella.h",
        "cffi",
        code=umbrella,
        include_dirs=[NNG_INCLUDE_DIR],
        defines=["NNG_DECL", "NNG_STATIC_LIB", "NNG_DEPRECATED"],
        writer_options={"exclude_patterns": EXCLUDE_PATTERNS},
        project_prefixes=(NNG_INCLUDE_DIR,),
        cache_dir=os.path.join(_SCRIPT_DIR, ".hkcache"),
        auto_install_libclang=True,
    )

    # Extract additional #define constants from nng.h via regex
    # (libclang does not capture macro values that involve expressions)
    nng_h_path = os.path.join(NNG_INCLUDE_DIR, "nng/nng.h")
    extra_defines = _extract_defines(nng_h_path)
    if extra_defines:
        cdef = cdef + "\n" + extra_defines

    return cdef, existing


# Generate cdef content and get the list of existing headers
cdef_content, _existing_headers = generate_cdef()

callbacks = """
    extern "Python" void _async_complete(void *);
    extern "Python" void _nng_pipe_cb(nng_pipe, nng_pipe_ev, void *);
"""

ffibuilder = FFI()

# Build set_source includes from the existing headers returned by generate_cdef()
_source_includes = "\n".join(f"        #include <{h}>" for h in _existing_headers)

ffibuilder.set_source(
    "pynng._nng",
    f"""
        #define NNG_DECL
        #define NNG_STATIC_LIB
{_source_includes}
    """,
    include_dirs=[NNG_INCLUDE_DIR],
)

ffibuilder.cdef(cdef_content + callbacks)

if __name__ == "__main__":
    ffibuilder.compile(verbose=True)
