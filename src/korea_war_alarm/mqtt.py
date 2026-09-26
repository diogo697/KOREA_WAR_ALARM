import asyncio
import json
import os

from .config import Config
from .models import utcnow
from .storage import Store


def mqtt_payload(alert, heartbeat: str | None) -> dict:
    return {
        "level": alert.level.rank,
        "active": int(alert.active),
        "seq": alert.seq,
        "updated_at": alert.updated_at.isoformat(),
        "heartbeat": heartbeat,
    }


async def mqtt_worker(config: Config):
    import paho.mqtt.client as mqtt

    store = Store(config.database)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    settings = config.mqtt
    username, password = (
        os.environ.get(settings.username_env),
        os.environ.get(settings.password_env),
    )
    if username:
        client.username_pw_set(username, password)
    if settings.tls:
        client.tls_set()
    client.will_set(
        f"{settings.topic_prefix}/status", json.dumps({"status": "offline"}), qos=1, retain=True
    )
    try:
        await asyncio.to_thread(client.connect, settings.host, settings.port, 30)
        client.loop_start()
        while True:
            alert = store.alert()
            heartbeat = store.state("heartbeat")
            messages = {
                "alert": mqtt_payload(alert, heartbeat),
                "status": {
                    "status": "running",
                    "updated_at": utcnow().isoformat(),
                    "heartbeat": heartbeat,
                },
                "incidents": [
                    i.model_dump(mode="json") for i in store.incidents(active=True, limit=50)
                ],
            }
            for suffix, payload in messages.items():
                result = client.publish(
                    f"{settings.topic_prefix}/{suffix}", json.dumps(payload), qos=1, retain=True
                )
                await asyncio.to_thread(result.wait_for_publish, 5)
                if not result.is_published():
                    raise TimeoutError("MQTT PUBACK timeout")
            with store.db:
                store.set_state(
                    "mqtt_health", {"healthy": True, "updated_at": utcnow().isoformat()}
                )
            await asyncio.sleep(1)
    finally:
        with store.db:
            store.set_state("mqtt_health", {"healthy": False, "updated_at": utcnow().isoformat()})
        client.disconnect()
        client.loop_stop()
        store.close()
