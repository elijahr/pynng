import time
import threading

import pytest

from _test_util import wait_pipe_len
from conftest import unique_inproc_addr


def test_bus(nng):
    addr = unique_inproc_addr()
    with nng.Bus0(recv_timeout=100) as s0, nng.Bus0(
        recv_timeout=100
    ) as s1, nng.Bus0(recv_timeout=100) as s2:
        s0.listen(addr)
        s1.dial(addr)
        s2.dial(addr)
        wait_pipe_len(s0, 2)
        s0.send(b"s1 and s2 get this")
        assert s1.recv() == b"s1 and s2 get this"
        assert s2.recv() == b"s1 and s2 get this"
        s1.send(b"only s0 gets this")
        assert s0.recv() == b"only s0 gets this"
        s2.recv_timeout = 0
        with pytest.raises(nng.Timeout):
            s2.recv()


def test_context_manager_works(nng):
    addr = unique_inproc_addr()
    s0 = nng.Pair0(listen=addr)
    assert len(s0.listeners) == 1
    s0.__exit__(None, None, None)
    # Verify the socket was closed and resources released
    assert len(s0.listeners) == 0
    # We should be able to reuse the address if cleanup happened
    with nng.Pair0(listen=addr) as s1:
        assert len(s1.listeners) == 1


def test_pair0(nng):
    addr = unique_inproc_addr()
    with nng.Pair0(listen=addr, recv_timeout=100) as s0, nng.Pair0(
        dial=addr, recv_timeout=100
    ) as s1:
        s1.send(b"hey howdy there")
        assert s0.recv() == b"hey howdy there"


def test_pair1(nng):
    addr = unique_inproc_addr()
    with nng.Pair1(listen=addr, recv_timeout=100) as s0, nng.Pair1(
        dial=addr, recv_timeout=100
    ) as s1:
        s1.send(b"beep boop beep")
        assert s0.recv() == b"beep boop beep"


def test_reqrep0(nng):
    addr = unique_inproc_addr()
    with nng.Req0(listen=addr, recv_timeout=100) as req, nng.Rep0(
        dial=addr, recv_timeout=100
    ) as rep:
        request = b"i am requesting"
        req.send(request)
        assert rep.recv() == request

        response = b"i am responding"
        rep.send(response)
        assert req.recv() == response

        with pytest.raises(nng.BadState):
            req.recv()

        # responders can't send before receiving
        with pytest.raises(nng.BadState):
            rep.send(b"I cannot do this why am I trying")


def test_pubsub0(nng):
    addr = unique_inproc_addr()
    with nng.Sub0(listen=addr, recv_timeout=100) as sub, nng.Pub0(
        dial=addr, recv_timeout=100
    ) as pub:
        sub.subscribe(b"")
        msg = b"i am requesting"
        wait_pipe_len(sub, 1)
        wait_pipe_len(pub, 1)
        pub.send(msg)
        assert sub.recv() == msg

        # publishers can't recv
        with pytest.raises(nng.NotSupported):
            pub.recv()

        # subscribers can't send
        with pytest.raises(nng.NotSupported):
            sub.send(
                b"""I am a bold subscribing socket.  I believe I was truly
                         meant to be a publisher.  The world needs to hear what
                         I have to say!
                     """
            )


def test_push_pull(nng):
    addr = unique_inproc_addr()
    received = {"pull1": None, "pull2": None}
    with nng.Push0(listen=addr) as push, nng.Pull0(
        dial=addr, recv_timeout=1000
    ) as pull1, nng.Pull0(dial=addr, recv_timeout=1000) as pull2:

        def recv1():
            received["pull1"] = pull1.recv()

        def recv2():
            received["pull2"] = pull2.recv()

        # push/pull does round robin style distribution
        t1 = threading.Thread(target=recv1, daemon=True)
        t2 = threading.Thread(target=recv2, daemon=True)

        t1.start()
        t2.start()
        wait_pipe_len(push, 2)
        wait_pipe_len(pull1, 1)
        wait_pipe_len(pull2, 1)

        push.send(b"message one")
        push.send(b"message two")
        t1.join()
        t2.join()
        # Verify actual data received, not just boolean flags
        all_received = {received["pull1"], received["pull2"]}
        assert all_received == {b"message one", b"message two"}


def test_surveyor_respondent(nng):
    addr = unique_inproc_addr()
    with nng.Surveyor0(listen=addr, recv_timeout=4000) as surveyor, nng.Respondent0(
        dial=addr, recv_timeout=4000
    ) as resp1, nng.Respondent0(dial=addr, recv_timeout=4000) as resp2:
        query = b"hey how's it going buddy?"
        # wait for sockets to connect
        wait_pipe_len(surveyor, 2)
        wait_pipe_len(resp1, 1)
        wait_pipe_len(resp2, 1)
        surveyor.send(query)
        assert resp1.recv() == query
        assert resp2.recv() == query
        resp1.send(b"not too bad I suppose")

        msg2 = b"""
            Thanks for asking.  It's been a while since I've had
            human contact; times have been difficult for me.  I woke up this
            morning and again could not find a pair of matching socks.  I know that
            a lot of people think it's worth it to just throw all your old socks
            out and buy like 12 pairs of identical socks, but that just seems so
            mundane.  Life is about more than socks, you know?  So anyway, since I
            couldn't find any socks, I went ahead and put banana peels on my
            feet.  They don't match *perfectly* but it's close enough.  Anyway
            thanks for asking, I guess I'm doing pretty good.
        """
        resp2.send(msg2)
        resp = [surveyor.recv() for _ in range(2)]
        assert b"not too bad I suppose" in resp
        assert msg2 in resp

        with pytest.raises(nng.BadState):
            resp2.send(b"oadsfji")

        now = time.monotonic()
        # 1 millisecond timeout
        surveyor.survey_time = 10
        surveyor.send(b"hey nobody should respond to me")
        with pytest.raises(nng.Timeout):
            surveyor.recv()
        later = time.monotonic()
        # nng default survey time is 1 second
        assert later - now < 0.9


def test_cannot_instantiate_socket_without_opener(nng):
    with pytest.raises(TypeError):
        nng.Socket()


@pytest.mark.nng_v1
def test_can_instantiate_socket_with_raw_opener():
    """v1-only: uses pynng.lib directly for raw opener."""
    import pynng
    with pynng.Socket(opener=pynng.lib.nng_sub0_open_raw) as s:
        assert s.raw is True
        assert isinstance(s.protocol_name, str)
        assert len(s.protocol_name) > 0


def test_can_pass_addr_as_bytes_or_str(nng):
    addr = unique_inproc_addr()
    addr_bytes = addr.encode()
    with nng.Pair0(
        listen=addr_bytes, recv_timeout=1000
    ) as s0, nng.Pair0(
        dial=addr, recv_timeout=1000
    ) as s1:
        wait_pipe_len(s0, 1)
        s1.send(b"hello from str dial")
        assert s0.recv() == b"hello from str dial"


def test_socket_protocol_properties(nng):
    """Test that socket protocol properties return correct values."""
    protocol_data = [
        ("Pair0", "pair", "pair"),
        ("Pub0", "pub", "sub"),
        ("Sub0", "sub", "pub"),
        ("Req0", "req", "rep"),
        ("Rep0", "rep", "req"),
        ("Push0", "push", "pull"),
        ("Pull0", "pull", "push"),
        ("Bus0", "bus", "bus"),
        ("Surveyor0", "surveyor", "respondent"),
        ("Respondent0", "respondent", "surveyor"),
    ]
    for cls_name, expected_name, expected_peer in protocol_data:
        socket_cls = getattr(nng, cls_name)
        with socket_cls() as s:
            assert s.protocol_name == expected_name, (
                f"{cls_name}.protocol_name == {s.protocol_name!r}, expected {expected_name!r}"
            )
            assert s.peer_name == expected_peer, (
                f"{cls_name}.peer_name == {s.peer_name!r}, expected {expected_peer!r}"
            )
            assert isinstance(s.protocol, int)
            assert s.protocol > 0
            assert isinstance(s.peer, int)
            assert s.peer > 0


def test_buffer_size_options(nng):
    """Test that recv_buffer_size and send_buffer_size can be set and read back."""
    with nng.Pair0(recv_buffer_size=4, send_buffer_size=8) as s:
        assert s.recv_buffer_size == 4
        assert s.send_buffer_size == 8
