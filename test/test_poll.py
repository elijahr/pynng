"""
Unit tests for non-Windows recv_fd event loop polling optimization.
"""

import asyncio
import os
import pytest
import trio

import pynng
from conftest import random_addr


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
def test_can_use_recv_fd():
    from pynng._poll import can_use_recv_fd

    addr = random_addr()
    with pynng.Pair0(listen=addr) as s:
        assert can_use_recv_fd(s) is True

    # Closed socket cannot use recv_fd
    assert can_use_recv_fd(s) is False

    # Context cannot use recv_fd
    with pynng.Req0(listen=addr) as req:
        with req.new_context() as ctx:
            assert can_use_recv_fd(ctx) is False


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
@pytest.mark.asyncio
async def test_recv_fd_asyncio_roundtrip():
    addr = random_addr()
    with pynng.Pair0(listen=addr) as s1, pynng.Pair0(dial=addr) as s2:
        for i in range(5):
            await s1.asend(f"msg-{i}".encode())
            msg = await s2.arecv()
            assert msg == f"msg-{i}".encode()


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
@pytest.mark.asyncio
async def test_recv_fd_asyncio_buffered_drain():
    addr = random_addr()
    with pynng.Pair0(listen=addr, send_buffer_size=16) as s1, pynng.Pair0(
        dial=addr, recv_buffer_size=16
    ) as s2:
        for i in range(8):
            await s1.asend(f"buf-{i}".encode())

        recvd = []
        for _ in range(8):
            recvd.append(await s2.arecv())
        assert recvd == [f"buf-{i}".encode() for i in range(8)]


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
@pytest.mark.asyncio
async def test_recv_fd_asyncio_arecv_into():
    addr = random_addr()
    with pynng.Pair0(listen=addr) as s1, pynng.Pair0(dial=addr) as s2:
        await s1.asend(b"hello-into")
        buf = bytearray(20)
        n = await s2.arecv_into(buf)
        assert n == len(b"hello-into")
        assert bytes(buf[:n]) == b"hello-into"


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
@pytest.mark.asyncio
async def test_recv_fd_asyncio_timeout():
    addr = random_addr()
    with pynng.Pair0(listen=addr, recv_timeout=50) as s:
        with pytest.raises(pynng.Timeout):
            await s.arecv()


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
@pytest.mark.asyncio
async def test_recv_fd_asyncio_close_unblocks_waiter():
    addr = random_addr()
    s = pynng.Pair0(listen=addr)

    async def close_soon():
        await asyncio.sleep(0.05)
        s.close()

    asyncio.create_task(close_soon())
    with pytest.raises(pynng.Closed):
        await s.arecv()


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
@pytest.mark.asyncio
async def test_recv_fd_asyncio_cancellation():
    addr = random_addr()
    with pynng.Pair0(listen=addr) as s:
        task = asyncio.create_task(s.arecv())
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
@pytest.mark.asyncio
async def test_recv_fd_asyncio_concurrent_readers():
    addr = random_addr()
    with pynng.Pair0(listen=addr, send_buffer_size=16) as s1, pynng.Pair0(
        dial=addr, recv_buffer_size=16
    ) as s2:
        for i in range(5):
            await s1.asend(f"conc-{i}".encode())

        results = await asyncio.gather(*(s2.arecv() for _ in range(5)))
        assert sorted(results) == [f"conc-{i}".encode() for i in range(5)]


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
@pytest.mark.trio
async def test_recv_fd_trio_roundtrip():
    addr = random_addr()
    with pynng.Pair0(listen=addr) as s1, pynng.Pair0(dial=addr) as s2:
        for i in range(5):
            await s1.asend(f"trio-{i}".encode())
            msg = await s2.arecv()
            assert msg == f"trio-{i}".encode()


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
@pytest.mark.trio
async def test_recv_fd_trio_timeout():
    addr = random_addr()
    with pynng.Pair0(listen=addr, recv_timeout=50) as s:
        with pytest.raises(pynng.Timeout):
            await s.arecv()


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
@pytest.mark.asyncio
async def test_recv_fd_v2_asyncio():
    from pynng import v2

    addr = random_addr()
    with v2.Pair0(listen=addr) as s1, v2.Pair0(dial=addr) as s2:
        await s1.asend(b"v2-recvfd")
        msg = await s2.arecv()
        assert msg == b"v2-recvfd"


@pytest.mark.skipif(os.name == "nt", reason="recv_fd optimization is POSIX only")
def test_recv_fd_sequential_event_loops():
    """Verify socket can be used across separate asyncio.run() event loops."""
    addr = random_addr()
    with pynng.Pair0(listen=addr) as s1, pynng.Pair0(dial=addr) as s2:
        async def step1():
            await s1.asend(b"loop1")
            return await s2.arecv()

        async def step2():
            await s1.asend(b"loop2")
            return await s2.arecv()

        res1 = asyncio.run(step1())
        res2 = asyncio.run(step2())
        assert res1 == b"loop1"
        assert res2 == b"loop2"
