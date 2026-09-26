import asyncio
import json

from korea_war_alarm.config import MQTT, Config
from korea_war_alarm.core import Core
from korea_war_alarm.models import Category
from korea_war_alarm.mqtt import mqtt_worker
from korea_war_alarm.storage import Store


async def test_critical_published_with_qos1_to_local_broker(tmp_path, event_factory):
    received = {}
    complete = asyncio.Event()

    async def broker(reader, writer):
        try:
            while True:
                header = (await reader.readexactly(1))[0]
                remaining, multiplier = 0, 1
                while True:
                    byte = (await reader.readexactly(1))[0]
                    remaining += (byte & 127) * multiplier
                    if not byte & 128:
                        break
                    multiplier *= 128
                body = await reader.readexactly(remaining)
                kind = header >> 4
                if kind == 1:
                    writer.write(b"\x20\x02\x00\x00")
                elif kind == 3:
                    length = int.from_bytes(body[:2], "big")
                    topic = body[2 : 2 + length].decode()
                    packet_id = body[2 + length : 4 + length]
                    received[topic] = json.loads(body[4 + length :])
                    writer.write(b"\x40\x02" + packet_id)
                    if len(received) == 3:
                        complete.set()
                elif kind == 14:
                    return
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(broker, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    config = Config(
        database=str(tmp_path / "state.sqlite"),
        mqtt=MQTT(enabled=True, host="127.0.0.1", port=port, tls=False),
    )
    store = Store(config.database)
    core = Core(store, config)
    core.ingest(event_factory())
    core.ingest(event_factory(1))
    core.ingest(event_factory(2, source_type="sensor", category=Category.SEISMIC_EVENT))
    task = asyncio.create_task(mqtt_worker(config))
    try:
        await asyncio.wait_for(complete.wait(), 10)
        assert received["korea-war-alarm/alert"]["level"] == 4
        assert received["korea-war-alarm/alert"]["seq"] == store.alert().seq
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()
        store.close()
