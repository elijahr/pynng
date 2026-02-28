#!/usr/bin/env python3

"""Build the pynng CFFI interface.

Uses headerkit's libclang backend to parse NNG C headers into an IR,
then converts the IR to CFFI cdef strings.
"""

import os
import re

from headerkit.backends import get_backend
from cffi import FFI

from headerkit.writers.cffi import header_to_cffi

NNG_INCLUDE_DIR = os.environ["NNG_INCLUDE_DIR"]

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


def generate_cdef() -> str:
    """Parse NNG headers and generate CFFI cdef declarations."""
    # Build umbrella header that includes all existing NNG headers
    existing = [
        h for h in NNG_HEADERS if os.path.exists(os.path.join(NNG_INCLUDE_DIR, h))
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
        include_dirs=[NNG_INCLUDE_DIR],
        project_prefixes=(NNG_INCLUDE_DIR,),
    )

    # Convert IR to CFFI cdef string
    cdef = header_to_cffi(header, exclude_patterns=EXCLUDE_PATTERNS)

    # Extract additional #define constants from nng.h via regex
    # (libclang can miss macro values that involve expressions)
    nng_h_path = os.path.join(NNG_INCLUDE_DIR, "nng/nng.h")
    extra_defines = _extract_defines(nng_h_path)
    if extra_defines:
        cdef = cdef + "\n" + extra_defines

    return cdef


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


# Generate cdef content
cdef_content = generate_cdef()

callbacks = """
    extern "Python" void _async_complete(void *);
    extern "Python" void _nng_pipe_cb(nng_pipe, nng_pipe_ev, void *);
"""

ffibuilder = FFI()

# Build set_source includes from the same header list
_existing_headers = [
    h for h in NNG_HEADERS if os.path.exists(os.path.join(NNG_INCLUDE_DIR, h))
]
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
