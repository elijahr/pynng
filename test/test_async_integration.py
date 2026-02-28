"""Async integration tests for multi-peer messaging topologies.

Tests that NNG messaging patterns work correctly under Python's async
event loops (both trio and asyncio), exercising concurrent callback
delivery, context multiplexing, and socket lifecycle management
through the CFFI wrapper layer.
"""

import asyncio

import pytest
import trio

import pynng
from _test_util import wait_pipe_len


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_addr(name):
    """Return a unique inproc address for the given test name."""
    return "inproc://test-async-integ-{}".format(name)


# ---------------------------------------------------------------------------
# 1. Fan-out/Fan-in: Pub/Sub with multiple subscribers
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_pubsub_fanout_all_subscribers_receive_trio():
    """1 publisher, 3 subscribers all subscribed to everything.

    All subscribers must receive all N messages.  This exercises concurrent
    callback delivery under the GIL with trio.
    """
    addr = _unique_addr("pubsub-fanout-trio")
    num_messages = 20
    num_subs = 3

    with pynng.Pub0(listen=addr) as pub:
        subs = []
        for _ in range(num_subs):
            s = pynng.Sub0(dial=addr, recv_timeout=3000)
            s.subscribe(b"")
            subs.append(s)

        # Wait for all pipes to connect
        wait_pipe_len(pub, num_subs)
        for s in subs:
            wait_pipe_len(s, 1)

        received = [[] for _ in range(num_subs)]

        async def recv_all(idx, sub):
            for _ in range(num_messages):
                msg = await sub.arecv()
                received[idx].append(msg)

        # Send all messages first, then receive.
        # Pub/sub is best-effort, so we give a short settling time.
        await trio.sleep(0.05)
        for i in range(num_messages):
            await pub.asend("msg:{}".format(i).encode())

        async with trio.open_nursery() as nursery:
            for idx, sub in enumerate(subs):
                nursery.start_soon(recv_all, idx, sub)

        for sub in subs:
            sub.close()

    # Verify all subscribers received all messages
    for idx in range(num_subs):
        assert len(received[idx]) == num_messages, (
            "Subscriber {} received {} messages, expected {}".format(
                idx, len(received[idx]), num_messages
            )
        )
        for i in range(num_messages):
            assert "msg:{}".format(i).encode() in received[idx]


@pytest.mark.asyncio
async def test_pubsub_fanout_all_subscribers_receive_asyncio():
    """Same as trio variant but with asyncio backend."""
    addr = _unique_addr("pubsub-fanout-asyncio")
    num_messages = 20
    num_subs = 3

    with pynng.Pub0(listen=addr) as pub:
        subs = []
        for _ in range(num_subs):
            s = pynng.Sub0(dial=addr, recv_timeout=3000)
            s.subscribe(b"")
            subs.append(s)

        wait_pipe_len(pub, num_subs)
        for s in subs:
            wait_pipe_len(s, 1)

        received = [[] for _ in range(num_subs)]

        async def recv_all(idx, sub):
            for _ in range(num_messages):
                msg = await sub.arecv()
                received[idx].append(msg)

        await asyncio.sleep(0.05)
        for i in range(num_messages):
            await pub.asend("msg:{}".format(i).encode())

        await asyncio.gather(*(recv_all(idx, sub) for idx, sub in enumerate(subs)))

        for sub in subs:
            sub.close()

    for idx in range(num_subs):
        assert len(received[idx]) == num_messages
        for i in range(num_messages):
            assert "msg:{}".format(i).encode() in received[idx]


@pytest.mark.trio
async def test_pubsub_topic_filtering_trio():
    """Subscribers with different topic filters only receive matching messages."""
    addr = _unique_addr("pubsub-topics-trio")
    num_per_topic = 10

    with pynng.Pub0(listen=addr) as pub:
        sub_even = pynng.Sub0(dial=addr, recv_timeout=3000)
        sub_even.subscribe(b"even:")
        sub_odd = pynng.Sub0(dial=addr, recv_timeout=3000)
        sub_odd.subscribe(b"odd:")

        wait_pipe_len(pub, 2)
        wait_pipe_len(sub_even, 1)
        wait_pipe_len(sub_odd, 1)

        received_even = []
        received_odd = []

        async def recv_even():
            for _ in range(num_per_topic):
                msg = await sub_even.arecv()
                received_even.append(msg)

        async def recv_odd():
            for _ in range(num_per_topic):
                msg = await sub_odd.arecv()
                received_odd.append(msg)

        await trio.sleep(0.05)
        for i in range(num_per_topic * 2):
            prefix = b"even:" if i % 2 == 0 else b"odd:"
            await pub.asend(prefix + str(i).encode())

        async with trio.open_nursery() as nursery:
            nursery.start_soon(recv_even)
            nursery.start_soon(recv_odd)

        sub_even.close()
        sub_odd.close()

    assert len(received_even) == num_per_topic
    assert len(received_odd) == num_per_topic
    for msg in received_even:
        assert msg.startswith(b"even:")
    for msg in received_odd:
        assert msg.startswith(b"odd:")


@pytest.mark.asyncio
async def test_pubsub_topic_filtering_asyncio():
    """Topic filtering with asyncio backend."""
    addr = _unique_addr("pubsub-topics-asyncio")
    num_per_topic = 10

    with pynng.Pub0(listen=addr) as pub:
        sub_even = pynng.Sub0(dial=addr, recv_timeout=3000)
        sub_even.subscribe(b"even:")
        sub_odd = pynng.Sub0(dial=addr, recv_timeout=3000)
        sub_odd.subscribe(b"odd:")

        wait_pipe_len(pub, 2)
        wait_pipe_len(sub_even, 1)
        wait_pipe_len(sub_odd, 1)

        received_even = []
        received_odd = []

        async def recv_even():
            for _ in range(num_per_topic):
                received_even.append(await sub_even.arecv())

        async def recv_odd():
            for _ in range(num_per_topic):
                received_odd.append(await sub_odd.arecv())

        await asyncio.sleep(0.05)
        for i in range(num_per_topic * 2):
            prefix = b"even:" if i % 2 == 0 else b"odd:"
            await pub.asend(prefix + str(i).encode())

        await asyncio.gather(recv_even(), recv_odd())

        sub_even.close()
        sub_odd.close()

    assert len(received_even) == num_per_topic
    assert len(received_odd) == num_per_topic
    for msg in received_even:
        assert msg.startswith(b"even:")
    for msg in received_odd:
        assert msg.startswith(b"odd:")


# ---------------------------------------------------------------------------
# 2. Request/Reply under load with contexts
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_reqrep_concurrent_contexts_trio():
    """Multiple req contexts send simultaneously to a rep socket with contexts.

    Each request must get back the correct response (no cross-talk).
    """
    addr = _unique_addr("reqrep-ctx-trio")
    num_clients = 4

    with pynng.Rep0(listen=addr, recv_timeout=3000) as rep_sock, \
         pynng.Req0(dial=addr, recv_timeout=3000) as req_sock:
        wait_pipe_len(rep_sock, 1)

        results = {}

        async def client(idx):
            ctx_req = req_sock.new_context()
            request = "request-{}".format(idx).encode()
            await ctx_req.asend(request)
            response = await ctx_req.arecv()
            results[idx] = response
            ctx_req.close()

        async def server():
            for _ in range(num_clients):
                ctx_rep = rep_sock.new_context()
                data = await ctx_rep.arecv()
                # Echo back with a "reply-" prefix, stripping "request-"
                reply = data.replace(b"request-", b"reply-")
                await ctx_rep.asend(reply)
                ctx_rep.close()

        async with trio.open_nursery() as nursery:
            nursery.start_soon(server)
            for idx in range(num_clients):
                nursery.start_soon(client, idx)

    assert len(results) == num_clients
    for idx in range(num_clients):
        assert results[idx] == "reply-{}".format(idx).encode()


@pytest.mark.asyncio
async def test_reqrep_concurrent_contexts_asyncio():
    """Concurrent req/rep with contexts under asyncio."""
    addr = _unique_addr("reqrep-ctx-asyncio")
    num_clients = 4

    with pynng.Rep0(listen=addr, recv_timeout=3000) as rep_sock, \
         pynng.Req0(dial=addr, recv_timeout=3000) as req_sock:
        wait_pipe_len(rep_sock, 1)

        results = {}

        async def client(idx):
            ctx_req = req_sock.new_context()
            request = "request-{}".format(idx).encode()
            await ctx_req.asend(request)
            response = await ctx_req.arecv()
            results[idx] = response
            ctx_req.close()

        async def server():
            for _ in range(num_clients):
                ctx_rep = rep_sock.new_context()
                data = await ctx_rep.arecv()
                reply = data.replace(b"request-", b"reply-")
                await ctx_rep.asend(reply)
                ctx_rep.close()

        await asyncio.gather(
            server(),
            *(client(idx) for idx in range(num_clients)),
        )

    assert len(results) == num_clients
    for idx in range(num_clients):
        assert results[idx] == "reply-{}".format(idx).encode()


# ---------------------------------------------------------------------------
# 3. Pipeline fan-out: Push/Pull distribution
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_push_pull_fanout_trio():
    """1 Push, 3+ Pulls. All messages distributed (not duplicated) across pullers.

    Total received across all pullers must equal total sent.
    """
    addr = _unique_addr("pushpull-trio")
    num_messages = 30
    num_pullers = 3

    with pynng.Push0(
        listen=addr, send_timeout=5000, send_buffer_size=64
    ) as push:
        pullers = []
        for _ in range(num_pullers):
            p = pynng.Pull0(dial=addr, recv_timeout=3000, recv_buffer_size=64)
            pullers.append(p)

        wait_pipe_len(push, num_pullers)
        for p in pullers:
            wait_pipe_len(p, 1)

        received = [[] for _ in range(num_pullers)]
        all_sent = set()
        send_done = trio.Event()

        async def recv_loop(idx, puller):
            while True:
                try:
                    msg = await puller.arecv()
                    received[idx].append(msg)
                except pynng.Timeout:
                    break

        async def send_loop():
            for i in range(num_messages):
                data = "push-{}".format(i).encode()
                all_sent.add(data)
                await push.asend(data)
            send_done.set()

        async with trio.open_nursery() as nursery:
            for idx, puller in enumerate(pullers):
                nursery.start_soon(recv_loop, idx, puller)
            nursery.start_soon(send_loop)
            # Wait for send to finish, then set short recv_timeout
            await send_done.wait()
            await trio.sleep(0.1)
            for p in pullers:
                p.recv_timeout = 200

        for p in pullers:
            p.close()

    # Total received == total sent (no duplication, no loss)
    all_received = []
    for r in received:
        all_received.extend(r)
    assert len(all_received) == num_messages, (
        "Received {} messages, expected {}".format(len(all_received), num_messages)
    )
    assert set(all_received) == all_sent

    # Verify distribution: each puller got at least 1 message
    for idx in range(num_pullers):
        assert len(received[idx]) > 0, (
            "Puller {} received no messages".format(idx)
        )


@pytest.mark.asyncio
async def test_push_pull_fanout_asyncio():
    """Push/Pull fan-out with asyncio backend."""
    addr = _unique_addr("pushpull-asyncio")
    num_messages = 30
    num_pullers = 3

    with pynng.Push0(
        listen=addr, send_timeout=5000, send_buffer_size=64
    ) as push:
        pullers = []
        for _ in range(num_pullers):
            p = pynng.Pull0(dial=addr, recv_timeout=3000, recv_buffer_size=64)
            pullers.append(p)

        wait_pipe_len(push, num_pullers)
        for p in pullers:
            wait_pipe_len(p, 1)

        received = [[] for _ in range(num_pullers)]
        all_sent = set()
        send_done = asyncio.Event()

        async def recv_loop(idx, puller):
            while True:
                try:
                    msg = await puller.arecv()
                    received[idx].append(msg)
                except pynng.Timeout:
                    break

        async def send_loop():
            for i in range(num_messages):
                data = "push-{}".format(i).encode()
                all_sent.add(data)
                await push.asend(data)
            send_done.set()

        async def recv_with_timeout():
            await asyncio.gather(
                *(recv_loop(idx, puller) for idx, puller in enumerate(pullers))
            )

        # Start recv tasks and send concurrently
        recv_task = asyncio.ensure_future(recv_with_timeout())
        await send_loop()
        await asyncio.sleep(0.1)
        for p in pullers:
            p.recv_timeout = 200
        await recv_task

        for p in pullers:
            p.close()

    all_received = []
    for r in received:
        all_received.extend(r)
    assert len(all_received) == num_messages
    assert set(all_received) == all_sent
    for idx in range(num_pullers):
        assert len(received[idx]) > 0


# ---------------------------------------------------------------------------
# 4. Pair1 polyamorous routing
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_pair1_polyamorous_routing_trio():
    """Pair1 listener with polyamorous=True routes messages to specific peers via pipes."""
    addr = _unique_addr("pair1-poly-trio")
    num_dialers = 3

    with pynng.Pair1(
        listen=addr, polyamorous=True, recv_timeout=3000
    ) as listener:
        dialers = []
        for _ in range(num_dialers):
            d = pynng.Pair1(
                dial=addr, polyamorous=True, recv_timeout=3000
            )
            dialers.append(d)

        wait_pipe_len(listener, num_dialers)
        for d in dialers:
            wait_pipe_len(d, 1)

        # Each dialer sends an identifying message
        for idx, d in enumerate(dialers):
            await d.asend("hello-from-{}".format(idx).encode())

        # Listener receives all messages and tracks which pipe each came from
        pipe_to_dialer_idx = {}
        for _ in range(num_dialers):
            msg = await listener.arecv_msg()
            data = msg.bytes
            # Parse "hello-from-N"
            dialer_idx = int(data.split(b"-")[-1])
            pipe_to_dialer_idx[msg.pipe.id] = dialer_idx

        assert len(pipe_to_dialer_idx) == num_dialers

        # Now send targeted replies via each pipe
        for pipe in listener.pipes:
            dialer_idx = pipe_to_dialer_idx[pipe.id]
            await pipe.asend(
                "reply-to-{}".format(dialer_idx).encode()
            )

        # Each dialer should get only its own reply
        for idx, d in enumerate(dialers):
            reply = await d.arecv()
            assert reply == "reply-to-{}".format(idx).encode(), (
                "Dialer {} got wrong reply: {}".format(idx, reply)
            )

        for d in dialers:
            d.close()


@pytest.mark.asyncio
async def test_pair1_polyamorous_routing_asyncio():
    """Pair1 polyamorous routing with asyncio backend."""
    addr = _unique_addr("pair1-poly-asyncio")
    num_dialers = 3

    with pynng.Pair1(
        listen=addr, polyamorous=True, recv_timeout=3000
    ) as listener:
        dialers = []
        for _ in range(num_dialers):
            d = pynng.Pair1(
                dial=addr, polyamorous=True, recv_timeout=3000
            )
            dialers.append(d)

        wait_pipe_len(listener, num_dialers)
        for d in dialers:
            wait_pipe_len(d, 1)

        for idx, d in enumerate(dialers):
            await d.asend("hello-from-{}".format(idx).encode())

        pipe_to_dialer_idx = {}
        for _ in range(num_dialers):
            msg = await listener.arecv_msg()
            data = msg.bytes
            dialer_idx = int(data.split(b"-")[-1])
            pipe_to_dialer_idx[msg.pipe.id] = dialer_idx

        assert len(pipe_to_dialer_idx) == num_dialers

        for pipe in listener.pipes:
            dialer_idx = pipe_to_dialer_idx[pipe.id]
            await pipe.asend(
                "reply-to-{}".format(dialer_idx).encode()
            )

        for idx, d in enumerate(dialers):
            reply = await d.arecv()
            assert reply == "reply-to-{}".format(idx).encode()

        for d in dialers:
            d.close()


# ---------------------------------------------------------------------------
# 5. Survey pattern with timeout
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_survey_with_partial_responses_trio():
    """Surveyor sends survey; some respondents reply, some don't.

    Verify surveyor collects available responses within timeout and
    does not hang or deadlock.
    """
    addr = _unique_addr("survey-trio")

    with pynng.Surveyor0(
        listen=addr, recv_timeout=3000, survey_time=500
    ) as surveyor:
        respondents = []
        for _ in range(3):
            r = pynng.Respondent0(dial=addr, recv_timeout=3000)
            respondents.append(r)

        wait_pipe_len(surveyor, 3)
        for r in respondents:
            wait_pipe_len(r, 1)

        responses_collected = []

        async def respond(idx, respondent):
            question = await respondent.arecv()
            assert question == b"survey-question"
            if idx < 2:
                # First two respondents reply immediately
                await respondent.asend(
                    "response-{}".format(idx).encode()
                )
            # Third respondent does not reply (simulating slow/absent)

        async def collect_responses():
            await surveyor.asend(b"survey-question")
            # Collect responses until survey_time expires
            while True:
                try:
                    resp = await surveyor.arecv()
                    responses_collected.append(resp)
                except pynng.Timeout:
                    break

        async with trio.open_nursery() as nursery:
            for idx, r in enumerate(respondents):
                nursery.start_soon(respond, idx, r)
            nursery.start_soon(collect_responses)

        for r in respondents:
            r.close()

    # Should have exactly 2 responses (from respondents 0 and 1)
    assert len(responses_collected) == 2
    assert b"response-0" in responses_collected
    assert b"response-1" in responses_collected


@pytest.mark.asyncio
async def test_survey_with_partial_responses_asyncio():
    """Survey pattern with partial responses under asyncio."""
    addr = _unique_addr("survey-asyncio")

    with pynng.Surveyor0(
        listen=addr, recv_timeout=3000, survey_time=500
    ) as surveyor:
        respondents = []
        for _ in range(3):
            r = pynng.Respondent0(dial=addr, recv_timeout=3000)
            respondents.append(r)

        wait_pipe_len(surveyor, 3)
        for r in respondents:
            wait_pipe_len(r, 1)

        responses_collected = []

        async def respond(idx, respondent):
            question = await respondent.arecv()
            assert question == b"survey-question"
            if idx < 2:
                await respondent.asend(
                    "response-{}".format(idx).encode()
                )

        async def collect_responses():
            await surveyor.asend(b"survey-question")
            while True:
                try:
                    resp = await surveyor.arecv()
                    responses_collected.append(resp)
                except pynng.Timeout:
                    break

        await asyncio.gather(
            collect_responses(),
            *(respond(idx, r) for idx, r in enumerate(respondents)),
        )

        for r in respondents:
            r.close()

    assert len(responses_collected) == 2
    assert b"response-0" in responses_collected
    assert b"response-1" in responses_collected


# ---------------------------------------------------------------------------
# 6. Async for message streaming
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_async_for_multiple_sockets_parallel_trio():
    """Multiple sockets consuming messages via async for in parallel."""
    addr1 = _unique_addr("aiter-multi-1-trio")
    addr2 = _unique_addr("aiter-multi-2-trio")
    num_messages = 5

    received1 = []
    received2 = []

    pusher1 = pynng.Push0(listen=addr1, send_timeout=2000)
    puller1 = pynng.Pull0(dial=addr1, recv_timeout=2000)
    pusher2 = pynng.Push0(listen=addr2, send_timeout=2000)
    puller2 = pynng.Pull0(dial=addr2, recv_timeout=2000)

    wait_pipe_len(pusher1, 1)
    wait_pipe_len(pusher2, 1)

    async def consume1():
        async for msg in puller1:
            received1.append(msg)

    async def consume2():
        async for msg in puller2:
            received2.append(msg)

    async def produce():
        for i in range(num_messages):
            await pusher1.asend("s1-{}".format(i).encode())
            await pusher2.asend("s2-{}".format(i).encode())
        await trio.sleep(0.05)
        puller1.close()
        puller2.close()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(consume1)
        nursery.start_soon(consume2)
        nursery.start_soon(produce)

    pusher1.close()
    pusher2.close()

    assert len(received1) == num_messages
    assert len(received2) == num_messages
    for i in range(num_messages):
        assert "s1-{}".format(i).encode() in received1
        assert "s2-{}".format(i).encode() in received2


@pytest.mark.asyncio
async def test_async_for_multiple_sockets_parallel_asyncio():
    """Multiple sockets consuming via async for in parallel with asyncio."""
    addr1 = _unique_addr("aiter-multi-1-asyncio")
    addr2 = _unique_addr("aiter-multi-2-asyncio")
    num_messages = 5

    received1 = []
    received2 = []

    pusher1 = pynng.Push0(listen=addr1, send_timeout=2000)
    puller1 = pynng.Pull0(dial=addr1, recv_timeout=2000)
    pusher2 = pynng.Push0(listen=addr2, send_timeout=2000)
    puller2 = pynng.Pull0(dial=addr2, recv_timeout=2000)

    wait_pipe_len(pusher1, 1)
    wait_pipe_len(pusher2, 1)

    async def consume1():
        async for msg in puller1:
            received1.append(msg)

    async def consume2():
        async for msg in puller2:
            received2.append(msg)

    async def produce():
        for i in range(num_messages):
            await pusher1.asend("s1-{}".format(i).encode())
            await pusher2.asend("s2-{}".format(i).encode())
        await asyncio.sleep(0.05)
        puller1.close()
        puller2.close()

    await asyncio.gather(consume1(), consume2(), produce())

    pusher1.close()
    pusher2.close()

    assert len(received1) == num_messages
    assert len(received2) == num_messages
    for i in range(num_messages):
        assert "s1-{}".format(i).encode() in received1
        assert "s2-{}".format(i).encode() in received2


@pytest.mark.trio
async def test_async_for_close_mid_stream_trio():
    """Close socket mid-stream during async for; verify clean shutdown."""
    addr = _unique_addr("aiter-close-mid-trio")
    received = []

    pusher = pynng.Push0(listen=addr, send_timeout=2000)
    puller = pynng.Pull0(dial=addr, recv_timeout=5000)
    wait_pipe_len(pusher, 1)

    async def produce():
        for i in range(3):
            await pusher.asend("msg-{}".format(i).encode())
        # Wait for messages to be received, then close the puller
        await trio.sleep(0.1)
        puller.close()

    async def consume():
        async for msg in puller:
            received.append(msg)
        # Should exit cleanly, no hang

    async with trio.open_nursery() as nursery:
        nursery.start_soon(consume)
        nursery.start_soon(produce)

    pusher.close()

    assert len(received) == 3


@pytest.mark.asyncio
async def test_async_for_close_mid_stream_asyncio():
    """Close socket mid-stream during async for with asyncio."""
    addr = _unique_addr("aiter-close-mid-asyncio")
    received = []

    pusher = pynng.Push0(listen=addr, send_timeout=2000)
    puller = pynng.Pull0(dial=addr, recv_timeout=5000)
    wait_pipe_len(pusher, 1)

    async def produce():
        for i in range(3):
            await pusher.asend("msg-{}".format(i).encode())
        await asyncio.sleep(0.05)
        puller.close()

    async def consume():
        async for msg in puller:
            received.append(msg)

    await asyncio.gather(consume(), produce())

    pusher.close()

    assert len(received) == 3


# ---------------------------------------------------------------------------
# 7. Rapid open/close under async load
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_rapid_open_close_trio():
    """Open socket, start async recv, close quickly. Repeat 10+ times.

    Verify no segfault, no hang, proper Closed exception each time.
    """
    for i in range(15):
        addr = _unique_addr("rapid-{}-trio".format(i))
        sock = pynng.Pair0(listen=addr, recv_timeout=5000)

        async with trio.open_nursery() as nursery:
            got_closed = False

            async def try_recv():
                nonlocal got_closed
                try:
                    await sock.arecv()
                except (pynng.Closed, pynng.Timeout):
                    got_closed = True

            async def close_soon():
                await trio.sleep(0.01)
                sock.close()

            nursery.start_soon(try_recv)
            nursery.start_soon(close_soon)

        assert got_closed, "Iteration {} did not get Closed".format(i)


@pytest.mark.asyncio
async def test_rapid_open_close_asyncio():
    """Rapid open/close under asyncio. 10+ iterations."""
    for i in range(15):
        addr = _unique_addr("rapid-{}-asyncio".format(i))
        sock = pynng.Pair0(listen=addr, recv_timeout=5000)

        got_closed = False

        async def try_recv():
            nonlocal got_closed
            try:
                await sock.arecv()
            except (pynng.Closed, pynng.Timeout):
                got_closed = True

        async def close_soon():
            await asyncio.sleep(0.01)
            sock.close()

        await asyncio.gather(try_recv(), close_soon())
        assert got_closed, "Iteration {} did not get Closed".format(i)


@pytest.mark.trio
async def test_rapid_open_close_with_connected_peer_trio():
    """Open socket, connect peer, start async recv, close quickly.

    Tests that closing a connected socket under active async recv does not
    segfault or hang, even with an active peer.
    """
    for i in range(10):
        addr = _unique_addr("rapid-peer-{}-trio".format(i))
        listener = pynng.Pair0(listen=addr, recv_timeout=5000)
        dialer = pynng.Pair0(dial=addr, recv_timeout=5000)
        wait_pipe_len(listener, 1)

        async with trio.open_nursery() as nursery:
            got_exception = False

            async def try_recv():
                nonlocal got_exception
                try:
                    await listener.arecv()
                except (pynng.Closed, pynng.Timeout):
                    got_exception = True

            async def close_soon():
                await trio.sleep(0.01)
                listener.close()

            nursery.start_soon(try_recv)
            nursery.start_soon(close_soon)

        dialer.close()
        assert got_exception


@pytest.mark.asyncio
async def test_rapid_open_close_with_connected_peer_asyncio():
    """Open socket, connect peer, start async recv, close quickly under asyncio."""
    for i in range(10):
        addr = _unique_addr("rapid-peer-{}-asyncio".format(i))
        listener = pynng.Pair0(listen=addr, recv_timeout=5000)
        dialer = pynng.Pair0(dial=addr, recv_timeout=5000)
        wait_pipe_len(listener, 1)

        got_exception = False

        async def try_recv():
            nonlocal got_exception
            try:
                await listener.arecv()
            except (pynng.Closed, pynng.Timeout):
                got_exception = True

        async def close_soon():
            await asyncio.sleep(0.01)
            listener.close()

        await asyncio.gather(try_recv(), close_soon())
        dialer.close()
        assert got_exception


# ---------------------------------------------------------------------------
# 8. Mixed sync/async on same socket
# ---------------------------------------------------------------------------

@pytest.mark.trio
async def test_sync_send_async_recv_trio():
    """Socket used for sync send, then async recv (or vice versa)."""
    addr = _unique_addr("mixed-sync-async-trio")
    with pynng.Pair0(listen=addr, recv_timeout=2000, send_timeout=2000) as s0, \
         pynng.Pair0(dial=addr, recv_timeout=2000, send_timeout=2000) as s1:
        wait_pipe_len(s0, 1)

        # Sync send from s0, async recv on s1
        s0.send(b"sync-to-async")
        result = await s1.arecv()
        assert result == b"sync-to-async"

        # Async send from s1, sync recv on s0
        await s1.asend(b"async-to-sync")
        result = s0.recv()
        assert result == b"async-to-sync"


@pytest.mark.asyncio
async def test_sync_send_async_recv_asyncio():
    """Mixed sync/async on same socket with asyncio."""
    addr = _unique_addr("mixed-sync-async-asyncio")
    with pynng.Pair0(listen=addr, recv_timeout=2000, send_timeout=2000) as s0, \
         pynng.Pair0(dial=addr, recv_timeout=2000, send_timeout=2000) as s1:
        wait_pipe_len(s0, 1)

        # Sync send, async recv
        s0.send(b"sync-to-async")
        result = await s1.arecv()
        assert result == b"sync-to-async"

        # Async send, sync recv
        await s1.asend(b"async-to-sync")
        result = s0.recv()
        assert result == b"async-to-sync"


@pytest.mark.trio
async def test_alternating_sync_async_trio():
    """Alternate between sync and async operations on the same socket pair."""
    addr = _unique_addr("alternating-trio")
    with pynng.Pair0(listen=addr, recv_timeout=2000, send_timeout=2000) as s0, \
         pynng.Pair0(dial=addr, recv_timeout=2000, send_timeout=2000) as s1:
        wait_pipe_len(s0, 1)

        for i in range(5):
            if i % 2 == 0:
                # Sync send from s0
                s0.send("sync-{}".format(i).encode())
                result = await s1.arecv()
            else:
                # Async send from s0
                await s0.asend("async-{}".format(i).encode())
                result = s1.recv()

            if i % 2 == 0:
                assert result == "sync-{}".format(i).encode()
            else:
                assert result == "async-{}".format(i).encode()


@pytest.mark.asyncio
async def test_alternating_sync_async_asyncio():
    """Alternating sync/async with asyncio backend."""
    addr = _unique_addr("alternating-asyncio")
    with pynng.Pair0(listen=addr, recv_timeout=2000, send_timeout=2000) as s0, \
         pynng.Pair0(dial=addr, recv_timeout=2000, send_timeout=2000) as s1:
        wait_pipe_len(s0, 1)

        for i in range(5):
            if i % 2 == 0:
                s0.send("sync-{}".format(i).encode())
                result = await s1.arecv()
            else:
                await s0.asend("async-{}".format(i).encode())
                result = s1.recv()

            if i % 2 == 0:
                assert result == "sync-{}".format(i).encode()
            else:
                assert result == "async-{}".format(i).encode()
