import pynng
import trio


async def receiver(socket):
    async for msg in socket:
        print(f'Received: {msg}')


async def sender(address):
    async with pynng.Pair0(dial=address) as s:
        for i in range(5):
            await s.asend(f'message {i}'.encode())
            await trio.sleep(0.1)


async def main():
    address = 'inproc://async-for-demo'
    async with pynng.Pair0(listen=address, recv_timeout=2000) as s:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(receiver, s)
            nursery.start_soon(sender, address)
            await trio.sleep(1)
            nursery.cancel_scope.cancel()


trio.run(main)
