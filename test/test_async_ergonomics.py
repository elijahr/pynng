"""Tests for async ergonomic improvements to pynng.

Covers:
- __aiter__ / __anext__ on Socket and Context
- async with (aenter/aexit) on Socket and Context
- aclose() on Socket and Context
- get_running_loop() usage (implicitly tested by all asyncio tests)
- Defensive _aio_map.pop in _async_complete
"""

import asyncio
import unittest.mock

import pytest
import trio

import pynng
from pynng import _aio


# ---------------------------------------------------------------------------
# Socket: async for
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_socket_async_for_trio():
    """async for on a socket receives messages until socket is closed."""
    addr = "inproc://test-socket-aiter-trio"
    received = []

    listener = pynng.Push0(listen=addr, send_timeout=2000)
    puller = pynng.Pull0(dial=addr, recv_timeout=2000)
    try:
        async with trio.open_nursery() as nursery:
            async def send_messages():
                for i in range(3):
                    await listener.asend("msg{}".format(i).encode())
                # Close after sending all messages with a small delay
                # to ensure the puller has time to receive
                await trio.sleep(0.05)
                puller.close()

            nursery.start_soon(send_messages)

            async for msg in puller:
                received.append(msg)
    finally:
        puller.close()
        listener.close()

    assert len(received) == 3
    assert received[0] == b"msg0"
    assert received[1] == b"msg1"
    assert received[2] == b"msg2"


@pytest.mark.asyncio
async def test_socket_async_for_asyncio():
    """async for on a socket receives messages with asyncio backend."""
    addr = "inproc://test-socket-aiter-asyncio"
    received = []

    listener = pynng.Push0(listen=addr, send_timeout=2000)
    puller = pynng.Pull0(dial=addr, recv_timeout=2000)
    try:
        async def send_messages():
            for i in range(3):
                await listener.asend("msg{}".format(i).encode())
            await asyncio.sleep(0.05)
            puller.close()

        task = asyncio.ensure_future(send_messages())

        async for msg in puller:
            received.append(msg)

        await task
    finally:
        puller.close()
        listener.close()

    assert len(received) == 3
    assert received[0] == b"msg0"
    assert received[1] == b"msg1"
    assert received[2] == b"msg2"


@pytest.mark.trio
async def test_socket_async_for_stops_on_close_trio():
    """async for stops cleanly when socket is closed externally."""
    addr = "inproc://test-socket-aiter-close-trio"
    received = []

    pusher = pynng.Push0(listen=addr, send_timeout=2000)
    puller = pynng.Pull0(dial=addr, recv_timeout=5000)
    try:
        async with trio.open_nursery() as nursery:
            async def send_and_close():
                await pusher.asend(b"hello")
                await trio.sleep(0.1)
                puller.close()

            nursery.start_soon(send_and_close)

            async for msg in puller:
                received.append(msg)
    finally:
        puller.close()
        pusher.close()

    assert received == [b"hello"]


@pytest.mark.asyncio
async def test_socket_async_for_stops_on_close_asyncio():
    """async for stops cleanly when socket is closed externally (asyncio)."""
    addr = "inproc://test-socket-aiter-close-asyncio"
    received = []

    pusher = pynng.Push0(listen=addr, send_timeout=2000)
    puller = pynng.Pull0(dial=addr, recv_timeout=5000)
    try:
        async def send_and_close():
            await pusher.asend(b"hello")
            await asyncio.sleep(0.1)
            puller.close()

        task = asyncio.ensure_future(send_and_close())

        async for msg in puller:
            received.append(msg)

        await task
    finally:
        puller.close()
        pusher.close()

    assert received == [b"hello"]


# ---------------------------------------------------------------------------
# Socket: async with
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_socket_async_with_trio():
    """async with on a socket closes it on exit."""
    addr = "inproc://test-socket-acm-trio"
    async with pynng.Pair0(listen=addr, recv_timeout=1000) as s:
        assert isinstance(s, pynng.Socket)
        async with pynng.Pair0(dial=addr, send_timeout=1000) as d:
            await d.asend(b"hi")
            assert await s.arecv() == b"hi"
    # After exiting, socket should be closed (listeners cleared)
    assert len(s._listeners) == 0


@pytest.mark.asyncio
async def test_socket_async_with_asyncio():
    """async with on a socket closes it on exit with asyncio."""
    addr = "inproc://test-socket-acm-asyncio"
    async with pynng.Pair0(listen=addr, recv_timeout=1000) as s:
        assert isinstance(s, pynng.Socket)
        async with pynng.Pair0(dial=addr, send_timeout=1000) as d:
            await d.asend(b"hi")
            assert await s.arecv() == b"hi"
    # After exiting, socket should be closed (listeners cleared)
    assert len(s._listeners) == 0


@pytest.mark.trio
async def test_socket_async_with_cleans_up_on_exception_trio():
    """async with on a socket closes it even if an exception occurs."""
    addr = "inproc://test-socket-acm-exc-trio"
    with pytest.raises(RuntimeError, match="intentional"):
        async with pynng.Pair0(listen=addr) as s:
            raise RuntimeError("intentional")
    assert len(s._listeners) == 0


@pytest.mark.asyncio
async def test_socket_async_with_cleans_up_on_exception_asyncio():
    """async with on a socket closes it even if an exception occurs."""
    addr = "inproc://test-socket-acm-exc-asyncio"
    with pytest.raises(RuntimeError, match="intentional"):
        async with pynng.Pair0(listen=addr) as s:
            raise RuntimeError("intentional")
    assert len(s._listeners) == 0


# ---------------------------------------------------------------------------
# Socket: aclose
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_socket_aclose_trio():
    """aclose() closes the socket."""
    addr = "inproc://test-socket-aclose-trio"
    s = pynng.Pair0(listen=addr)
    assert len(s.listeners) == 1
    await s.aclose()
    assert len(s._listeners) == 0


@pytest.mark.asyncio
async def test_socket_aclose_asyncio():
    """aclose() closes the socket with asyncio."""
    addr = "inproc://test-socket-aclose-asyncio"
    s = pynng.Pair0(listen=addr)
    assert len(s.listeners) == 1
    await s.aclose()
    assert len(s._listeners) == 0


# ---------------------------------------------------------------------------
# Context: async for
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_context_async_for_trio():
    """async for on a context receives messages."""
    addr = "inproc://test-ctx-aiter-trio"
    received = []
    with pynng.Rep0(listen=addr, recv_timeout=2000) as rep_sock, \
         pynng.Req0(dial=addr, recv_timeout=2000) as req_sock:
        ctx_rep = rep_sock.new_context()
        ctx_req = req_sock.new_context()

        # Send a request so rep can receive it
        await ctx_req.asend(b"request1")

        # Use async for on the rep context (just one iteration, then break)
        async for msg in ctx_rep:
            received.append(msg)
            # Send response so req/rep cycle completes
            await ctx_rep.asend(b"response1")
            break

        resp = await ctx_req.arecv()
        assert resp == b"response1"

        ctx_rep.close()
        ctx_req.close()

    assert received == [b"request1"]


@pytest.mark.asyncio
async def test_context_async_for_asyncio():
    """async for on a context receives messages with asyncio."""
    addr = "inproc://test-ctx-aiter-asyncio"
    received = []
    with pynng.Rep0(listen=addr, recv_timeout=2000) as rep_sock, \
         pynng.Req0(dial=addr, recv_timeout=2000) as req_sock:
        ctx_rep = rep_sock.new_context()
        ctx_req = req_sock.new_context()

        await ctx_req.asend(b"request1")

        async for msg in ctx_rep:
            received.append(msg)
            await ctx_rep.asend(b"response1")
            break

        resp = await ctx_req.arecv()
        assert resp == b"response1"

        ctx_rep.close()
        ctx_req.close()

    assert received == [b"request1"]


@pytest.mark.trio
async def test_context_async_for_stops_on_close_trio():
    """async for on a context stops when the parent socket is closed."""
    addr = "inproc://test-ctx-aiter-close-trio"
    received = []

    rep_sock = pynng.Rep0(listen=addr, recv_timeout=5000)
    req_sock = pynng.Req0(dial=addr, send_timeout=2000)
    try:
        ctx = rep_sock.new_context()

        async with trio.open_nursery() as nursery:
            async def send_and_close():
                await req_sock.asend(b"msg")
                await trio.sleep(0.1)
                # Closing the parent socket causes the context's arecv to get
                # a Closed exception, which stops async iteration.
                rep_sock.close()

            nursery.start_soon(send_and_close)

            async for msg in ctx:
                received.append(msg)
    finally:
        req_sock.close()
        rep_sock.close()

    assert received == [b"msg"]


@pytest.mark.asyncio
async def test_context_async_for_stops_on_close_asyncio():
    """async for on a context stops when the parent socket is closed (asyncio)."""
    addr = "inproc://test-ctx-aiter-close-asyncio"
    received = []

    rep_sock = pynng.Rep0(listen=addr, recv_timeout=5000)
    req_sock = pynng.Req0(dial=addr, send_timeout=2000)
    try:
        ctx = rep_sock.new_context()

        async def send_and_close():
            await req_sock.asend(b"msg")
            await asyncio.sleep(0.1)
            # Closing the parent socket causes the context's arecv to get
            # a Closed exception, which stops async iteration.
            rep_sock.close()

        task = asyncio.ensure_future(send_and_close())

        async for msg in ctx:
            received.append(msg)

        await task
    finally:
        req_sock.close()
        rep_sock.close()

    assert received == [b"msg"]


# ---------------------------------------------------------------------------
# Context: async with
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_context_async_with_trio():
    """async with on a context closes it on exit."""
    addr = "inproc://test-ctx-acm-trio"
    with pynng.Req0(listen=addr, recv_timeout=1000) as req_sock, \
         pynng.Rep0(dial=addr, recv_timeout=1000) as rep_sock:
        async with req_sock.new_context() as ctx_req:
            assert isinstance(ctx_req, pynng.Context)
            async with rep_sock.new_context() as ctx_rep:
                await ctx_req.asend(b"hello")
                assert await ctx_rep.arecv() == b"hello"
                await ctx_rep.asend(b"world")
                assert await ctx_req.arecv() == b"world"
            # ctx_rep should be closed now
            assert ctx_rep._context is None


@pytest.mark.asyncio
async def test_context_async_with_asyncio():
    """async with on a context closes it on exit with asyncio."""
    addr = "inproc://test-ctx-acm-asyncio"
    with pynng.Req0(listen=addr, recv_timeout=1000) as req_sock, \
         pynng.Rep0(dial=addr, recv_timeout=1000) as rep_sock:
        async with req_sock.new_context() as ctx_req:
            assert isinstance(ctx_req, pynng.Context)
            async with rep_sock.new_context() as ctx_rep:
                await ctx_req.asend(b"hello")
                assert await ctx_rep.arecv() == b"hello"
                await ctx_rep.asend(b"world")
                assert await ctx_req.arecv() == b"world"
            # ctx_rep should be closed now
            assert ctx_rep._context is None


# ---------------------------------------------------------------------------
# Context: aclose
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_context_aclose_trio():
    """aclose() closes the context."""
    with pynng.Req0() as s:
        ctx = s.new_context()
        assert ctx._context is not None
        await ctx.aclose()
        assert ctx._context is None


@pytest.mark.asyncio
async def test_context_aclose_asyncio():
    """aclose() closes the context with asyncio."""
    with pynng.Req0() as s:
        ctx = s.new_context()
        assert ctx._context is not None
        await ctx.aclose()
        assert ctx._context is None


# ---------------------------------------------------------------------------
# Defensive _aio_map.pop
# ---------------------------------------------------------------------------

def test_aio_map_pop_defensive():
    """_async_complete does not raise if callback id is not in _aio_map.

    This tests the defensive pop(id, None) behavior. We simulate calling the
    callback with a void* that has no corresponding entry.
    """
    from pynng._nng import ffi, lib

    # Create a fake void* pointer that maps to an id not in _aio_map
    fake_id = 9999999999
    void_p = ffi.cast("void *", fake_id)

    # Ensure this id is NOT in the map
    _aio._aio_map.pop(fake_id, None)

    # This should not raise (before the fix, it would KeyError)
    lib._async_complete(void_p)


# ---------------------------------------------------------------------------
# get_running_loop verification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_asyncio_uses_running_loop():
    """Verify asyncio_helper calls get_running_loop (not get_event_loop).

    Patches get_event_loop at the pynng._aio module level to raise if called,
    ensuring that the code path uses get_running_loop instead.
    """
    addr = "inproc://test-running-loop"
    with unittest.mock.patch.object(
        _aio.asyncio,
        "get_event_loop",
        side_effect=AssertionError("get_event_loop should not be called"),
    ):
        with pynng.Pair0(listen=addr, recv_timeout=1000) as listener, \
             pynng.Pair0(dial=addr, send_timeout=1000) as dialer:
            await dialer.asend(b"running-loop-test")
            result = await listener.arecv()
            assert result == b"running-loop-test"
