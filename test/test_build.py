"""Tests for the CFFI generation pipeline in build_pynng.py.

Validates that the generated FFI bindings contain all expected NNG types,
functions, and constants, and that excluded patterns are properly filtered.

These tests operate on the already-compiled _nng module to verify the end
result of the build pipeline. Where NNG headers are available (via
NNG_INCLUDE_DIR or the build cache), they also test the build functions
directly.
"""

import os
import re
import sys

import pytest

# Ensure the project root is on sys.path so that build_pynng.py is importable.
# This is necessary in cibuildwheel and other environments where pytest runs
# from a directory that doesn't include the project root.
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from pynng._nng import ffi, lib


# -- Tests against the compiled FFI module ------------------------------------


class TestFFICoreTypes:
    """Verify that the FFI knows about all core NNG types."""

    @pytest.mark.parametrize(
        "type_name",
        [
            "nng_socket",
            "nng_pipe",
            "nng_aio",
            "nng_ctx",
            "nng_msg",
            "nng_dialer",
            "nng_listener",
        ],
    )
    def test_ffi_knows_core_types(self, type_name):
        # ffi.typeof raises FFIError if the type is unknown
        result = ffi.typeof(type_name)
        assert result is not None
        assert result.kind in ("struct", "union"), (
            "Expected struct or union for {}, got {}".format(type_name, result.kind)
        )

    @pytest.mark.parametrize(
        "type_name",
        [
            "nng_socket *",
            "nng_pipe *",
            "nng_aio *",
            "nng_ctx *",
            "nng_msg *",
            "nng_dialer *",
            "nng_listener *",
        ],
    )
    def test_ffi_knows_pointer_types(self, type_name):
        result = ffi.typeof(type_name)
        assert result is not None
        assert result.kind == "pointer", (
            "Expected pointer for {}, got {}".format(type_name, result.kind)
        )


class TestFFICoreFunctions:
    """Verify that all expected protocol openers and core functions exist."""

    @pytest.mark.parametrize(
        "func_name",
        [
            "nng_pair0_open",
            "nng_pair1_open",
            "nng_req0_open",
            "nng_rep0_open",
            "nng_pub0_open",
            "nng_sub0_open",
            "nng_push0_open",
            "nng_pull0_open",
            "nng_bus0_open",
            "nng_surveyor0_open",
            "nng_respondent0_open",
        ],
    )
    def test_ffi_has_protocol_openers(self, func_name):
        assert hasattr(lib, func_name)

    @pytest.mark.parametrize(
        "func_name",
        [
            "nng_send",
            "nng_recv",
            "nng_close",
            "nng_aio_alloc",
            "nng_ctx_open",
            "nng_dial",
            "nng_listen",
            "nng_strerror",
            "nng_msg_alloc",
            "nng_msg_free",
        ],
    )
    def test_ffi_has_core_functions(self, func_name):
        assert hasattr(lib, func_name)


class TestFFIExcludePatterns:
    """Verify that EXCLUDE_PATTERNS properly filter sensitive TLS functions."""

    @pytest.mark.parametrize(
        "func_name",
        [
            "nng_tls_config_pass",
            "nng_tls_config_key",
        ],
    )
    def test_ffi_excludes_filtered_functions(self, func_name):
        assert not hasattr(lib, func_name)

    def test_ffi_retains_non_excluded_tls_functions(self):
        # nng_tls_config_alloc should NOT be excluded
        assert hasattr(lib, "nng_tls_config_alloc")


class TestFFIDefines:
    """Verify that #define constants extracted from nng.h are present."""

    @pytest.mark.parametrize(
        "define_name",
        [
            "NNG_FLAG_ALLOC",
            "NNG_FLAG_NONBLOCK",
            pytest.param(
                "NNG_MAXADDRLEN",
                marks=pytest.mark.skipif(
                    not hasattr(lib, "NNG_MAXADDRLEN"),
                    reason="NNG_MAXADDRLEN only available with headerkit build system",
                ),
            ),
        ],
    )
    def test_ffi_has_flag_defines(self, define_name):
        assert hasattr(lib, define_name)

    def test_flag_alloc_is_integer(self):
        assert isinstance(lib.NNG_FLAG_ALLOC, int)

    def test_flag_nonblock_is_integer(self):
        assert isinstance(lib.NNG_FLAG_NONBLOCK, int)

    @pytest.mark.skipif(
        not hasattr(lib, "NNG_MAXADDRLEN"),
        reason="NNG_MAXADDRLEN only available with headerkit build system",
    )
    def test_maxaddrlen_is_positive(self):
        assert lib.NNG_MAXADDRLEN > 0


# -- Tests against build_pynng functions directly ----------------------------
# These require the NNG include directory to be available (either via env var
# or auto-detected from the build cache).

from build_pynng import find_nng_include_dir

_NNG_INCLUDE_DIR = find_nng_include_dir()

_skip_no_headers = pytest.mark.skipif(
    _NNG_INCLUDE_DIR is None,
    reason="NNG headers not available (set NNG_INCLUDE_DIR, install libnng-dev, or build first)",
)


@_skip_no_headers
class TestExtractDefines:
    """Test _extract_defines() from build_pynng against real NNG headers."""

    @pytest.fixture(autouse=True)
    def _set_include_dir(self):
        old = os.environ.get("NNG_INCLUDE_DIR")
        os.environ["NNG_INCLUDE_DIR"] = _NNG_INCLUDE_DIR
        yield
        if old is None:
            os.environ.pop("NNG_INCLUDE_DIR", None)
        else:
            os.environ["NNG_INCLUDE_DIR"] = old

    def _get_extract_defines(self):
        from build_pynng import _extract_defines

        return _extract_defines

    def test_extract_defines_contains_expected_names(self):
        _extract_defines = self._get_extract_defines()
        nng_h = os.path.join(_NNG_INCLUDE_DIR, "nng", "nng.h")
        result = _extract_defines(nng_h)
        assert "NNG_FLAG_ALLOC" in result
        assert "NNG_FLAG_NONBLOCK" in result
        assert "NNG_MAXADDRLEN" in result

    def test_extract_defines_format(self):
        _extract_defines = self._get_extract_defines()
        nng_h = os.path.join(_NNG_INCLUDE_DIR, "nng", "nng.h")
        result = _extract_defines(nng_h)
        assert result.strip(), "Expected non-empty defines output"
        for line in result.strip().split("\n"):
            assert line.startswith("#define "), f"Bad line: {line!r}"
            assert line.endswith(" ..."), f"Bad line: {line!r}"
            # Verify the name is a valid C identifier
            parts = line.split()
            name = parts[1]
            assert re.match(r"^[A-Z_][A-Z0-9_]+$", name), (
                f"Invalid define name: {name!r}"
            )

    def test_extract_defines_returns_string(self):
        _extract_defines = self._get_extract_defines()
        nng_h = os.path.join(_NNG_INCLUDE_DIR, "nng", "nng.h")
        result = _extract_defines(nng_h)
        assert isinstance(result, str)


@_skip_no_headers
class TestGenerateCdef:
    """Test generate_cdef() from build_pynng against real NNG headers."""

    @pytest.fixture(autouse=True)
    def _set_include_dir(self):
        old = os.environ.get("NNG_INCLUDE_DIR")
        os.environ["NNG_INCLUDE_DIR"] = _NNG_INCLUDE_DIR
        yield
        if old is None:
            os.environ.pop("NNG_INCLUDE_DIR", None)
        else:
            os.environ["NNG_INCLUDE_DIR"] = old

    def test_cdef_is_valid_cffi(self):
        """The generated cdef can be parsed by a fresh FFI without error."""
        from build_pynng import generate_cdef

        cdef, _ = generate_cdef()
        test_ffi = __import__("cffi").FFI()
        # This will raise cffi.CDefError or cffi.FFIError if the cdef is bad
        test_ffi.cdef(cdef)

    def test_cdef_contains_core_types(self):
        from build_pynng import generate_cdef

        cdef, _ = generate_cdef()
        for type_name in [
            "nng_socket",
            "nng_pipe",
            "nng_aio",
            "nng_ctx",
            "nng_msg",
            "nng_dialer",
            "nng_listener",
        ]:
            assert type_name in cdef, f"Missing type {type_name} in cdef"

    def test_cdef_contains_protocol_openers(self):
        from build_pynng import generate_cdef

        cdef, _ = generate_cdef()
        for func in [
            "nng_pair0_open",
            "nng_req0_open",
            "nng_rep0_open",
            "nng_pub0_open",
            "nng_sub0_open",
            "nng_push0_open",
            "nng_pull0_open",
            "nng_bus0_open",
            "nng_surveyor0_open",
            "nng_respondent0_open",
        ]:
            assert func in cdef, f"Missing function {func} in cdef"

    def test_cdef_excludes_filtered_patterns(self):
        from build_pynng import generate_cdef

        cdef, _ = generate_cdef()
        assert "nng_tls_config_pass" not in cdef
        assert "nng_tls_config_key" not in cdef
        # But other TLS functions should be present
        assert "nng_tls_config_alloc" in cdef

    def test_cdef_contains_core_functions(self):
        from build_pynng import generate_cdef

        cdef, _ = generate_cdef()
        for func in ["nng_send", "nng_recv", "nng_close", "nng_aio_alloc", "nng_ctx_open"]:
            assert func in cdef, f"Missing function {func} in cdef"


@_skip_no_headers
class TestUmbrellaHeader:
    """Test that the umbrella header logic includes expected components."""

    @pytest.fixture(autouse=True)
    def _set_include_dir(self):
        old = os.environ.get("NNG_INCLUDE_DIR")
        os.environ["NNG_INCLUDE_DIR"] = _NNG_INCLUDE_DIR
        yield
        if old is None:
            os.environ.pop("NNG_INCLUDE_DIR", None)
        else:
            os.environ["NNG_INCLUDE_DIR"] = old

    def test_all_existing_headers_are_included(self):
        """Verify generate_cdef() output contains types/functions from all NNG headers."""
        from build_pynng import NNG_HEADERS, generate_cdef

        existing = [
            h
            for h in NNG_HEADERS
            if os.path.exists(os.path.join(_NNG_INCLUDE_DIR, h))
        ]
        assert len(existing) > 0, "No NNG headers found"

        # The actual test: verify that generate_cdef() produces output that
        # includes declarations from across the header set, not just nng.h.
        cdef, _ = generate_cdef()

        # Core nng.h types
        assert "nng_socket" in cdef, "Missing nng_socket from nng/nng.h"

        # Protocol-specific openers prove that protocol headers were included
        protocol_markers = {
            "nng/protocol/pair0/pair.h": "nng_pair0_open",
            "nng/protocol/pair1/pair.h": "nng_pair1_open",
            "nng/protocol/bus0/bus.h": "nng_bus0_open",
            "nng/protocol/reqrep0/req.h": "nng_req0_open",
            "nng/protocol/reqrep0/rep.h": "nng_rep0_open",
            "nng/protocol/pubsub0/pub.h": "nng_pub0_open",
            "nng/protocol/pubsub0/sub.h": "nng_sub0_open",
            "nng/protocol/pipeline0/push.h": "nng_push0_open",
            "nng/protocol/pipeline0/pull.h": "nng_pull0_open",
            "nng/protocol/survey0/survey.h": "nng_surveyor0_open",
            "nng/protocol/survey0/respond.h": "nng_respondent0_open",
        }
        for header, marker in protocol_markers.items():
            if header in existing:
                assert marker in cdef, (
                    f"Header {header} exists but {marker} missing from cdef"
                )

        # TLS header inclusion (if present)
        if "nng/supplemental/tls/tls.h" in existing:
            assert "nng_tls_config_alloc" in cdef, (
                "TLS header exists but nng_tls_config_alloc missing from cdef"
            )
