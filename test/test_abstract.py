import time
import pytest
import pynng
import pynng.sockaddr
import platform


def test_abstract_addr_basic():
    """Test basic AbstractAddr functionality"""
    # Test that NNG_AF_ABSTRACT is available
    assert hasattr(pynng.lib, "NNG_AF_ABSTRACT")
    assert pynng.lib.NNG_AF_ABSTRACT == 6
    # Verify the Python AbstractAddr class exists and is a proper SockAddr subclass
    assert hasattr(pynng.sockaddr, "AbstractAddr")
    assert issubclass(pynng.sockaddr.AbstractAddr, pynng.sockaddr.SockAddr)


def test_abstract_addr_in_type_to_str():
    """Test that abstract socket family is in type_to_str mapping"""
    assert pynng.lib.NNG_AF_ABSTRACT in pynng.sockaddr.SockAddr.type_to_str
    assert pynng.sockaddr.SockAddr.type_to_str[pynng.lib.NNG_AF_ABSTRACT] == "abstract"


def test_nng_sockaddr_dispatch_includes_abstract():
    """Test that _nng_sockaddr correctly dispatches NNG_AF_ABSTRACT to AbstractAddr"""
    from pynng.sockaddr import _nng_sockaddr

    # Create a mock sockaddr with abstract family to verify dispatch
    class MockAbstractSockAddr:
        def __init__(self):
            self.s_family = pynng.lib.NNG_AF_ABSTRACT
            self.s_abstract = MockAbstract()

    class MockAbstract:
        def __init__(self):
            self.sa_len = 4
            self.sa_name = bytearray(107)
            self.sa_name[0:4] = b"test"

    mock_addr = [MockAbstractSockAddr()]
    result = _nng_sockaddr(mock_addr)
    assert isinstance(result, pynng.sockaddr.AbstractAddr)
    assert result.family == pynng.lib.NNG_AF_ABSTRACT


@pytest.mark.skipif(
    platform.system() != "Linux", reason="Abstract sockets are Linux-specific"
)
def test_abstract_socket_connection():
    """Test actual abstract socket connection on Linux"""
    # Test with a simple abstract socket name
    abstract_addr = "abstract://test_socket"

    with pynng.Pair0(recv_timeout=1000) as sock1, pynng.Pair0(
        recv_timeout=1000
    ) as sock2:
        # Test listening on abstract socket
        listener = sock1.listen(abstract_addr)
        assert len(sock1.listeners) == 1

        # Test dialing abstract socket
        sock2.dial(abstract_addr)
        assert len(sock2.dialers) == 1

        # Test basic communication
        sock1.send(b"hello")
        received = sock2.recv()
        assert received == b"hello"

        # Test that local address is AbstractAddr
        local_addr = listener.local_address
        assert isinstance(local_addr, pynng.sockaddr.AbstractAddr)
        assert local_addr.family == pynng.lib.NNG_AF_ABSTRACT
        assert local_addr.family_as_str == "abstract"


@pytest.mark.skipif(
    platform.system() != "Linux", reason="Abstract sockets are Linux-specific"
)
def test_abstract_socket_with_special_chars():
    """Test abstract socket with special characters including NUL bytes"""
    # Test with URI-encoded special characters
    abstract_addr = "abstract://test%00socket%20with%20spaces"

    with pynng.Pair0(recv_timeout=100) as sock1, pynng.Pair0(recv_timeout=100) as sock2:
        listener = sock1.listen(abstract_addr)
        sock2.dial(abstract_addr)

        # Test communication
        sock1.send(b"test message")
        received = sock2.recv()
        assert received == b"test message"

        # Test that the address is properly handled
        local_addr = listener.local_address
        assert isinstance(local_addr, pynng.sockaddr.AbstractAddr)

        # Test string representation
        addr_str = str(local_addr)
        assert addr_str.startswith("abstract://")


@pytest.mark.skipif(
    platform.system() != "Linux", reason="Abstract sockets are Linux-specific"
)
@pytest.mark.xfail(
    raises=pynng.exceptions.InvalidOperation,
    reason="Auto-bind with empty abstract name not supported in all NNG versions",
    strict=False,
)
def test_abstract_socket_auto_bind():
    """Test abstract socket auto-bind functionality with empty name"""
    # Test with empty abstract socket name for auto-bind
    abstract_addr = "abstract://"

    with pynng.Pair0(recv_timeout=100) as sock1, pynng.Pair0(recv_timeout=100) as sock2:
        listener = sock1.listen(abstract_addr)
        sock2.dial(abstract_addr)

        # Test communication
        sock1.send(b"auto-bind test")
        received = sock2.recv()
        assert received == b"auto-bind test"

        # Test that the address is properly handled
        local_addr = listener.local_address
        assert isinstance(local_addr, pynng.sockaddr.AbstractAddr)


@pytest.mark.skipif(
    platform.system() != "Linux", reason="Abstract sockets are Linux-specific"
)
def test_abstract_socket_with_different_protocols():
    """Test abstract sockets with different protocol types"""
    protocols = [
        (pynng.Pair0, pynng.Pair0, "pair"),
        (pynng.Pub0, pynng.Sub0, "pubsub"),
        (pynng.Push0, pynng.Pull0, "pushpull"),
        (pynng.Req0, pynng.Rep0, "reqrep"),
    ]

    for server_proto, client_proto, proto_name in protocols:
        # Use a unique address for each protocol to avoid "Address in use" errors
        abstract_addr = f"abstract://test_{proto_name}_protocol"

        # Retry logic to handle race conditions
        max_retries = 5
        for retry in range(max_retries):
            try:
                with server_proto(recv_timeout=100) as server, client_proto(
                    recv_timeout=100
                ) as client:
                    if server_proto == pynng.Pub0 and client_proto == pynng.Sub0:
                        # Special handling for pub/sub
                        server.listen(abstract_addr)
                        client.dial(abstract_addr)
                        client.subscribe("")  # Subscribe to all messages
                        # Add a small delay to ensure subscription is processed
                        time.sleep(0.01)
                        server.send(b"pubsub test")
                        received = client.recv()
                        assert received == b"pubsub test"
                    elif server_proto == pynng.Push0 and client_proto == pynng.Pull0:
                        # Special handling for push/pull
                        server.listen(abstract_addr)
                        client.dial(abstract_addr)
                        # Add a small delay to ensure connection is established
                        time.sleep(0.01)
                        server.send(b"pushpull test")
                        received = client.recv()
                        assert received == b"pushpull test"
                    elif server_proto == pynng.Req0 and client_proto == pynng.Rep0:
                        # Special handling for req/rep
                        client.listen(abstract_addr)
                        server.dial(abstract_addr)
                        # Add a small delay to ensure connection is established
                        time.sleep(0.01)
                        server.send(b"reqrep test")
                        received = client.recv()
                        assert received == b"reqrep test"
                        client.send(b"reply")
                        reply = server.recv()
                        assert reply == b"reply"
                    else:
                        # Default handling for pair protocols
                        server.listen(abstract_addr)
                        client.dial(abstract_addr)
                        # Add a small delay to ensure connection is established
                        time.sleep(0.01)
                        server.send(b"pair test")
                        received = client.recv()
                        assert received == b"pair test"

                # If we get here, the test passed for this protocol
                break

            except pynng.exceptions.Timeout:
                if retry == max_retries - 1:
                    # This was the last retry, re-raise the exception
                    raise
                # Log the retry attempt
                print(
                    f"Retry {retry + 1}/{max_retries} for {proto_name} protocol due to timeout"
                )
                # Add a small delay before retrying
                time.sleep(0.1)


@pytest.mark.skipif(
    platform.system() == "Linux", reason="Test error handling on non-Linux systems"
)
def test_abstract_socket_error_on_non_linux():
    """Test that abstract sockets raise appropriate errors on non-Linux systems"""
    abstract_addr = "abstract://test_socket"

    with pytest.raises(pynng.exceptions.NNGException):
        with pynng.Pair0() as sock:
            sock.listen(abstract_addr)


def test_abstract_addr_name_bytes():
    """Test AbstractAddr name_bytes property"""

    # Create a mock abstract sockaddr
    class MockAbstractSockAddr:
        def __init__(self):
            self.s_family = pynng.lib.NNG_AF_ABSTRACT
            self.s_abstract = MockAbstract()

    class MockAbstract:
        def __init__(self):
            self.sa_len = 5
            self.sa_name = bytearray(107)
            # Set first 5 bytes
            self.sa_name[0:5] = [ord("t"), ord("e"), ord("s"), ord("t"), 0]

    # Create a mock ffi_sock_addr
    mock_sock_addr = [MockAbstractSockAddr()]

    # Create AbstractAddr instance
    abstract_addr = pynng.sockaddr.AbstractAddr(mock_sock_addr)

    # Test name_bytes property
    name_bytes = abstract_addr.name_bytes
    assert len(name_bytes) == 5
    assert name_bytes == b"test\x00"


def test_abstract_addr_name_with_uri_encoding():
    """Test AbstractAddr name property with NUL bytes and URI decoding"""

    class MockAbstractSockAddr:
        def __init__(self):
            self.s_family = pynng.lib.NNG_AF_ABSTRACT
            self.s_abstract = MockAbstract()

    class MockAbstract:
        def __init__(self):
            self.sa_len = 11
            self.sa_name = bytearray(107)
            test_bytes = b"test\x00socket"
            self.sa_name[0:11] = test_bytes

    mock_sock_addr = [MockAbstractSockAddr()]
    abstract_addr = pynng.sockaddr.AbstractAddr(mock_sock_addr)

    # Verify the exact decoded name, including the NUL byte
    name = abstract_addr.name
    assert name == "test\x00socket"


def test_abstract_addr_str_representation():
    """Test AbstractAddr string representation"""

    class MockAbstractSockAddr:
        def __init__(self):
            self.s_family = pynng.lib.NNG_AF_ABSTRACT
            self.s_abstract = MockAbstract()

    class MockAbstract:
        def __init__(self):
            self.sa_len = 9
            self.sa_name = bytearray(107)
            test_bytes = b"test_name"
            self.sa_name[0:9] = test_bytes

    mock_sock_addr = [MockAbstractSockAddr()]
    abstract_addr = pynng.sockaddr.AbstractAddr(mock_sock_addr)

    # Verify exact string representation
    addr_str = str(abstract_addr)
    assert addr_str == "abstract://test_name"
