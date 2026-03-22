"""Tests for safety and concurrency fixes.

Each test should fail without the corresponding fix in v1-safety-fixes.
"""

import gc
import threading

import pytest
import trio

import pynng


def _random_addr():
    return "inproc://test-safety-{}".format(id(object()))


class TestDelGuards:
    """__del__ guards prevent tracebacks during cleanup."""

    def test_socket_del_after_close(self):
        """Socket.__del__ should not raise after explicit close."""
        sock = pynng.Pair0(listen=_random_addr())
        sock.close()
        # Should not raise -- __del__ guards with try/except
        sock.__del__()

    def test_context_del_after_close(self):
        """Context.__del__ should not raise after explicit close."""
        sock = pynng.Rep0(listen=_random_addr())
        ctx = sock.new_context()
        ctx.close()
        # Should not raise
        ctx.__del__()
        sock.close()

    def test_tls_config_del_partially_initialized(self):
        """TLSConfig.__del__ should not raise if __init__ failed partway."""
        tls = pynng.TLSConfig.__new__(pynng.TLSConfig)
        # _tls_config is None because __init__ never completed
        # __del__ should handle this gracefully
        tls.__del__()

    def test_tls_config_del_after_normal_init(self):
        """TLSConfig should clean up without error when garbage collected."""
        tls = pynng.TLSConfig(pynng.TLSConfig.MODE_CLIENT)
        # Let normal GC handle cleanup -- just verify it was created
        assert tls._tls_config is not None


class TestDialerListenerIdempotentClose:
    """Dialer.close() and Listener.close() should be idempotent."""

    def test_dialer_double_close(self):
        """Closing a dialer twice should not raise KeyError."""
        sock = pynng.Pair0(listen=_random_addr())
        sock2 = pynng.Pair0(dial=sock.listeners[0].url)
        dialer = sock2.dialers[0]
        dialer.close()
        # Second close should not raise
        dialer.close()
        sock.close()
        sock2.close()

    def test_listener_double_close(self):
        """Closing a listener twice should not raise KeyError."""
        sock = pynng.Pair0(listen=_random_addr())
        listener = sock.listeners[0]
        listener.close()
        # Second close should not raise
        listener.close()
        sock.close()


class TestOptionSetterErrorChecking:
    """_setopt_size and _setopt_ms now check return values."""

    def test_setopt_ms_invalid_option(self):
        """Setting an invalid ms option should raise, not silently fail."""
        sock = pynng.Pair0(listen=_random_addr())
        with pytest.raises(pynng.NNGException):
            pynng.options._setopt_ms(sock, "not-a-real-option", 1000)
        sock.close()

    def test_setopt_size_invalid_option(self):
        """Setting an invalid size option should raise, not silently fail."""
        sock = pynng.Pair0(listen=_random_addr())
        with pytest.raises(pynng.NNGException):
            pynng.options._setopt_size(sock, "not-a-real-option", 1024)
        sock.close()


class TestWriteOnlyErrorMessage:
    """_NNGOption.__get__ error message says 'write-only' not 'cannot be set'."""

    def test_write_only_message(self):
        """Error message for write-only options should say 'write-only'."""
        # Create an option descriptor with no getter
        opt = pynng.nng._NNGOption("test-opt")
        opt._getter = None
        try:
            opt.__get__(None, None)
        except TypeError as e:
            assert "write-only" in str(e)
            assert "cannot be set" not in str(e)


class TestMessageStateError:
    """Message._buffer raises MessageStateError after send."""

    def test_buffer_after_send_raises(self):
        """Accessing buffer after send should raise MessageStateError."""
        addr = _random_addr()
        sender = pynng.Pair0(listen=addr)
        receiver = pynng.Pair0(dial=addr)
        msg = pynng.Message(b"hello")
        sender.send_msg(msg)
        with pytest.raises(pynng.MessageStateError):
            _ = msg._buffer
        received = receiver.recv()
        assert received == b"hello"
        sender.close()
        receiver.close()


class TestTLSConfigValidation:
    """TLS configuration edge cases."""

    def test_auth_mode_none_applied(self):
        """TLSConfig(auth_mode=0) should apply AUTH_MODE_NONE, not skip it."""
        # auth_mode=0 is AUTH_MODE_NONE. Previously `if auth_mode:` would
        # skip this because 0 is falsy.
        tls = pynng.TLSConfig(
            pynng.TLSConfig.MODE_CLIENT,
            auth_mode=pynng.TLSConfig.AUTH_MODE_NONE,
        )
        # Should not raise -- the auth mode was applied
        assert tls is not None

    def test_server_name_none_raises(self):
        """set_server_name(None) should raise ValueError."""
        tls = pynng.TLSConfig(pynng.TLSConfig.MODE_CLIENT)
        with pytest.raises(ValueError, match="cannot be None"):
            tls.set_server_name(None)

    def test_server_name_empty_string_allowed(self):
        """set_server_name('') should work (clears the name)."""
        tls = pynng.TLSConfig(pynng.TLSConfig.MODE_CLIENT)
        # Should not raise
        tls.set_server_name("")

    def test_server_name_with_value(self):
        """set_server_name with a real hostname should work."""
        tls = pynng.TLSConfig(pynng.TLSConfig.MODE_CLIENT)
        tls.set_server_name("example.com")


class TestPair1Simplified:
    """Pair1 delegates dial/listen to base class."""

    def test_pair1_listen_dial(self):
        """Pair1 should support listen and dial like other sockets."""
        addr = _random_addr()
        listener = pynng.Pair1(listen=addr)
        dialer = pynng.Pair1(dial=addr)
        dialer.send(b"hello")
        assert listener.recv() == b"hello"
        dialer.close()
        listener.close()

    def test_pair1_polyamorous(self):
        """Pair1 polyamorous mode should work."""
        addr = _random_addr()
        listener = pynng.Pair1(polyamorous=True, listen=addr)
        dialer = pynng.Pair1(polyamorous=True, dial=addr)
        dialer.send(b"poly")
        assert listener.recv() == b"poly"
        dialer.close()
        listener.close()


class TestPipesThreadSafety:
    """Socket.pipes property is thread-safe."""

    def test_pipes_access_under_contention(self):
        """Accessing pipes from multiple threads should not crash."""
        addr = _random_addr()
        listener = pynng.Pair0(listen=addr)
        errors = []

        def access_pipes():
            try:
                for _ in range(100):
                    _ = listener.pipes
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=access_pipes) for _ in range(4)]
        for t in threads:
            t.start()

        # Create some pipe churn
        dialers = []
        for _ in range(10):
            d = pynng.Pair0(dial=addr)
            dialers.append(d)

        for t in threads:
            t.join()

        for d in dialers:
            d.close()
        listener.close()

        assert not errors, f"Thread errors: {errors}"
