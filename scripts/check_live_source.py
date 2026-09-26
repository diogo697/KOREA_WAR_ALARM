"""기본 활성 소스만 한 번 수집해 연결/파싱 상태를 확인한다. 실제 경보는 보내지 않는다."""

import asyncio
import json

import httpx

from korea_war_alarm.collectors import make_collector
from korea_war_alarm.config import load_config


async def main():
    config = load_config("config.example.yaml")
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        for source in config.sources:
            if not source.enabled:
                continue
            events = []
            connected = asyncio.Event()
            collector = make_collector(
                source,
                events.append,
                lambda health: connected.set() if health.healthy else None,
                client,
            )
            if source.kind == "emsc_ws":
                task = asyncio.create_task(collector.start())
                try:
                    await asyncio.wait_for(connected.wait(), 15)
                except TimeoutError:
                    pass
                finally:
                    await collector.stop()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            else:
                await collector.once()
            print(
                json.dumps(
                    {
                        "source": source.id,
                        "health": (await collector.health()).model_dump(mode="json"),
                        "parsed_events": len(events),
                    }
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
