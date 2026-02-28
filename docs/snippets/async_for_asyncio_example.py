import asyncio
import pynng


async def receiver(socket):
    async for msg in socket:
        print(f'Received: {msg}')


async def sender(address):
    async with pynng.Pair0(dial=address) as s:
        for i in range(5):
            await s.asend(f'message {i}'.encode())
            await asyncio.sleep(0.1)


async def main():
    address = 'inproc://async-for-asyncio-demo'
    async with pynng.Pair0(listen=address, recv_timeout=2000) as s:
        recv_task = asyncio.create_task(receiver(s))
        send_task = asyncio.create_task(sender(address))
        await send_task
        await asyncio.sleep(0.5)
        recv_task.cancel()
        try:
            await recv_task
        except asyncio.CancelledError:
            pass


asyncio.run(main())
