"""
v2-specific CFFI callbacks for async I/O and pipe notifications.

These are structurally identical to the v1 callbacks in ``pynng._aio`` and
``pynng.nng``, but are bound to the v2 CFFI module (``pynng._nng_v2``).

The callbacks share the same Python-side dispatch data structures as v1:

- ``_aio_map`` / ``_aio_map_lock`` from ``pynng._aio``  (keyed by ``id()``,
  so v1/v2 AIO objects cannot collide).
- ``_active_handles`` / ``_active_handles_lock`` from ``pynng._base`` (keyed
  by ``(version_tag, socket_id)`` tuples, preventing v1/v2 collision).
"""

import logging

from pynng._nng_v2 import ffi, lib
from pynng._aio import _aio_map, _aio_map_lock
from pynng._base import (
    _active_handles,
    _active_handles_lock,
    _do_callbacks,
)

logger = logging.getLogger(__name__)


@ffi.def_extern()
def _async_complete(void_p):
    """
    Callback provided to nng_aio_alloc for v2 async operations.

    Looks up and invokes the rescheduler stored in ``_aio_map``.
    """
    assert isinstance(void_p, ffi.CData)
    id_val = int(ffi.cast("size_t", void_p))

    with _aio_map_lock:
        rescheduler = _aio_map.pop(id_val, None)
    if rescheduler is None:
        return
    rescheduler()


@ffi.def_extern()
def _nng_pipe_cb(lib_pipe, event, arg):
    """
    Pipe notification callback for v2 sockets.

    Dispatches to the Socket's pipe callback lists, identical to the v1
    version but using the v2 ffi for handle resolution.
    """
    logger.debug("v2 pipe callback event {}".format(event))

    if arg == ffi.NULL:
        logger.info(
            "v2 pipe callback fired with invalid handle (socket likely GC'd); ignoring"
        )
        return

    arg_ptr = int(ffi.cast("uintptr_t", arg))
    with _active_handles_lock:
        ref = _active_handles.get(arg_ptr)
        sock = ref() if ref is not None else None

    if sock is None:
        logger.info(
            "v2 pipe callback fired with invalid handle (socket likely GC'd); ignoring"
        )
        return

    # Snapshot callbacks under lock, then invoke outside lock to prevent deadlock
    callbacks = None
    pipe = None
    remove_pipe_on_finally = False

    with sock._pipe_notify_lock:
        pipe_id = lib.nng_pipe_id(lib_pipe)
        if event == lib.NNG_PIPE_EV_ADD_PRE:
            pipe = sock._add_pipe(lib_pipe)
            callbacks = list(sock._on_pre_pipe_add)
        elif event == lib.NNG_PIPE_EV_ADD_POST:
            pipe = sock._add_pipe(lib_pipe)
            callbacks = list(sock._on_post_pipe_add)
        elif event == lib.NNG_PIPE_EV_REM_POST:
            try:
                pipe = sock._pipes[pipe_id]
            except KeyError:
                logger.debug("Could not find pipe for v2 socket")
                return
            callbacks = list(sock._on_post_pipe_remove)
            remove_pipe_on_finally = True

    try:
        if callbacks and pipe:
            _do_callbacks(pipe, callbacks)
    finally:
        if remove_pipe_on_finally:
            with sock._pipe_notify_lock:
                sock._remove_pipe(lib_pipe)
        elif event == lib.NNG_PIPE_EV_ADD_PRE and pipe and pipe.closed:
            with sock._pipe_notify_lock:
                sock._remove_pipe(lib_pipe)
