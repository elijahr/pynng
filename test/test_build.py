"""Tests for the CFFI generation pipeline in build_pynng.py.

Validates that excluded patterns are properly filtered from the generated
FFI bindings.

These tests operate on the already-compiled _nng module to verify the end
result of the build pipeline.
"""

import os
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
