import gc
import platform
import time

import pytest
import trio

from _test_util import wait_pipe_len
from conftest import unique_inproc_addr


def test_dialers_get_added(nng):
    addr = unique_inproc_addr()
    addr2 = unique_inproc_addr()
    with nng.Pair0() as s:
        assert len(s.dialers) == 0
        s.dial(addr, block=False)
        assert len(s.dialers) == 1
        s.dial(addr2, block=False)
        assert len(s.dialers) == 2


def test_listeners_get_added(nng):
    addr = unique_inproc_addr()
    addr2 = unique_inproc_addr()
    with nng.Pair0() as s:
        assert len(s.listeners) == 0
        s.listen(addr)
        assert len(s.listeners) == 1
        s.listen(addr2)
        assert len(s.listeners) == 2


def test_closing_listener_works(nng):
    addr = unique_inproc_addr()
    with nng.Pair0(listen=addr) as s:
        assert len(s.listeners) == 1
        s.listeners[0].close()
        assert len(s.listeners) == 0
        # if the listener is really closed, we should be able to listen at the
        # same address again; we'll sleep a little so OS X CI will pass.
        time.sleep(0.01)
        s.listen(addr)
        assert len(s.listeners) == 1
    assert len(s.listeners) == 0


def test_closing_dialer_works(nng):
    addr = unique_inproc_addr()
    with nng.Pair0(dial=addr, block_on_dial=False) as s:
        assert len(s.dialers) == 1
        s.dialers[0].close()
        assert len(s.dialers) == 0


def test_nonblocking_recv_works(nng):
    addr = unique_inproc_addr()
    with nng.Pair0(listen=addr) as s:
        with pytest.raises(nng.TryAgain):
            s.recv(block=False)


def test_nonblocking_send_works(nng):
    addr = unique_inproc_addr()
    with nng.Pair0(listen=addr) as s:
        with pytest.raises(nng.TryAgain):
            s.send(b"sad message, never will be seen", block=False)


@pytest.mark.trio
async def test_context(nng):
    addr = unique_inproc_addr()
    with nng.Req0(listen=addr, recv_timeout=1000) as req_sock, nng.Rep0(
        dial=addr, recv_timeout=1000
    ) as rep_sock:
        with req_sock.new_context() as req, rep_sock.new_context() as rep:
            request = b"i am requesting"
            await req.asend(request)
            assert await rep.arecv() == request

            response = b"i am responding"
            await rep.asend(response)
            assert await req.arecv() == response

            with pytest.raises(nng.BadState):
                await req.arecv()

            # responders can't send before receiving
            with pytest.raises(nng.BadState):
                await rep.asend(b"I cannot do this why am I trying")


@pytest.mark.trio
async def test_multiple_contexts(nng):
    addr = unique_inproc_addr()

    async def recv_and_send(ctx):
        data = await ctx.arecv()
        await trio.sleep(0.05)
        await ctx.asend(data)

    with nng.Rep0(listen=addr, recv_timeout=500) as rep, nng.Req0(
        dial=addr, recv_timeout=500
    ) as req1, nng.Req0(dial=addr, recv_timeout=500) as req2:
        async with trio.open_nursery() as n:
            ctx1, ctx2 = [rep.new_context() for _ in range(2)]
            with ctx1, ctx2:
                n.start_soon(recv_and_send, ctx1)
                n.start_soon(recv_and_send, ctx2)

                await req1.asend(b"oh hi")
                await req2.asend(b"me toooo")
                assert await req1.arecv() == b"oh hi"
                assert await req2.arecv() == b"me toooo"


def test_synchronous_recv_context(nng):
    addr = unique_inproc_addr()
    with nng.Rep0(listen=addr, recv_timeout=500) as rep, nng.Req0(
        dial=addr, recv_timeout=500
    ) as req:
        req.send(b"oh hello there old pal")
        assert rep.recv() == b"oh hello there old pal"
        rep.send(b"it is so good to hear from you")
        assert req.recv() == b"it is so good to hear from you"


def test_pair1_polyamorousness(nng):
    addr = unique_inproc_addr()
    with nng.Pair1(
        listen=addr, polyamorous=True, recv_timeout=500
    ) as s0, nng.Pair1(dial=addr, polyamorous=True, recv_timeout=500) as s1:
        wait_pipe_len(s0, 1)
        # pipe for s1 .
        p1 = s0.pipes[0]
        with nng.Pair1(dial=addr, polyamorous=True, recv_timeout=500) as s2:
            wait_pipe_len(s0, 2)
            # pipes is backed by a dict, so we can't rely on order in
            # Python 3.5.
            pipes = s0.pipes
            p2 = pipes[1]
            if p2 is p1:
                p2 = pipes[0]
            p1.send(b"hello s1")
            assert s1.recv() == b"hello s1"

            p2.send(b"hello there s2")
            assert s2.recv() == b"hello there s2"


@pytest.mark.skipif(
    platform.python_implementation() == "PyPy",
    reason="Sub0 topic filtering has issues on PyPy wheels"
)
def test_sub_sock_options(nng):
    addr = unique_inproc_addr()
    with nng.Pub0(listen=addr) as pub:
        # test single option topic
        with nng.Sub0(dial=addr, topics="beep", recv_timeout=1500) as sub:
            wait_pipe_len(sub, 1)
            wait_pipe_len(pub, 1)
            pub.send(b"beep hi")
            assert sub.recv() == b"beep hi"
        with nng.Sub0(dial=addr, topics=["beep", "hello"], recv_timeout=500) as sub:
            wait_pipe_len(sub, 1)
            wait_pipe_len(pub, 1)
            pub.send(b"beep hi")
            assert sub.recv() == b"beep hi"
            pub.send(b"hello there")
            assert sub.recv() == b"hello there"


def test_send_str_raises_valueerror(nng):
    addr = unique_inproc_addr()
    with nng.Pair0(listen=addr) as s:
        with pytest.raises(ValueError, match="Cannot send type str"):
            s.send("forgot to encode")


@pytest.mark.skipif(
    platform.python_implementation() == "PyPy",
    reason="PyPy GC does not guarantee __del__ timing"
)
@pytest.mark.nng_v1
def test_socket_del_after_bad_init():
    """v1-only: tests pynng.Socket() directly."""
    import pynng
    try:
        pynng.Socket()
    except Exception:
        pass
    gc.collect()  # should not raise


def test_context_del_after_socket_close(nng):
    s = nng.Req0()
    ctx = s.new_context()
    s.close()
    del ctx
    gc.collect()  # should not raise or SEGFAULT


@pytest.mark.nng_v1
def test_tls_config_del_after_init_failure():
    """v1-only: TLSConfig constructor validation test."""
    import pynng
    with pytest.raises(ValueError):
        pynng.TLSConfig(
            pynng.TLSConfig.MODE_CLIENT,
            ca_string="dummy",
            ca_files=["dummy"],
        )
    gc.collect()  # should not raise AttributeError


@pytest.mark.skipif(
    platform.python_implementation() == "PyPy",
    reason="Sub0 topic filtering has issues on PyPy wheels"
)
def test_sub_unsubscribe(nng):
    addr = unique_inproc_addr()
    with nng.Pub0(listen=addr) as pub, \
         nng.Sub0(dial=addr, topics="beep", recv_timeout=500) as sub:
        wait_pipe_len(sub, 1)
        wait_pipe_len(pub, 1)
        sub.unsubscribe("beep")
        pub.send(b"beep should not arrive")
        with pytest.raises(nng.Timeout):
            sub.recv()


def test_remove_pipe_callbacks(nng):
    with nng.Pair0() as s:
        cb = lambda pipe: None
        s.add_pre_pipe_connect_cb(cb)
        assert len(s._on_pre_pipe_add) == 1
        s.remove_pre_pipe_connect_cb(cb)
        assert len(s._on_pre_pipe_add) == 0

        s.add_post_pipe_connect_cb(cb)
        assert len(s._on_post_pipe_add) == 1
        s.remove_post_pipe_connect_cb(cb)
        assert len(s._on_post_pipe_add) == 0

        s.add_post_pipe_remove_cb(cb)
        assert len(s._on_post_pipe_remove) == 1
        s.remove_post_pipe_remove_cb(cb)
        assert len(s._on_post_pipe_remove) == 0


def test_nonblocking_recv_msg(nng):
    addr = unique_inproc_addr()
    with nng.Pair0(listen=addr) as s:
        with pytest.raises(nng.TryAgain):
            s.recv_msg(block=False)


def test_nonblocking_send_msg(nng):
    addr = unique_inproc_addr()
    with nng.Pair0(listen=addr) as s:
        msg = nng.Message(b"will not send")
        with pytest.raises(nng.TryAgain):
            s.send_msg(msg, block=False)


@pytest.mark.skipif(
    platform.python_implementation() == "PyPy",
    reason="PyPy GC does not guarantee __del__ timing"
)
@pytest.mark.nng_v1
def test_sockets_get_garbage_collected():
    """v1-only: checks isinstance against pynng.Pub0 specifically."""
    import pynng
    with pynng.Pub0() as _:
        pass
    _ = None
    gc.collect()
    objs = [o for o in gc.get_objects() if isinstance(o, pynng.Pub0)]
    assert len(objs) == 0
