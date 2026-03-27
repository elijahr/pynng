#!/usr/bin/env python3

"""Build the pynng CFFI interface.

Uses headerkit to parse NNG C headers and generate CFFI cdef declarations.
headerkit's two-layer cache (.headerkit/) enables builds without libclang
when the cache is committed to version control.
"""

import os

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

# __file__ may not be defined when invoked via cffi_buildtool exec-python.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(
    __file__ if "__file__" in dir() else os.path.join(os.getcwd(), "build_pynng.py")
))

existing_headers = [
    h for h in NNG_HEADERS if os.path.exists(os.path.join(NNG_INCLUDE_DIR, h))
]
includes = "\n".join(f"#include <{h}>" for h in existing_headers)
umbrella = f"""\
#define NNG_DECL
#define NNG_STATIC_LIB
#define NNG_DEPRECATED
{includes}
"""

cdef_content = generate(
    "umbrella.h",
    "cffi",
    code=umbrella,
    include_dirs=[NNG_INCLUDE_DIR],
    defines=["NNG_DECL", "NNG_STATIC_LIB", "NNG_DEPRECATED"],
    writer_options={
        "exclude_patterns": [r"nng_tls_config_(pass|key)"],
        "define_patterns": [r"NNG_FLAG_\w+", r"NNG_\w+_VERSION", r"NNG_MAXADDRLEN"],
        "extra_cdef": [
            'extern "Python" void _async_complete(void *);',
            'extern "Python" void _nng_pipe_cb(nng_pipe, nng_pipe_ev, void *);',
        ],
    },
    project_prefixes=(NNG_INCLUDE_DIR,),
    store_dir=os.environ.get("HEADERKIT_STORE_DIR", os.path.join(_SCRIPT_DIR, ".headerkit")),
    auto_install_libclang=True,
)

ffibuilder = FFI()

source_includes = "\n".join(f"        #include <{h}>" for h in existing_headers)
ffibuilder.set_source(
    "pynng._nng",
    f"""
        #define NNG_DECL
        #define NNG_STATIC_LIB
{source_includes}
    """,
    include_dirs=[NNG_INCLUDE_DIR],
)

ffibuilder.cdef(cdef_content)

if __name__ == "__main__":
    ffibuilder.compile(verbose=True)
