"""Shared test fixtures and configuration for pynng tests."""
import pytest

# Standard timeout values (ms) to prevent infinite hangs
FAST_TIMEOUT = 500     # For inproc operations
MEDIUM_TIMEOUT = 3000  # For TCP/IPC operations
SLOW_TIMEOUT = 10000   # For TLS and slow protocols

_addr_counter = 0


def _unique_inproc_addr():
    """Generate a unique inproc address to prevent test interference."""
    global _addr_counter
    _addr_counter += 1
    return f"inproc://test-{_addr_counter}"


# Keep the module-level function for backward compatibility
unique_inproc_addr = _unique_inproc_addr


def _v2_available():
    """Check whether the v2 CFFI extension is importable."""
    try:
        import pynng._nng_v2  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture(params=[
    "v1",
    pytest.param("v2", marks=pytest.mark.nng_v2),
])
def nng(request):
    """Provide either ``pynng`` (v1) or ``pynng.v2`` module.

    Tests using this fixture run once per version. The v2 parametrization
    is skipped when the ``_nng_v2`` extension is not installed.
    """
    if request.param == "v2":
        pytest.importorskip("pynng._nng_v2")
        import pynng.v2 as mod
        return mod
    else:
        import pynng as mod
        return mod


@pytest.fixture
def inproc_addr():
    """Return a unique inproc address for the current test."""
    return _unique_inproc_addr()
