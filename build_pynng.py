#!/usr/bin/env python3

"""Build the pynng CFFI interface.

Uses headerkit's libclang backend to parse NNG C headers into an IR,
then converts the IR to CFFI cdef strings.

This module serves dual purposes:
  1. Build-time: executed by cffi_buildtool to generate CFFI bindings
  2. Test-time: imported by tests to verify generate_cdef() and _extract_defines()

When imported as a regular Python module (e.g., by tests), only the functions
and constants are made available. The ffibuilder setup only runs when executed
by cffi_buildtool (which sets __name__ to "gen-cffi-src") or directly.
"""

import os
import re


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


def _get_nng_include_dir() -> str:
    """Read NNG_INCLUDE_DIR from the environment.

    Raises:
        RuntimeError: If NNG_INCLUDE_DIR is not set.
    """
    include_dir = os.environ.get("NNG_INCLUDE_DIR")
    if include_dir is None:
        raise RuntimeError(
            "NNG_INCLUDE_DIR environment variable must be set. "
            "This is normally set by the CMake build system."
        )
    return include_dir


def generate_cdef() -> tuple[str, list[str]]:
    """Parse NNG headers and generate CFFI cdef declarations.

    Reads NNG_INCLUDE_DIR from the environment at call time.

    Returns:
        A tuple of (cdef_string, existing_headers) where existing_headers
        is the filtered list of NNG_HEADERS that exist on disk.
    """
    from headerkit.backends import get_backend
    from headerkit.writers.cffi import header_to_cffi

    nng_include_dir = _get_nng_include_dir()

    # Build umbrella header that includes all existing NNG headers
    existing = [
        h for h in NNG_HEADERS if os.path.exists(os.path.join(nng_include_dir, h))
    ]
    includes = "\n".join(f"#include <{h}>" for h in existing)
    umbrella = f"""\
#define NNG_DECL
#define NNG_STATIC_LIB
#define NNG_DEPRECATED
{includes}
"""

    # Parse with headerkit libclang backend
    backend = get_backend("libclang")
    header = backend.parse(
        umbrella,
        "umbrella.h",
        include_dirs=[nng_include_dir],
        project_prefixes=(nng_include_dir,),
    )

    # Convert IR to CFFI cdef string
    cdef = header_to_cffi(header, exclude_patterns=EXCLUDE_PATTERNS)

    # Extract additional #define constants from nng.h via regex
    # (libclang can miss macro values that involve expressions)
    nng_h_path = os.path.join(nng_include_dir, "nng/nng.h")
    extra_defines = _extract_defines(nng_h_path)
    if extra_defines:
        cdef = cdef + "\n" + extra_defines

    return cdef, existing


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


def _build_ffi():
    """Set up the CFFI ffibuilder for use by cffi_buildtool.

    This is called at module level only during builds (cffi_buildtool or
    direct execution), never when imported by tests.
    """
    from cffi import FFI

    nng_include_dir = _get_nng_include_dir()

    # Generate cdef content and get the list of existing headers
    cdef_content, existing_headers = generate_cdef()

    callbacks = """
        extern "Python" void _async_complete(void *);
        extern "Python" void _nng_pipe_cb(nng_pipe, nng_pipe_ev, void *);
    """

    ffi = FFI()

    # Build set_source includes from the existing headers returned by generate_cdef()
    source_includes = "\n".join(f"        #include <{h}>" for h in existing_headers)

    ffi.set_source(
        "pynng._nng",
        f"""
            #define NNG_DECL
            #define NNG_STATIC_LIB
    {source_includes}
        """,
        include_dirs=[nng_include_dir],
    )

    ffi.cdef(cdef_content + callbacks)
    return ffi


# Only run the build when executed by cffi_buildtool (sets __name__ to
# "gen-cffi-src") or when run directly as a script. When imported normally
# by tests (__name__ == "build_pynng"), skip the build setup.
if __name__ in ("gen-cffi-src", "__main__"):
    ffibuilder = _build_ffi()

    if __name__ == "__main__":
        ffibuilder.compile(verbose=True)
