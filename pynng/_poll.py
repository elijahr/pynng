"""
Non-Windows async receive polling using socket recv_fd.

Provides high-throughput, low-latency async message reception by directly
polling the socket's receive file descriptor (recv_fd) with the native
event loop selector (epoll/kqueue) on POSIX platforms, bypassing C thread pool
callbacks and self-pipe context switches.
"""

import asyncio
import os
import time

import sniffio

from .exceptions import Closed, Timeout, TryAgain


def can_use_recv_fd(sock):
    """Determine whether sock can use the recv_fd event loop optimization.

    Requirements:
    - POSIX platform (os.name != 'nt')
    - Object is a Socket (not a Context; contexts do not have recv_fd)
    - Socket has valid recv_fd attribute that returns a non-negative integer
    - Socket is not closed
    """
    if os.name == "nt":
        return False
    from ._base import Socket, Context

    if not isinstance(sock, Socket) or isinstance(sock, Context):
        return False
    # nng surveyor protocol blocks synchronously inside nng_recvmsg even with
    # non-blocking flag until survey_time elapses; surveyor must use AIOHelper.
    if hasattr(sock, "survey_time"):
        return False
    if getattr(sock, "_socket_closed", False):
        return False
    try:
        fd = sock.recv_fd
        return isinstance(fd, int) and fd >= 0
    except Exception:
        return False


def _get_timeout_s(sock):
    """Calculate effective timeout in seconds from socket options."""
    timeout_ms = sock.recv_timeout
    if hasattr(sock, "survey_time"):
        st = sock.survey_time
        if st is not None and st >= 0:
            if timeout_ms is None or timeout_ms < 0:
                timeout_ms = st
            else:
                timeout_ms = min(timeout_ms, st)
    if timeout_ms is not None and timeout_ms >= 0:
        return timeout_ms / 1000.0
    return None


async def _arecv_msg_asyncio(sock, fd, timeout_s):
    """Receive next message using asyncio loop.add_reader on recv_fd."""
    loop = asyncio.get_running_loop()

    # Lazy-initialize per-socket asyncio lock to serialize concurrent readers
    if not hasattr(sock, "_async_recv_lock") or sock._async_recv_lock is None:
        sock._async_recv_lock = asyncio.Lock()

    async with sock._async_recv_lock:
        deadline = (time.monotonic() + timeout_s) if timeout_s is not None else None

        while True:
            # Check if socket was closed while waiting for lock
            if getattr(sock, "_socket_closed", False):
                raise Closed("Socket closed", 2)

            # Opportunistic non-blocking receive
            try:
                return sock.recv_msg(block=False)
            except (TryAgain, Timeout):
                pass

            now = time.monotonic()
            if deadline is not None and now >= deadline:
                raise Timeout("Timed out", 5)

            remaining_s = (deadline - now) if deadline is not None else None

            fut = loop.create_future()
            if not hasattr(sock, "_async_recv_waiters") or sock._async_recv_waiters is None:
                sock._async_recv_waiters = set()
            sock._async_recv_waiters.add(fut)

            def _on_readable():
                if not fut.done():
                    fut.set_result(None)

            loop.add_reader(fd, _on_readable)
            try:
                if remaining_s is not None:
                    if hasattr(asyncio, "timeout"):
                        async with asyncio.timeout(remaining_s):
                            await fut
                    else:
                        await asyncio.wait_for(asyncio.shield(fut), timeout=remaining_s)
                else:
                    await fut
            except (TimeoutError, asyncio.TimeoutError):
                raise Timeout("Timed out", 5)
            finally:
                try:
                    loop.remove_reader(fd)
                except Exception:
                    pass
                sock._async_recv_waiters.discard(fut)


async def _arecv_msg_trio(sock, fd, timeout_s):
    """Receive next message using trio wait_readable on recv_fd."""
    import trio

    if not hasattr(sock, "_trio_recv_lock") or sock._trio_recv_lock is None:
        sock._trio_recv_lock = trio.Lock()

    async with sock._trio_recv_lock:
        deadline = (time.monotonic() + timeout_s) if timeout_s is not None else None

        while True:
            if getattr(sock, "_socket_closed", False):
                raise Closed("Socket closed", 2)

            try:
                return sock.recv_msg(block=False)
            except (TryAgain, Timeout):
                pass

            now = time.monotonic()
            if deadline is not None and now >= deadline:
                raise Timeout("Timed out", 5)

            remaining_s = (deadline - now) if deadline is not None else None
            try:
                with trio.CancelScope() as cancel_scope:
                    waiter = (cancel_scope, trio.lowlevel.current_trio_token())
                    if not hasattr(sock, "_trio_recv_waiters") or sock._trio_recv_waiters is None:
                        sock._trio_recv_waiters = set()
                    sock._trio_recv_waiters.add(waiter)
                    try:
                        if remaining_s is not None:
                            with trio.fail_after(remaining_s):
                                await trio.lowlevel.wait_readable(fd)
                        else:
                            await trio.lowlevel.wait_readable(fd)
                    finally:
                        sock._trio_recv_waiters.discard(waiter)

                if getattr(sock, "_socket_closed", False):
                    raise Closed("Socket closed", 2)
            except trio.TooSlowError:
                raise Timeout("Timed out", 5)


async def arecv_msg_recvfd(sock):
    """Receive a Message using recv_fd polling.

    Dispatches to the running async framework (asyncio or trio).
    """
    fd = sock.recv_fd
    timeout_s = _get_timeout_s(sock)

    backend = sock._async_backend
    if backend is None:
        backend = sniffio.current_async_library()

    if backend == "trio":
        return await _arecv_msg_trio(sock, fd, timeout_s)
    return await _arecv_msg_asyncio(sock, fd, timeout_s)
