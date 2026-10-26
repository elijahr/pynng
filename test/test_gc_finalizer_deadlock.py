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

_DEVICE = """
import asyncio
import gc
import importlib
import sys
import threading
import time
import weakref

from pynng import _aio

pynng = importlib.import_module(sys.argv[1])


collected = []


class DeviceAios(set):
    def add(self, aio):
        collected.append(gc.collect())
        super().add(aio)

    def discard(self, aio):
        collected.append(gc.collect())
        super().discard(aio)


class GarbageDeviceAIO(_aio.DeviceAIO):
    __slots__ = ("__weakref__",)


close_events = []
garbage_aios = []


def make_garbage(sock1, sock2):
    s = pynng.Pair0()
    s.cycle = s
    close_events.append(s._close_done)
    box = [GarbageDeviceAIO(sock1, sock2, "asyncio")]
    box.append(box)
    garbage_aios.append(weakref.ref(box[0]))


def run_device(rep, req):
    try:
        pynng.device(rep, req)
    except pynng.Closed:
        pass


async def main():
    rep = pynng.RawRep0()
    req = pynng.RawReq0()
    rep._device_aios = DeviceAios()
    idle1 = pynng.RawRep0()
    idle2 = pynng.RawReq0()
    make_garbage(idle1, idle2)
    device = threading.Thread(target=run_device, args=(rep, req))
    device.start()
    deadline = time.monotonic() + 30
    while not rep._device_aios:
        assert time.monotonic() < deadline, "device did not start"
        time.sleep(0.01)
    make_garbage(idle1, idle2)
    rep.close()
    device.join()
    for t in threading.enumerate():
        if t.name in ("pynng-close", "pynng-device-free"):
            t.join()
    assert len(collected) == 2 and min(collected) > 0
    gc.collect()
    assert all(e.is_set() for e in close_events)
    assert all(r() is None for r in garbage_aios)
    req.close()
    idle1.close()
    idle2.close()


gc.disable()
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


@pytest.mark.parametrize("module", ["pynng", "pynng.v2"])
def test_finalizers_during_device_start_and_stop(module):
    _run(_DEVICE, module)


_DEVICE_AT_EXIT = """
import asyncio
import importlib
import sys

from pynng._aio import DeviceAIO

pynng = importlib.import_module(sys.argv[1])
lib = importlib.import_module(sys.argv[2])

a = pynng.Pair0(listen="inproc://device-at-exit-a")
b = pynng.Pair0(listen="inproc://device-at-exit-b")


async def main():
    global dev
    dev = DeviceAIO(a, b, "asyncio", _default_lib=lib.lib, _default_ffi=lib.ffi)


asyncio.run(main())
"""


@pytest.mark.parametrize(
    "module, nng", [("pynng", "pynng._nng"), ("pynng.v2", "pynng._nng_v2")]
)
def test_device_aio_freed_at_interpreter_exit(module, nng):
    proc = subprocess.run(
        [sys.executable, "-c", _DEVICE_AT_EXIT, module, nng],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
