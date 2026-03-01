Async Usage Guide
=================

Both :class:`~pynng.Socket` and :class:`~pynng.Context` support modern Python
async patterns, making it natural to use pynng in async code with either
`Trio`_ or :mod:`asyncio`.

Async Context Manager (``async with``)
---------------------------------------

Sockets and Contexts can be used as async context managers, mirroring the
synchronous ``with`` statement. The socket or context is automatically closed
when the block exits:

.. literalinclude:: snippets/async_with_example.py
   :language: python

This is equivalent to the synchronous ``with pynng.Pair0(...) as s:`` pattern,
but suitable for use inside ``async def`` functions.

Async Iteration (``async for``)
-------------------------------

Sockets and Contexts support async iteration, enabling a clean loop over
incoming messages. Internally, each iteration calls :meth:`~pynng.Socket.arecv`
and stops when the socket is closed (by catching :class:`~pynng.Closed` and
raising ``StopAsyncIteration``):

Using Trio:

.. literalinclude:: snippets/async_for_example.py
   :language: python

Using asyncio:

.. literalinclude:: snippets/async_for_asyncio_example.py
   :language: python

.. note::

   When the socket is closed, the ``async for`` loop exits cleanly via
   ``StopAsyncIteration``. Other exceptions such as ``Timeout`` propagate
   normally.

Async Close (``aclose()``)
--------------------------

Both :class:`~pynng.Socket` and :class:`~pynng.Context` provide an
:meth:`~pynng.Socket.aclose` method for consistency with Python's async
resource management conventions (e.g., ``aclose()`` on async generators).
It delegates to the synchronous :meth:`~pynng.Socket.close` since the
underlying NNG close operation is non-blocking.

.. _Trio: https://trio.readthedocs.io
