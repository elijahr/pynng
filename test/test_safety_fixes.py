"""Tests for safety and concurrency behaviors."""

import threading

import pytest

import pynng


def _random_addr():
    return "inproc://test-safety-{}".format(id(object()))


class TestDelGuards:
    """Graceful cleanup when __del__ runs on already-closed objects."""

    def test_socket_del_after_close(self):
        """Socket.__del__ tolerates a previously closed socket."""
        sock = pynng.Pair0(listen=_random_addr())
        sock.close()
        sock.__del__()

    def test_context_del_after_close(self):
        """Context.__del__ tolerates a previously closed context."""
        sock = pynng.Rep0(listen=_random_addr())
        ctx = sock.new_context()
        ctx.close()
        ctx.__del__()
        sock.close()

    def test_tls_config_del_partially_initialized(self):
        """TLSConfig.__del__ tolerates a partially initialized instance."""
        tls = pynng.TLSConfig.__new__(pynng.TLSConfig)
        tls.__del__()

    def test_tls_config_del_after_normal_init(self):
        """TLSConfig cleans up normally when garbage collected."""
        tls = pynng.TLSConfig(pynng.TLSConfig.MODE_CLIENT)
        assert tls._tls_config is not None


class TestDialerListenerIdempotentClose:
    """Dialer and Listener close is idempotent."""

    def test_dialer_double_close(self):
        """Closing a dialer twice does not raise."""
        sock = pynng.Pair0(listen=_random_addr())
        sock2 = pynng.Pair0(dial=sock.listeners[0].url)
        dialer = sock2.dialers[0]
        dialer.close()
        dialer.close()
        sock.close()
        sock2.close()

    def test_listener_double_close(self):
        """Closing a listener twice does not raise."""
        sock = pynng.Pair0(listen=_random_addr())
        listener = sock.listeners[0]
        listener.close()
        listener.close()
        sock.close()


class TestOptionSetterErrorChecking:
    """Option setters propagate NNG errors."""

    def test_setopt_ms_invalid_option(self):
        """Setting an invalid ms option raises NNGException."""
        sock = pynng.Pair0(listen=_random_addr())
        with pytest.raises(pynng.NNGException):
            pynng.options._setopt_ms(sock, "not-a-real-option", 1000)
        sock.close()

    def test_setopt_size_invalid_option(self):
        """Setting an invalid size option raises NNGException."""
        sock = pynng.Pair0(listen=_random_addr())
        with pytest.raises(pynng.NNGException):
            pynng.options._setopt_size(sock, "not-a-real-option", 1024)
        sock.close()


class TestWriteOnlyOptionError:
    """Write-only options report clear error messages."""

    def test_write_only_message(self):
        """Reading a write-only option says 'write-only' in the error."""
        opt = pynng.nng._NNGOption("test-opt")
        opt._getter = None
        with pytest.raises(TypeError, match="write-only"):
            opt.__get__(None, None)


class TestMessageBufferAfterSend:
    """Message buffer access after send."""

    def test_buffer_after_send_raises(self):
        """Accessing _buffer after send raises MessageStateError."""
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
    """TLS configuration validation."""

    def test_auth_mode_none_applied(self):
        """auth_mode=AUTH_MODE_NONE is applied."""
        tls = pynng.TLSConfig(
            pynng.TLSConfig.MODE_CLIENT,
            auth_mode=pynng.TLSConfig.AUTH_MODE_NONE,
        )
        assert tls is not None

    def test_server_name_none_raises(self):
        """set_server_name(None) raises ValueError."""
        tls = pynng.TLSConfig(pynng.TLSConfig.MODE_CLIENT)
        with pytest.raises(ValueError, match="cannot be None"):
            tls.set_server_name(None)

    def test_server_name_empty_string_clears(self):
        """set_server_name('') clears the server name."""
        tls = pynng.TLSConfig(pynng.TLSConfig.MODE_CLIENT)
        tls.set_server_name("")

    def test_server_name_set(self):
        """set_server_name accepts a hostname."""
        tls = pynng.TLSConfig(pynng.TLSConfig.MODE_CLIENT)
        tls.set_server_name("example.com")


class TestPair1:
    """Pair1 socket behavior."""

    def test_pair1_listen_dial(self):
        """Pair1 supports listen and dial."""
        addr = _random_addr()
        listener = pynng.Pair1(listen=addr)
        dialer = pynng.Pair1(dial=addr)
        dialer.send(b"hello")
        assert listener.recv() == b"hello"
        dialer.close()
        listener.close()

    def test_pair1_polyamorous(self):
        """Pair1 polyamorous mode sends and receives."""
        addr = _random_addr()
        listener = pynng.Pair1(polyamorous=True, listen=addr)
        dialer = pynng.Pair1(polyamorous=True, dial=addr)
        dialer.send(b"poly")
        assert listener.recv() == b"poly"
        dialer.close()
        listener.close()


class TestPipesThreadSafety:
    """Socket.pipes is safe to access from multiple threads."""

    def test_pipes_access_under_contention(self):
        """Concurrent pipes access with connection churn does not crash."""
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
