# pynng Tests

## Running Tests

```bash
# All tests
pytest test/

# Single file
pytest test/test_protocols.py

# Single test
pytest test/test_protocols.py::test_pair0
```

Default pytest config (pyproject.toml): `--capture=no --verbose`

## Test Files

| File | Tests | What it covers |
|------|-------|----------------|
| test_protocols.py | 9 | All protocol types: Bus0, Pair0/1, Req/Rep, Pub/Sub, Push/Pull, Surveyor/Respondent |
| test_aio.py | 7 | Async send/recv with asyncio and Trio, cancellation, pub/sub nurseries |
| test_api.py | 9 | Dialers, listeners, contexts, Pair1 polyamorous, Sub0 topics, GC |
| test_msg.py | 8 | Message creation, send/recv, pipe association, double-send prevention |
| test_options.py | 9 | Timeouts, socket name, raw mode, recv_max_size, sockaddr, resend_time |
| test_pipe.py | 10 | Pipe lifecycle, all callback types, pipe addresses, pipe send |
| test_tls.py | 2 | TLS with string certs and file certs |
| _test_util.py | - | Helper: `wait_pipe_len()` |

## Framework

- **pytest** with `pytest-trio` and `pytest-asyncio` (STRICT mode)
- No conftest.py, no custom fixtures
- All socket setup/teardown via context managers (inline, not fixtures)

## Writing a New Test

### Template

```python
import pynng
import pytest
from _test_util import wait_pipe_len

addr = "inproc://test-addr"

def test_my_feature():
    with pynng.Pair0(listen=addr, recv_timeout=1000) as s0, \
         pynng.Pair0(dial=addr, recv_timeout=1000) as s1:
        wait_pipe_len(s0, 1)
        s1.send(b"hello")
        assert s0.recv() == b"hello"
```

### Async test (Trio)

```python
@pytest.mark.trio
async def test_my_async_feature():
    with pynng.Pair0(listen=addr, recv_timeout=2000) as s0, \
         pynng.Pair0(dial=addr, send_timeout=2000) as s1:
        await s1.asend(b"hello")
        assert (await s0.arecv()) == b"hello"
```

### Async test (asyncio)

```python
@pytest.mark.asyncio
async def test_my_asyncio_feature():
    with pynng.Pair0(listen=addr, recv_timeout=2000) as s0, \
         pynng.Pair0(dial=addr, send_timeout=2000) as s1:
        await s1.asend(b"hello")
        assert (await s0.arecv()) == b"hello"
```

## Critical Patterns

### Always use `wait_pipe_len` before accessing pipes or sending

Pipe establishment is asynchronous. Sending immediately after `dial()` without waiting will fail non-deterministically:

```python
# WRONG - race condition
s1.dial(addr)
s0.pipes[0].send(b"data")  # IndexError sometimes

# CORRECT
s1.dial(addr)
wait_pipe_len(s0, 1)  # wait for pipe to establish
s0.pipes[0].send(b"data")
```

### Always set recv_timeout

Without `recv_timeout`, a `recv()` on a socket with no data will block forever, hanging the test:

```python
# WRONG - will hang if nothing is sent
with pynng.Pair0(listen=addr) as s:
    s.recv()

# CORRECT
with pynng.Pair0(listen=addr, recv_timeout=1000) as s:
    ...
```

### Use inproc:// transport

All tests should use `inproc://` addresses unless specifically testing TCP, IPC, or TLS behavior. It's fast and doesn't use OS resources.

### Use context managers for all sockets

Never create a socket without a `with` block in tests. Unclosed sockets leak resources and cause flaky tests.

```python
# WRONG
s = pynng.Pair0(listen=addr)
# if test fails, socket never closed

# CORRECT
with pynng.Pair0(listen=addr) as s:
    ...
```

## Common Gotchas

### macOS address reuse
After closing a listener and immediately re-listening on the same address, add `time.sleep(0.01)` on macOS:
```python
# Without this, macOS CI may fail with address-in-use
time.sleep(0.01)
s.listen(addr)
```

### Docker IPv6
`[::1]` is not available in most Docker containers. Skip IPv6 tests:
```python
if Path("/.dockerenv").exists():
    return
```

### Message is single-use for sending
Once `send_msg(msg)` is called, the Message's C memory is owned by nng. Sending the same Message twice raises `MessageStateError` (and without the guard, would SEGFAULT).

### Pipe callback threading
Pipe callbacks fire on nng's internal threads, not the Python main thread. Use polling loops with `wait_pipe_len` or manual `time.sleep(0.0005)` loops, not threading events (nng callbacks can't easily signal Python threading primitives).

### pytest-asyncio STRICT mode
`@pytest.mark.asyncio` must be explicitly added to every asyncio test. Auto mode is not configured.

## Test Coverage Gaps

Areas that are known to be undertested:
- Many socket options: recv_buffer_size, send_buffer_size, reconnect_time_min/max, recv_fd, send_fd, tcp_nodelay, tcp_keepalive, ttl_max
- Dialer/Listener-level options (only socket-level tested)
- Most NNGException subclasses (only Timeout, TryAgain, BadState, ConnectionRefused exercised)
- Context with protocols other than Req0/Rep0
- Sub0.unsubscribe()
