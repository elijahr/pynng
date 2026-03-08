"""Shared test fixtures and configuration for pynng tests."""
import pytest

# Standard timeout values (ms) to prevent infinite hangs
FAST_TIMEOUT = 500     # For inproc operations
MEDIUM_TIMEOUT = 3000  # For TCP/IPC operations
SLOW_TIMEOUT = 10000   # For TLS and slow protocols

_addr_counter = 0


def unique_inproc_addr():
    """Generate a unique inproc address to prevent test interference."""
    global _addr_counter
    _addr_counter += 1
    return f"inproc://test-{_addr_counter}"
