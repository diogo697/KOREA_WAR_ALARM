import asyncio

import httpx
import pytest

from korea_war_alarm.collectors import PollCollector
from korea_war_alarm.config import Source


def source():
    return Source(
        id="test",
        publisher="test",
        url="https://example.org/feed",
        operator_country="US",
        enabled=True,
        terms_reviewed=True,
    )


@pytest.mark.parametrize("failure", ["timeout", "429", "malformed", "disconnect"])
async def test_failure_isolation(failure):
    def handler(request):
        if request.url.path == "/ok":
            return httpx.Response(
                200, content=b'<rss version="2.0"><channel><title>ok</title></channel></rss>'
            )
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout")
        if failure == "disconnect":
            raise httpx.RemoteProtocolError("disconnect")
        if failure == "429":
            return httpx.Response(429, headers={"Retry-After": "600"})
        return httpx.Response(200, content=b"<broken>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bad = PollCollector(source(), lambda _: None, lambda _: None, client)
        good = PollCollector(
            source().model_copy(update={"url": "https://example.org/ok"}),
            lambda _: None,
            lambda _: None,
            client,
        )
        delays = await asyncio.gather(bad.once(), good.once())
        assert not (await bad.health()).healthy
        assert (await good.health()).healthy
        if failure == "429":
            assert delays[0] >= 600


async def test_conditional_request_and_recovery():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                headers={"ETag": '"v1"'},
                content=b'<rss version="2.0"><channel><title>ok</title></channel></rss>',
            )
        return httpx.Response(304)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = PollCollector(source(), lambda _: None, lambda _: None, client)
        await collector.once()
        await collector.once()
        assert calls[1].headers["If-None-Match"] == '"v1"'
        assert (await collector.health()).healthy
