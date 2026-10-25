"""A collection that runs a finalizer in the middle of a registry update.

A cyclic collection can run on any thread at any bytecode boundary, also while
that thread is inside pynng code. If the finalizer of an unreachable object
then takes a lock that the interrupted code holds, the thread deadlocks on
itself. Each script forces the collection at the registry update, so a
deadlock is a timeout instead of an intermittent hang.
"""

import subprocess
import sys

import pytest

_SOCKET_REGISTRY = """
import gc
import importlib
import sys
import weakref

from pynng import _base

pynng = importlib.import_module(sys.argv[1])


class Registry(dict):
    def __setitem__(self, key, value):
        gc.collect()
        super().__setitem__(key, value)

    def get(self, key, default=None):
        gc.collect()
        return super().get(key, default)


def unclosed_garbage_socket():
    s = pynng.Pair0()
    s.cycle = s
    return weakref.ref(s)


gc.disable()
_base._active_handles = Registry(_base._active_handles)
garbage = unclosed_garbage_socket()
s = pynng.Pair0()
assert garbage() is None
garbage = unclosed_garbage_socket()
s.close()
assert garbage() is None
print("NO_DEADLOCK")
"""

_AIO_MAP = """
import asyncio
import gc

import pynng
from pynng import _aio


class AioMap(dict):
    def __setitem__(self, key, value):
        gc.collect()
        super().__setitem__(key, value)

    def pop(self, key, default=None):
        gc.collect()
        return super().pop(key, default)


def unfreed_garbage_aio(sock):
    box = [_aio.AIOHelper(sock, "asyncio", _use_mpsc=False)]
    box.append(box)
    return id(box[0].cb_arg)


async def main():
    with pynng.Pair0() as sock:
        garbage = unfreed_garbage_aio(sock)
        aio = _aio.AIOHelper(sock, "asyncio", _use_mpsc=False)
        assert garbage not in _aio._aio_map
        garbage = unfreed_garbage_aio(sock)
        aio._free()
        assert garbage not in _aio._aio_map


gc.disable()
_aio._aio_map = AioMap(_aio._aio_map)
asyncio.run(main())
print("NO_DEADLOCK")
"""


def _run(code, *args):
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("deadlock: a finalizer blocked on a lock its thread held")
    assert proc.returncode == 0, proc.stderr
    assert "NO_DEADLOCK" in proc.stdout


@pytest.mark.parametrize("module", ["pynng", "pynng.v2"])
def test_socket_finalizer_during_registry_update(module):
    _run(_SOCKET_REGISTRY, module)


def test_aio_finalizer_during_aio_map_update():
    _run(_AIO_MAP)
